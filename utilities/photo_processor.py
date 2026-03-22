"""
Individual Photo Processing mit subprocess (GDAL command-line tools).

Verarbeitet Einzelbilder (Nadir/Oblique) - EXIF-Extraktion und Thumbnail-Erstellung.
Basiert auf dem ursprünglichen rm_publish_einzelbilder.py Ansatz.

ÄNDERUNGEN:
- Kopiert Original-Foto in temp_dir und benennt gemäß Asset-Definition um
- Upload erfolgt DIREKT nach Verarbeitung jedes Fotos (vor photos.append)
- Verwendet ausschließlich proxy_handler.py für Proxy-Verwaltung
- NEU v2.1: TIF-zu-JPEG Konvertierung für EBN/EBO mit GPS-EXIF aus GeoTransform
- NEU v2.2: Nord-oben Normalisierung via GeoTransform-Rotation (Solution B)
- NEU v2.2: Sequentielle ms-Offsets für Burst-Bilder mit identischem Timestamp
- NEU v2.2: Pro-Timestamp ein repräsentatives Bild auswählen → convert+upload sofort
"""

import os
import math
import subprocess
import json
import logging
import shutil
import struct
import re
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from configuration import THUMBNAIL_CONFIG, ProductType, generate_item_name, generate_asset_name
from utilities.file_handler import get_jpg_files
# publish_to_stac wird lazy importiert (innerhalb der Funktion) um zirkuläre
# Imports zu vermeiden: util_publish_stac_fsdi → utilities → photo_processor

logger = logging.getLogger(__name__)


# ==============================================================================
# SCHNELLER TIFF-HEADER-PARSER (kein gdalinfo-Subprocess nötig)
# Liest nur die ersten 64KB jeder Datei — drastisch schneller auf Netzlaufwerken
# ==============================================================================

def _fast_read_tiff_geodata(path: Path) -> dict:
    """
    Liest GeoTIFF-Metadaten direkt aus dem TIFF-Header — kein gdalinfo-Subprocess.
    Liest maximal 64KB pro Datei. Gibt {} bei Fehler zurück.

    Unterstützt:
      - Classic TIFF (magic=42) und BigTIFF (magic=43)
      - Little-Endian (II) und Big-Endian (MM)
      - ModelTransformationTag (34264): vollständige Affin-Matrix inkl. Rotation
      - ModelPixelScale (33550) + ModelTiepoint (33922): einfache Nord-oben-Bilder

    Returns dict mit Schlüsseln:
      width, height   int
      datetime        str  "YYYY:MM:DD HH:MM:SS"
      geotransform    tuple (origin_x, px_w, row_rot, origin_y, col_rot, px_h)
    """
    try:
        with open(path, 'rb') as f:
            raw = f.read(65536)

        if len(raw) < 8:
            return {}

        if raw[:2] == b'II':   bo = '<'
        elif raw[:2] == b'MM': bo = '>'
        else: return {}

        magic = struct.unpack_from(bo + 'H', raw, 2)[0]

        if magic == 43:       # BigTIFF
            if len(raw) < 16: return {}
            ifd_offset = struct.unpack_from(bo + 'Q', raw, 8)[0]
            entry_size = 20
            is_big = True
        elif magic == 42:     # Classic TIFF
            ifd_offset = struct.unpack_from(bo + 'I', raw, 4)[0]
            entry_size = 12
            is_big = False
        else:
            return {}

        if ifd_offset + 2 > len(raw):
            return {}

        n_entries = struct.unpack_from(bo + 'H', raw, ifd_offset)[0]
        if n_entries > 2000:
            return {}

        # IFD-Einträge parsen
        tags = {}
        base = ifd_offset + 2
        for i in range(n_entries):
            pos = base + i * entry_size
            if pos + entry_size > len(raw):
                break
            if is_big:
                tag, dtype, count = struct.unpack_from(bo + 'HHQ', raw, pos)
                val_off = struct.unpack_from(bo + 'Q', raw, pos + 12)[0]
            else:
                tag, dtype, count = struct.unpack_from(bo + 'HHI', raw, pos)
                val_off = struct.unpack_from(bo + 'I', raw, pos + 8)[0]
            tags[tag] = (dtype, count, val_off)

        def read_doubles(count, val_off):
            size = count * 8
            inline = 8 if is_big else 4
            if size <= inline:
                packed = struct.pack(bo + ('Q' if is_big else 'I'), val_off)
                data = packed[:size]
            else:
                if val_off + size > len(raw):
                    return None
                data = raw[val_off:val_off + size]
            return struct.unpack_from(bo + str(count) + 'd', data)

        def read_ascii(count, val_off):
            inline = 8 if is_big else 4
            if count <= inline:
                packed = struct.pack(bo + ('Q' if is_big else 'I'), val_off)
                return packed[:count].decode('ascii', errors='ignore').rstrip('\x00 ')
            if val_off + count > len(raw):
                return None
            return raw[val_off:val_off + count].decode('ascii', errors='ignore').rstrip('\x00 ')

        def read_long(val_off):
            return val_off  # stored inline for count=1

        result = {}

        # ImageWidth (256), ImageLength (257)
        for tag, key in [(256, 'width'), (257, 'height')]:
            if tag in tags:
                result[key] = tags[tag][2] & 0xFFFFFFFF  # inline value

        # DateTime (306)
        if 306 in tags:
            dtype, count, val_off = tags[306]
            v = read_ascii(count, val_off)
            if v:
                result['datetime'] = v.strip()

        # GeoTransform — ModelTransformationTag (34264) hat Vorrang (unterstützt Rotation)
        if 34264 in tags:
            dtype, count, val_off = tags[34264]
            v = read_doubles(count, val_off)
            if v and len(v) >= 16:
                # 4×4-Matrix row-major: [Mxx, Mxy, Mxz, Tx,  Myx, Myy, Myz, Ty, ...]
                # GeoTransform: (origin_x, px_w, row_rot, origin_y, col_rot, px_h)
                #              = (Tx,       Mxx,  Mxy,    Ty,       Myx,     Myy)
                #              = (v[3],    v[0], v[1],   v[7],    v[4],    v[5])
                result['geotransform'] = (v[3], v[0], v[1], v[7], v[4], v[5])

        if 'geotransform' not in result and 33550 in tags and 33922 in tags:
            scale = read_doubles(tags[33550][1], tags[33550][2])
            tp    = read_doubles(tags[33922][1], tags[33922][2])
            if scale and tp and len(scale) >= 2 and len(tp) >= 6:
                result['geotransform'] = (tp[3], scale[0], 0.0, tp[4], 0.0, -scale[1])

        return result

    except Exception:
        return {}


def _fast_tiff_to_gdalinfo_text(path: Path) -> str:
    """
    Synthetisiert einen minimalen gdalinfo-ähnlichen Text aus dem schnellen
    TIFF-Header-Parser. Wird als Ersatz für den gdalinfo-Subprocess verwendet.

    Der resultierende Text enthält nur die Felder die vom Rest des Codes
    benötigt werden: GeoTransform, Size, TIFFTAG_DATETIME, Corner Coordinates.
    """
    data = _fast_read_tiff_geodata(path)
    if not data:
        return ''

    lines = []

    if 'width' in data and 'height' in data:
        lines.append(f"Size is {data['width']}, {data['height']}")

    if 'datetime' in data:
        lines.append(f"  TIFFTAG_DATETIME={data['datetime']}")

    gt = data.get('geotransform')
    if gt and 'width' in data and 'height' in data:
        ox, pw, rr, oy, cr, ph = gt
        w, h = data['width'], data['height']
        lines.append("GeoTransform =")
        lines.append(f"  {ox}, {pw}, {rr}")
        lines.append(f"  {oy}, {cr}, {ph}")

        # Corner Coordinates aus GeoTransform berechnen
        def corner(col, row):
            return ox + pw * col + rr * row, oy + cr * col + ph * row

        ul = corner(0, 0)
        ll = corner(0, h)
        lr = corner(w, h)
        ur = corner(w, 0)
        lines.append("Corner Coordinates:")
        lines.append(f"Upper Left  ( {ul[0]:.7f},  {ul[1]:.7f})")
        lines.append(f"Lower Left  ( {ll[0]:.7f},  {ll[1]:.7f})")
        lines.append(f"Lower Right ( {lr[0]:.7f},  {lr[1]:.7f})")
        lines.append(f"Upper Right ( {ur[0]:.7f},  {ur[1]:.7f})")
        cx = (ul[0] + lr[0]) / 2
        cy = (ul[1] + lr[1]) / 2
        lines.append(f"Center      ( {cx:.7f},  {cy:.7f})")

    return '\n'.join(lines)


# ==============================================================================
# TIF → JPEG KONVERTIERUNG (NEU v2.1)
# ==============================================================================

def _parse_geotransform_center(gdalinfo_output: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Extrahiert Center-Koordinate (lat/lon WGS84) aus gdalinfo Text-Output.

    Die Center-Zeile sieht so aus:
      Center      (   7.1009958,  46.8208152) (  7d 6' 3.58"E, 46d49'14.93"N)

    Args:
        gdalinfo_output: Vollständiger Text-Output von gdalinfo

    Returns:
        Tuple (latitude, longitude) oder (None, None)
    """
    # Direkte Dezimal-Koordinaten aus der Center-Zeile
    pattern = r'Center\s+\(\s*([\-\d\.]+),\s*([\-\d\.]+)\)'
    match = re.search(pattern, gdalinfo_output)
    if match:
        # gdalinfo gibt (lon, lat) aus
        lon = float(match.group(1))
        lat = float(match.group(2))
        return round(lat, 6), round(lon, 6)

    # Fallback: GeoTransform manuell berechnen
    gt_pattern = r'GeoTransform\s*=\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+),.*?\n\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+)'
    size_pattern = r'Size is (\d+), (\d+)'

    gt_match = re.search(gt_pattern, gdalinfo_output, re.DOTALL)
    size_match = re.search(size_pattern, gdalinfo_output)

    if gt_match and size_match:
        origin_x = float(gt_match.group(1))
        pixel_w   = float(gt_match.group(2))
        origin_y = float(gt_match.group(3))
        pixel_h   = float(gt_match.group(4))
        cols = int(size_match.group(1))
        rows = int(size_match.group(2))

        center_lon = origin_x + pixel_w * cols / 2.0
        center_lat = origin_y + pixel_h * rows / 2.0
        return round(center_lat, 6), round(center_lon, 6)

    return None, None


def _parse_tifftag_datetime(gdalinfo_output: str) -> Optional[str]:
    """
    Extrahiert TIFFTAG_DATETIME aus gdalinfo Text-Output.

    Format in gdalinfo: TIFFTAG_DATETIME=2025:07:10 08:00:28

    Args:
        gdalinfo_output: Vollständiger Text-Output von gdalinfo

    Returns:
        Datetime-String im EXIF-Format "YYYY:MM:DD HH:MM:SS" oder None
    """
    pattern = r'TIFFTAG_DATETIME\s*=\s*(\d{4}:\d{2}:\d{2}\s+\d{2}:\d{2}:\d{2})'
    match = re.search(pattern, gdalinfo_output)
    if match:
        return match.group(1).strip()
    return None


# ==============================================================================
# NEU v2.2 — FIX 1: NORD-OBEN NORMALISIERUNG (Solution B)
# ==============================================================================

def _geotransform_rotation_deg(gdalinfo_output: str) -> Optional[float]:
    """
    Berechnet den Rotationswinkel (Grad, im Uhrzeigersinn) des Bildes relativ
    zu Nord, abgeleitet aus den GeoTransform-Schrägstellungs-Koeffizienten.

    GeoTransform = [origin_x, px_w, row_rot, origin_y, col_rot, px_h]
      row_rot (Koeff [2]) und col_rot (Koeff [4]) kodieren Rotation/Scherung.

    Für eine reine Drehung um Winkel θ im Uhrzeigersinn gilt:
      row_rot =  px_w * sin(θ)
      col_rot = -px_h * sin(θ)   (px_h negativ für nord-oben)

    Sonderfall: pixel_height > 0 und Schrägstellung ≈ 0  →  gibt 180.0 zurück
    Normalfall: pixel_height < 0 und Schrägstellung ≈ 0  →  gibt 0.0 zurück

    Returns:
        Rotationswinkel in Grad (im Uhrzeigersinn), oder None wenn nicht parsebar.
    """
    pattern = (
        r'GeoTransform\s*=\s*'
        r'([\-\d\.e\+]+),\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+)\s*\n'
        r'\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+)'
    )
    m = re.search(pattern, gdalinfo_output)
    if not m:
        return None

    px_w    = float(m.group(2))
    row_rot = float(m.group(3))
    col_rot = float(m.group(5))
    px_h    = float(m.group(6))

    # Reine 180°-Drehung: Schrägstellung ≈ 0, pixel_height > 0 (= nord-unten)
    skew_threshold = 1e-7
    if abs(row_rot) < skew_threshold and abs(col_rot) < skew_threshold:
        return 180.0 if px_h > 0 else 0.0

    # Allgemeine Rotation aus Schrägstellungs-Koeffizienten
    angle_rad = math.atan2(row_rot, px_w)
    return math.degrees(angle_rad)


def _rotate_to_north_up(jpg_path: Path, angle_deg: float, quality: int = 85) -> bool:
    """
    Rotiert ein JPEG so dass Nord oben ist, indem gdalwarp das Bild
    anhand der eingebetteten Georeferenzierung umprojiziert.

    Für beliebige Winkel (nicht nur 180°): gdalwarp mit -t_srs EPSG:4326
    reprojeziiert das Bild so dass der Pixelursprung (0,0) geogr. Nordwesten
    entspricht — das Ergebnis ist immer nord-oben.

    Für den reinen 180°-Fall wird stattdessen -a_ullr in gdal_translate bevorzugt
    (verlustfrei, single-pass) — diese Funktion ist der Fallback für andere Winkel.

    Args:
        jpg_path:  Pfad zum JPEG (wird in-place ersetzt)
        angle_deg: Rotationswinkel des Originals (nur für Logging)
        quality:   JPEG-Qualität für das Ausgabebild

    Returns:
        True bei Erfolg, False bei Fehler
    """
    if abs(angle_deg) < 0.01:
        return True  # bereits nord-oben

    tmp = jpg_path.with_suffix('.rot_tmp.jpg')
    try:
        result = subprocess.run(
            [
                'gdalwarp',
                '-of', 'JPEG',
                '-co', f'QUALITY={quality}',
                '-r', 'bilinear',
                '-t_srs', 'EPSG:4326',
                str(jpg_path),
                str(tmp)
            ],
            capture_output=True,
            timeout=60,
            env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
        )
        if result.returncode == 0:
            tmp.replace(jpg_path)
            logger.info(f"     ✓ Nord-oben Normalisierung ({angle_deg:.1f}°) via gdalwarp")
            return True
        else:
            logger.warning(
                f"     ⚠ gdalwarp fehlgeschlagen (rc={result.returncode}): "
                f"{result.stderr[:200] if result.stderr else '—'}"
            )
    except subprocess.TimeoutExpired:
        logger.warning(f"     ⚠ gdalwarp Timeout bei Rotation")
    except Exception as e:
        logger.warning(f"     ⚠ gdalwarp Rotation fehlgeschlagen: {e}")
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return False


# ==============================================================================
# NEU v2.3 — MINIMALE DATEIAUSWAHL FÜR FLÄCHENDECKUNG (Greedy Set Cover)
# Exakte Polygon-Footprints aus Corner Coordinates — korrekt für gedrehte Bilder
# ==============================================================================

def _parse_footprint_from_gdalinfo(gdalinfo_output: str) -> Optional[List[Tuple[float, float]]]:
    """
    Extrahiert den exakten Polygon-Footprint (4 Eckpunkte) aus gdalinfo-Output.
    Verwendet die 4 Corner Coordinates (lon, lat) direkt — korrekt für gedrehte
    Bilder, da die Ecken im Geographischen Raum angegeben werden.

    Returns:
        Liste von 4 (lon, lat) Punkten im CCW-Uhrzeigersinn, oder None
    """
    pattern = r'(Upper Left|Lower Left|Lower Right|Upper Right)\s+\(\s*([\-\d\.]+),\s*([\-\d\.]+)\)'
    matches = re.findall(pattern, gdalinfo_output)
    if len(matches) < 4:
        # Fallback: BBox aus GeoTransform
        gt_m = re.search(
            r'GeoTransform\s*=\s*'
            r'([\-\d\.e\+]+),\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+)\s*\n'
            r'\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+)',
            gdalinfo_output
        )
        sz_m = re.search(r'Size is (\d+), (\d+)', gdalinfo_output)
        if not (gt_m and sz_m):
            return None
        ox,pw,rr = float(gt_m.group(1)),float(gt_m.group(2)),float(gt_m.group(3))
        oy,cr,ph = float(gt_m.group(4)),float(gt_m.group(5)),float(gt_m.group(6))
        cols,rows = int(sz_m.group(1)),int(sz_m.group(2))
        return [(ox,oy),(ox+pw*cols,oy+cr*cols),
                (ox+pw*cols+rr*rows,oy+cr*cols+ph*rows),(ox+rr*rows,oy+ph*rows)]

    # Build dict: label → (lon, lat)
    corners = {m[0]: (float(m[1]), float(m[2])) for m in matches}
    # CCW order: UL → LL → LR → UR
    order = ['Upper Left', 'Lower Left', 'Lower Right', 'Upper Right']
    poly = [corners[k] for k in order if k in corners]
    return poly if len(poly) == 4 else None


def _polygon_area_signed(verts: List[Tuple[float, float]]) -> float:
    """Signed shoelace area. Positive = CCW."""
    n = len(verts); area = 0.0
    for i in range(n):
        j = (i+1)%n
        area += verts[i][0]*verts[j][1] - verts[j][0]*verts[i][1]
    return area / 2.0


def _ensure_ccw(poly: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    return list(reversed(poly)) if _polygon_area_signed(poly) < 0 else list(poly)


def _point_in_convex_ccw(px: float, py: float, ccw_poly: List[Tuple[float, float]]) -> bool:
    """Test if point is inside CCW convex polygon."""
    n = len(ccw_poly)
    for i in range(n):
        x1,y1 = ccw_poly[i]; x2,y2 = ccw_poly[(i+1)%n]
        if (x2-x1)*(py-y1) - (y2-y1)*(px-x1) < -1e-10:
            return False
    return True


def _select_by_strip(tif_files: List[Path]) -> Optional[List[Path]]:
    """
    Erkennt das DMC-4 Dateinamen-Muster NNN_idXXXcLYYYYYY.tif und wählt
    pro Flugstreifen (NNN) genau eine Kameraposition aus.
    Kamera-Priorität: 150157 (Nadir-Mitte) > 150158 > 150156
    Returns: ausgewählte Dateien, oder None wenn Muster nicht erkannt.
    """
    from collections import defaultdict
    PATTERN     = re.compile(r'^(\d+)_id\d+cL(\d+)\.tif$', re.IGNORECASE)
    CAMERA_PRIO = ['150157', '150158', '150156']
    strips: dict = defaultdict(list)
    unmatched = 0
    for tif in tif_files:
        m = PATTERN.match(tif.name)
        if m: strips[int(m.group(1))].append({'path': tif, 'camera': m.group(2)})
        else: unmatched += 1
    if unmatched > len(tif_files) * 0.2:
        return None
    selected: List[Path] = []
    for strip_num in sorted(strips.keys()):
        files_in_strip = strips[strip_num]
        if len(files_in_strip) == 1:
            selected.append(files_in_strip[0]['path'])
        else:
            for cam in CAMERA_PRIO:
                chosen = next((f['path'] for f in files_in_strip if f['camera'] == cam), None)
                if chosen: selected.append(chosen); break
    logger.info(
        f"  Streifen-Muster erkannt: {len(strips)} Streifen × bis zu 3 Kameras "
        f"→ {len(selected)} Dateien (eine pro Streifen)"
    )
    return selected


def select_minimal_coverage_files(
    tif_files: List[Path],
    gdalinfo_cache: Dict[Path, str],
    coverage_threshold: float = 0.99,
    grid_resolution: int = 300,
) -> Tuple[List[Path], Dict[Path, List[Tuple[float, float]]]]:
    """
    Wählt die minimale Anzahl TIF-Dateien aus, die ≥coverage_threshold des
    Gesamtgebiets abdecken. Verwendet exakte Polygon-Footprints (Corner
    Coordinates aus gdalinfo) — korrekt für beliebig gedrehte Bilder.

    Algorithmus: Greedy Set Cover via Gitter-Sampling
      1. Polygon-Footprint jeder Datei aus gdalinfo extrahieren
      2. Gesamtgitter auf Union aller Footprints aufspannen
      3. Für jedes Gitterpunkt: welche Polygone decken ihn ab? (Vorberechnung)
      4. Iterativ das Polygon wählen, das die meisten noch unbedeckten Punkte hinzufügt
      5. Stopp wenn coverage_threshold erreicht

    Komplexität: O(N × R²) Vorberechnung + O(K × (N-K)) Greedy, wobei
    N=Anzahl Dateien, R=Gitterauflösung, K=Anzahl ausgewählter Dateien.

    Args:
        tif_files:          Sortierte Liste aller TIF-Dateien
        gdalinfo_cache:     {tif_path: gdalinfo_text}
        coverage_threshold: Abdeckungsgrad (Standard 0.99 = 99%)
        grid_resolution:    Gitterauflösung (300 = 90000 Punkte)

    Returns:
        (selected_files, footprint_map)
    """
    # Footprints extrahieren
    fp_map:  Dict[Path, List[Tuple[float, float]]] = {}
    no_fp:   List[Path] = []
    for tif in tif_files:
        fp = _parse_footprint_from_gdalinfo(gdalinfo_cache.get(tif, ''))
        if fp is not None:
            fp_map[tif] = _ensure_ccw(fp)
        else:
            no_fp.append(tif)
            logger.warning(f"  ⚠ Kein Footprint für {tif.name} — wird immer eingeschlossen")

    parseable = [t for t in tif_files if t in fp_map]
    if not parseable:
        return tif_files, fp_map

    polys = [fp_map[t] for t in parseable]

    # Gitter aufspannen
    all_x = [p[0] for poly in polys for p in poly]
    all_y = [p[1] for poly in polys for p in poly]
    xmin,xmax = min(all_x),max(all_x)
    ymin,ymax = min(all_y),max(all_y)
    R = grid_resolution
    dx = (xmax-xmin)/R; dy = (ymax-ymin)/R

    # Vorberechnung: Gitterpunkte pro Polygon (als frozenset von (i,j))
    logger.info(f"  Greedy Set Cover: {len(parseable)} Polygone, {R}×{R} Gitter...")
    poly_cells: List[set] = []
    for poly in polys:
        cells = set()
        # Bounding box des Polygons im Gitter
        px_vals = [p[0] for p in poly]; py_vals = [p[1] for p in poly]
        i0 = max(0, int((min(px_vals)-xmin)/dx))
        i1 = min(R-1, int((max(px_vals)-xmin)/dx)+1)
        j0 = max(0, int((min(py_vals)-ymin)/dy))
        j1 = min(R-1, int((max(py_vals)-ymin)/dy)+1)
        for i in range(i0, i1+1):
            for j in range(j0, j1+1):
                cx = xmin+(i+0.5)*dx; cy = ymin+(j+0.5)*dy
                if _point_in_convex_ccw(cx, cy, poly):
                    cells.add((i,j))
        poly_cells.append(cells)

    # Gesamtzahl Gitterpunkte in der Union
    total_cells = len(set().union(*poly_cells)) if poly_cells else 0
    if total_cells == 0:
        return tif_files, fp_map

    # Greedy-Schleife
    covered:    set       = set()
    selected:   List[int] = []
    remaining:  List[int] = list(range(len(parseable)))

    while remaining and len(covered) / total_cells < coverage_threshold:
        best_i = max(remaining, key=lambda i: len(poly_cells[i] - covered))
        best_new = len(poly_cells[best_i] - covered)
        if best_new == 0:
            break
        selected.append(best_i)
        remaining.remove(best_i)
        covered |= poly_cells[best_i]
        coverage = len(covered) / total_cells
        logger.info(
            f"  + {parseable[best_i].name}  "
            f"(+{best_new/total_cells:.1%} → gesamt {coverage:.1%})"
        )

    final_coverage = len(covered) / total_cells if total_cells else 1.0
    skipped = len(parseable) - len(selected)
    logger.info(
        f"  ✓ Auswahl: {len(selected)} von {len(tif_files)} Dateien "
        f"({skipped} übersprungen, {final_coverage:.1%} Abdeckung)"
    )

    result_files = [parseable[i] for i in selected] + no_fp
    return result_files, fp_map


# ==============================================================================
# NEU v2.2 — FIX 2: SEQUENTIELLE MS-OFFSETS FÜR BURST-TIMESTAMPS
# ==============================================================================

def _assign_sequential_ms_offsets(
    tif_files: List[Path],
    gdalinfo_cache: Dict[Path, str]
) -> Dict[Path, str]:
    """
    Weist TIF-Dateien mit identischem TIFFTAG_DATETIME einen sequentiellen
    Millisekunden-Offset zu, um STAC-Item-Kollisionen zu vermeiden.

    Vorgehen:
      1. Alle Dateien nach TIFFTAG_DATETIME gruppieren
      2. Innerhalb jeder Gruppe: Dateien nach den letzten zwei Ziffern des
         Dateinamens sortieren (z.B. "56" aus "001_id111cL150156")
      3. Offset :01, :02, :03, ... (zweistellig) pro Gruppe zuweisen

    Beispiel:
      001_id111cL150156.tif  →  08:00:28  →  "2025:07:10 08:00:28:01"
      001_id111cL150157.tif  →  08:00:28  →  "2025:07:10 08:00:28:02"
      001_id111cL150158.tif  →  08:00:28  →  "2025:07:10 08:00:28:03"

    Dateien mit einzigartigem Timestamp erhalten keinen Offset-Suffix.

    Args:
        tif_files:      Sortierte Liste aller TIF-Dateien
        gdalinfo_cache: {tif_path: gdalinfo_text}

    Returns:
        {tif_path: "YYYY:MM:DD HH:MM:SS[:NN]"}
        Ohne Suffix bei eindeutigem Timestamp, mit ":NN" (01-basiert) bei Kollision.
    """
    from collections import defaultdict

    # Timestamp pro Datei bestimmen
    ts_map: Dict[Path, Optional[str]] = {
        tif: _parse_tifftag_datetime(gdalinfo_cache.get(tif, ''))
        for tif in tif_files
    }

    # Nach Timestamp gruppieren
    groups: Dict[str, List[Path]] = defaultdict(list)
    for tif, ts in ts_map.items():
        key = ts if ts else f"__no_ts_{tif.stem}"
        groups[key].append(tif)

    result: Dict[Path, str] = {}

    for ts_key, group in groups.items():
        if len(group) == 1:
            # Eindeutiger Timestamp → Offset "00" (kein Burst)
            result[group[0]] = f"{ts_key}:00"
        else:
            # Gruppe nach id-Nummer im Dateinamen sortieren (NNN_idXXXcL...).
            # WICHTIG: re.sub(r'[^0-9]', '', stem) würde den Kamerasuffix
            # (150156/157/158) miteinbeziehen → alle gleich → Kollision.
            # Stattdessen: id-Nummer direkt extrahieren.
            def _sort_key(p: Path) -> str:
                m = re.search(r'_id(\d+)', p.stem, re.IGNORECASE)
                if m:
                    return m.group(1).zfill(10)
                # Fallback: Kamerasuffix entfernen, dann letzte Ziffern
                stem_clean = re.sub(r'cL\d+$', '', p.stem, flags=re.IGNORECASE)
                digits = re.sub(r'[^0-9]', '', stem_clean)
                return digits[-6:].zfill(6) if digits else p.stem

            sorted_group = sorted(group, key=_sort_key)

            for idx, tif in enumerate(sorted_group, start=1):
                result[tif] = f"{ts_key}:{idx:02d}"   # "2025:07:10 08:00:28:01"

    return result


def _decimal_to_dms_rational(decimal: float) -> List[Tuple[int, int]]:
    """
    Konvertiert Dezimalgrad zu DMS als Liste von (Zähler, Nenner)-Tupeln
    für EXIF-Rational-Encoding.

    Returns:
        [(deg_num, 1), (min_num, 1), (sec_num, 100), ...]
    """
    decimal = abs(decimal)
    deg = int(decimal)
    minutes_full = (decimal - deg) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60
    sec_num = int(round(seconds * 100))
    return [(deg, 1), (minutes, 1), (sec_num, 100)]


def _write_minimal_exif_gps(jpg_path: Path, lat: float, lon: float, dt_str: Optional[str], verbose: bool = True) -> bool:
    """
    Schreibt GPS-EXIF + DateTimeOriginal direkt in ein JPEG (in-place).

    EXIF-Inline-Regel: Werte die ≤ 4 Bytes benötigen werden direkt im
    IFD-Eintrag (value_offset-Feld) gespeichert, nicht als Pointer.
    GPSLatitudeRef / GPSLongitudeRef sind ASCII count=2 → immer INLINE.
    DateTimeOriginal (20 Bytes) und RATIONAL-Koordinaten (24 Bytes) → Pointer.

    Returns:
        True bei Erfolg, False bei Fehler
    """
    try:
        with open(jpg_path, 'rb') as f:
            jpeg_data = f.read()

        if jpeg_data[:2] != b'\xff\xd8':
            logger.warning(f"  ⚠ Kein gültiges JPEG: {jpg_path.name}")
            return False

        BIG = '>'

        def pack_rational(num, den):
            return struct.pack(f'{BIG}II', num, den)

        TYPE_ASCII    = 2
        TYPE_LONG     = 4
        TYPE_RATIONAL = 5

        TIFF_HDR_SIZE    = 8
        IFD0_ENTRIES     = 2
        IFD0_SIZE        = 2 + IFD0_ENTRIES * 12 + 4      # 30
        EXIF_IFD_ENTRIES = 1
        EXIF_IFD_SIZE    = 2 + EXIF_IFD_ENTRIES * 12 + 4  # 18
        GPS_IFD_ENTRIES  = 4
        GPS_IFD_SIZE     = 2 + GPS_IFD_ENTRIES * 12 + 4   # 54

        ifd0_offset     = TIFF_HDR_SIZE
        exif_ifd_offset = ifd0_offset     + IFD0_SIZE
        gps_ifd_offset  = exif_ifd_offset + EXIF_IFD_SIZE
        values_offset   = gps_ifd_offset  + GPS_IFD_SIZE

        # ms-Offset-Suffix abschneiden
        dt_exif = dt_str[:19] if dt_str else ''
        dt_ascii = (dt_exif.encode('ascii') + b'\x00')[:20].ljust(20, b'\x00')

        # Externe Wertedaten: nur DateTimeOriginal (20B) + Koordinaten (24B+24B)
        # GPSLatitudeRef + GPSLongitudeRef werden INLINE gespeichert (je 2 Bytes → ≤ 4B)
        off_dt  = values_offset       # 20 bytes → DateTimeOriginal
        off_lat = off_dt  + 20        # 24 bytes → GPSLatitude  (3×Rational)
        off_lon = off_lat + 24        # 24 bytes → GPSLongitude (3×Rational)

        # Inline-Werte für 2-Byte ASCII Ref-Felder:
        # Big-Endian: Zeichen in Byte 0, Rest mit 0x00 → "N\0\0\0" für N
        lat_ref_inline = b'N\x00\x00\x00' if lat >= 0 else b'S\x00\x00\x00'
        lon_ref_inline = b'E\x00\x00\x00' if lon >= 0 else b'W\x00\x00\x00'

        lat_rational = b''.join(pack_rational(n, d) for n, d in _decimal_to_dms_rational(lat))
        lon_rational = b''.join(pack_rational(n, d) for n, d in _decimal_to_dms_rational(lon))

        # IFD0
        ifd0  = struct.pack(f'{BIG}H', IFD0_ENTRIES)
        ifd0 += struct.pack(f'{BIG}HHII', 0x8769, TYPE_LONG, 1, exif_ifd_offset)
        ifd0 += struct.pack(f'{BIG}HHII', 0x8825, TYPE_LONG, 1, gps_ifd_offset)
        ifd0 += struct.pack(f'{BIG}I', 0)

        # Exif SubIFD: DateTimeOriginal → Pointer (20 bytes, zu groß für inline)
        exif_ifd  = struct.pack(f'{BIG}H', EXIF_IFD_ENTRIES)
        exif_ifd += struct.pack(f'{BIG}HHI', 0x9003, TYPE_ASCII, 20) + struct.pack(f'{BIG}I', off_dt)
        exif_ifd += struct.pack(f'{BIG}I', 0)

        # GPS IFD: LatRef/LonRef inline, Lat/Lon als Pointer
        gps_ifd  = struct.pack(f'{BIG}H', GPS_IFD_ENTRIES)
        gps_ifd += struct.pack(f'{BIG}HHI', 0x0001, TYPE_ASCII, 2)    + lat_ref_inline   # INLINE
        gps_ifd += struct.pack(f'{BIG}HHII', 0x0002, TYPE_RATIONAL, 3, off_lat)           # Pointer
        gps_ifd += struct.pack(f'{BIG}HHI', 0x0003, TYPE_ASCII, 2)    + lon_ref_inline   # INLINE
        gps_ifd += struct.pack(f'{BIG}HHII', 0x0004, TYPE_RATIONAL, 3, off_lon)           # Pointer
        gps_ifd += struct.pack(f'{BIG}I', 0)

        # Nur externe Wertedaten (Ref-Felder sind jetzt inline → nicht mehr hier)
        values       = dt_ascii + lat_rational + lon_rational
        tiff_header  = b'MM\x00\x2a' + struct.pack(f'{BIG}I', ifd0_offset)
        exif_payload = tiff_header + ifd0 + exif_ifd + gps_ifd + values
        app1_data    = b'Exif\x00\x00' + exif_payload
        app1_length  = len(app1_data) + 2
        app1_segment = b'\xff\xe1' + struct.pack('>H', app1_length) + app1_data

        rest = jpeg_data[2:]
        if rest[:2] == b'\xff\xe1':
            old_len = struct.unpack('>H', rest[2:4])[0]
            rest = rest[2 + old_len:]

        with open(jpg_path, 'wb') as f:
            f.write(b'\xff\xd8' + app1_segment + rest)

        if dt_str:
            if verbose: logger.info(f"     ✓ EXIF geschrieben: lat={lat:.6f}, lon={lon:.6f}, dt={dt_exif}")
        else:
            if verbose: logger.info(f"     ✓ EXIF GPS geschrieben: lat={lat:.6f}, lon={lon:.6f} (kein Datum)")
        return True

    except Exception as e:
        logger.warning(f"     ⚠ EXIF-Schreiben fehlgeschlagen: {e}")
        return False

def convert_tif_to_jpg_with_exif(
    tif_path: Path,
    output_dir: Path,
    quality: int = 85,
    dt_str_override: Optional[str] = None,
    gdalinfo_text: Optional[str] = None,
    jpg_stem_override: Optional[str] = None,
    verbose: bool = True,
) -> Optional[Path]:
    """
    Konvertiert ein georeferenziertes GeoTIFF (EBN/EBO) zu JPEG und schreibt
    GPS-EXIF aus den Center-Koordinaten des GeoTransform.

    NEU v2.2:
      - Rotation wird aus GeoTransform erkannt und korrigiert:
          * 180°-Flip (nord-unten): direkt via -a_ullr in gdal_translate (verlustfrei)
          * Beliebiger Winkel:      via gdalwarp nach gdal_translate (Solution B)
      - dt_str_override: optionaler Timestamp mit ms-Offset aus _assign_sequential_ms_offsets
        (Format "YYYY:MM:DD HH:MM:SS:NN"); EXIF erhält nur [:19], Item-Name den vollen String
      - gdalinfo_text: gecachter gdalinfo-Output (vermeidet doppelten Prozessaufruf)

    Workflow:
      1. gdalinfo  → Koordinaten + Datum + Rotationswinkel
      2. gdal_translate → JPEG  (inkl. -a_ullr für 180°-Flip)
      2b. gdalwarp → Nord-oben Normalisierung (nur bei anderen Winkeln)
      3. GPS-EXIF ins JPEG schreiben

    Returns:
        Path zum erzeugten JPEG oder None bei Fehler
    """
    if verbose: logger.info(f"  🔄 TIF→JPG Konvertierung: {tif_path.name}")

    # ------------------------------------------------------------------
    # SCHRITT 1: gdalinfo – Koordinaten + Datum + Rotation
    # ------------------------------------------------------------------
    if gdalinfo_text is None:
        try:
            result = subprocess.run(
                ['gdalinfo', str(tif_path)],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
            )
            if result.returncode != 0:
                logger.error(f"     ✗ gdalinfo fehlgeschlagen: {result.stderr[:200]}")
                return None
            gdalinfo_text = result.stdout
        except subprocess.TimeoutExpired:
            logger.error(f"     ✗ gdalinfo Timeout für {tif_path.name}")
            return None
        except Exception as e:
            logger.error(f"     ✗ gdalinfo Fehler: {e}")
            return None

    lat, lon = _parse_geotransform_center(gdalinfo_text)
    if lat is None or lon is None:
        logger.warning(f"     ⚠ Keine Center-Koordinaten gefunden – EXIF wird ohne GPS geschrieben")
    else:
        if verbose: logger.info(f"     ✓ Center: lat={lat:.6f}, lon={lon:.6f}")

    # Timestamp: Override (mit ms-Offset) hat Vorrang vor TIFFTAG_DATETIME
    dt_str = dt_str_override if dt_str_override else _parse_tifftag_datetime(gdalinfo_text)
    if dt_str:
        base_ts = dt_str[:19]
        ms_part = dt_str[20:] if len(dt_str) > 19 else None
        if verbose: logger.info(f"     ✓ Datum: {base_ts}" + (f"  (ms-offset=:{ms_part})" if ms_part else ""))
    else:
        logger.warning(f"     ⚠ Kein TIFFTAG_DATETIME gefunden")

    # Rotationswinkel bestimmen (NEU v2.2)
    rotation_deg = _geotransform_rotation_deg(gdalinfo_text)

    # ------------------------------------------------------------------
    # SCHRITT 2: gdal_translate → JPEG
    # Für reinen 180°-Flip: gdalwarp TIF→JPEG (reordnet Pixel physisch)
    # Für beliebige Rotation: gdalwarp TIF→JPEG mit -t_srs EPSG:4326
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)

    # JPEG-Stem: jpg_stem_override hat Vorrang (vom Caller vorberechnet)
    # Fallback: aus dt_str ableiten (bisheriges Verhalten für Standalone-Aufrufe)
    if jpg_stem_override:
        jpg_stem = jpg_stem_override
    elif dt_str and len(dt_str) > 19:
        time_part  = dt_str[11:19].replace(':', '')
        ms_part    = dt_str[20:]
        jpg_stem   = f"{tif_path.stem}_{time_part}_{ms_part}"
    else:
        jpg_stem   = tif_path.stem
    jpg_path = output_dir / (jpg_stem + '.jpg')

    ullr_args      = []
    needs_gdalwarp = False

    if rotation_deg is not None and abs(rotation_deg) > 0.01:
        if abs(rotation_deg - 180.0) < 0.5:
            # Reiner 180°-Flip: gdalwarp auf das TIF → physische Pixelreihenfolge umkehren
            # HINWEIS: -a_ullr in gdal_translate ändert nur die Georeferenz-Metadaten,
            # nicht die tatsächliche Pixelreihenfolge im JPEG-Output. Deshalb gdalwarp.
            needs_gdalwarp = True
            if verbose: logger.info(f"     ↕ Nord-unten erkannt → 180° Flip via gdalwarp (Pixel-Reordering)")
        else:
            # Beliebiger Winkel → gdalwarp mit Reprojektion
            needs_gdalwarp = True
            if verbose: logger.info(f"     ↻ Rotation {rotation_deg:.1f}° erkannt → gdalwarp Reprojektion")

    # Originale Pixelgrösse + geographisches Extent aus gdalinfo
    # (für dimensionstreues Flip via gdalwarp -te + -ts)
    _size_m = re.search(r'Size is (\d+), (\d+)', gdalinfo_text)
    orig_cols = int(_size_m.group(1)) if _size_m else None
    orig_rows = int(_size_m.group(2)) if _size_m else None

    # GeoTransform für -te Berechnung parsen.
    # Alle 6 Koeffizienten einlesen — bei gedrehten Bildern (z.B. 90°) sind
    # die Schrägstellungs-Terme (row_rot, col_rot) dominant und dürfen nicht
    # ignoriert werden. Alle 4 Ecken berechnen → min/max → korrekter Extent.
    _gt_m = re.search(
        r'GeoTransform\s*=\s*'
        r'([\-\d\.e\+]+),\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+)\s*\n'
        r'\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+),\s*([\-\d\.e\+]+)',
        gdalinfo_text
    )
    if _gt_m and orig_cols and orig_rows:
        _ox      = float(_gt_m.group(1))
        _pw      = float(_gt_m.group(2))
        _row_rot = float(_gt_m.group(3))
        _oy      = float(_gt_m.group(4))
        _col_rot = float(_gt_m.group(5))
        _ph      = float(_gt_m.group(6))
        # Alle 4 Ecken mit vollständiger Affin-Transformation berechnen
        _corners_x = [
            _ox + _pw * c + _row_rot * r
            for c, r in [(0, 0), (orig_cols, 0), (0, orig_rows), (orig_cols, orig_rows)]
        ]
        _corners_y = [
            _oy + _col_rot * c + _ph * r
            for c, r in [(0, 0), (orig_cols, 0), (0, orig_rows), (orig_cols, orig_rows)]
        ]
        te_args = ['-te',
                   str(min(_corners_x)), str(min(_corners_y)),
                   str(max(_corners_x)), str(max(_corners_y))]
    else:
        te_args = []

    if needs_gdalwarp:
        # gdalwarp TIF → JPEG mit -te (exakter geogr. Extent) + -ts (korrekte Pixelgrösse).
        # -ts wird aus dem Extent und der originalen Pixelgrösse (als Vektorbetrag) berechnet.
        # Das ist nötig weil bei gedrehten Bildern (z.B. 90°) Breite und Höhe tauschen.
        ts_args = []
        if te_args and _gt_m and orig_cols and orig_rows:
            import math as _math
            _px_size_x = _math.sqrt(float(_gt_m.group(2))**2 + float(_gt_m.group(3))**2)
            _px_size_y = _math.sqrt(float(_gt_m.group(5))**2 + float(_gt_m.group(6))**2)
            if _px_size_x > 0 and _px_size_y > 0:
                _ext_x = max(_corners_x) - min(_corners_x)
                _ext_y = max(_corners_y) - min(_corners_y)
                _out_cols = max(1, round(_ext_x / _px_size_x))
                _out_rows = max(1, round(_ext_y / _px_size_y))
                ts_args = ['-ts', str(_out_cols), str(_out_rows)]
                if verbose: logger.info(f"     → Output-Größe: {_out_cols}×{_out_rows}px (Extent÷Pixelgrösse)")
        try:
            warp_result = subprocess.run(
                [
                    'gdalwarp',
                    '-of', 'JPEG',
                    '-co', f'QUALITY={quality}',
                    '-r', 'bilinear',
                    '-t_srs', 'EPSG:4326',
                    '-ovr', 'NONE',    # Keine internen TIF-Overviews verwenden → immer volle Auflösung
                    *te_args,
                    *ts_args,
                    str(tif_path),
                    str(jpg_path)
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
            )

            if warp_result.returncode != 0:
                logger.warning(
                    f"     ⚠ gdalwarp fehlgeschlagen (rc={warp_result.returncode}), "
                    f"Fallback auf gdal_translate:\n{warp_result.stderr[:200]}"
                )
                needs_gdalwarp = False   # Fallback: translate ohne Rotation
            else:
                aux_file = jpg_path.with_suffix('.jpg.aux.xml')
                if aux_file.exists():
                    aux_file.unlink()
                if verbose: logger.info(f"     ✓ JPEG erstellt (nord-oben): {jpg_path.name} ({jpg_path.stat().st_size // 1024} KB)")

                # SCHRITT 3: GPS-EXIF ins JPEG schreiben und fertig
                if lat is not None and lon is not None:
                    _write_minimal_exif_gps(jpg_path, lat, lon, dt_str, verbose=verbose)
                else:
                    logger.warning(f"     ⚠ GPS-EXIF übersprungen (keine Koordinaten)")
                return jpg_path

        except subprocess.TimeoutExpired:
            logger.warning(f"     ⚠ gdalwarp Timeout → Fallback auf gdal_translate")
            needs_gdalwarp = False
        except Exception as e:
            logger.warning(f"     ⚠ gdalwarp Fehler: {e} → Fallback auf gdal_translate")
            needs_gdalwarp = False

    # ------------------------------------------------------------------
    # Fallback: gdal_translate ohne Rotation (nur wenn gdalwarp oben
    # fehlgeschlagen ist oder keine Rotation nötig war)
    # ------------------------------------------------------------------
    try:
        translate_result = subprocess.run(
            [
                'gdal_translate',
                '-of', 'JPEG',
                '-co', f'QUALITY={quality}',
                '-co', 'EXIF_THUMBNAIL=NO',
                str(tif_path),
                str(jpg_path)
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
        )

        if translate_result.returncode != 0:
            logger.error(f"     ✗ gdal_translate fehlgeschlagen:\n{translate_result.stderr[:300]}")
            return None

        aux_file = jpg_path.with_suffix('.jpg.aux.xml')
        if aux_file.exists():
            aux_file.unlink()

        if needs_gdalwarp:
            if verbose: logger.info(f"     ⚠ JPEG ohne Rotation erstellt (gdalwarp fehlgeschlagen): {jpg_path.name}")
        else:
            if verbose: logger.info(f"     ✓ JPEG erstellt: {jpg_path.name} ({jpg_path.stat().st_size // 1024} KB)")

    except subprocess.TimeoutExpired:
        logger.error(f"     ✗ gdal_translate Timeout")
        return None
    except Exception as e:
        logger.error(f"     ✗ gdal_translate Fehler: {e}")
        return None

    # ------------------------------------------------------------------
    # SCHRITT 3: GPS-EXIF ins JPEG schreiben
    # ------------------------------------------------------------------
    if lat is not None and lon is not None:
        _write_minimal_exif_gps(jpg_path, lat, lon, dt_str, verbose=verbose)
    else:
        logger.warning(f"     ⚠ GPS-EXIF übersprungen (keine Koordinaten)")

    return jpg_path


# ==============================================================================
# NEU v2.2 — FIX 3: PRO-TIMESTAMP EIN REPRÄSENTATIVES BILD → SOFORT KONVERTIEREN
# ==============================================================================

def convert_tif_files_in_directory(
    input_dir: Path,
    output_dir: Path,
    quality: int = 85
) -> List[Path]:
    """
    Scannt alle TIF-Dateien in input_dir, wählt pro einzigartigem Timestamp
    genau ein repräsentatives Bild aus und konvertiert dieses sofort zu JPEG.

    NEU v2.2 — drei Phasen:

    Phase 1 — gdalinfo für alle TIFs (gecacht, einmalig):
      Alle Metadaten werden vorab abgerufen, um mehrfache Prozessaufrufe
      pro Datei zu vermeiden.

    Phase 2 — ms-Offsets zuweisen (_assign_sequential_ms_offsets):
      Dateien mit identischem TIFFTAG_DATETIME werden nach den letzten zwei
      Stem-Ziffern sortiert und erhalten sequentielle Offsets :01, :02, ...

    Phase 3 — Auswahl + Sofort-Konvertierung:
      Pro Timestamp-Gruppe wird nur die erste Datei (Offset :01 bzw. kein
      Offset bei eindeutigem Timestamp) konvertiert. Weitere Burst-Frames
      (:02, :03, ...) werden übersprungen.
      Konvertierung erfolgt sofort nach Auswahl, nicht gebatcht.

    Vorteile:
      - Keine redundanten Konvertierungen von Burst-Duplikaten
      - Keine stillen STAC-Item-Überschreibungen durch Timestamp-Kollisionen
      - Weniger temporärer Speicherbedarf

    Args:
        input_dir:  Quellverzeichnis mit TIF-Dateien
        output_dir: Zielverzeichnis für JPEGs
        quality:    JPEG-Qualität (Standard: 85)

    Returns:
        Liste der erzeugten JPEG-Dateien (eine pro einzigartigem Timestamp)
    """
    tif_files = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {'.tif', '.tiff'}
    )

    if not tif_files:
        return []

    logger.info(f"  Gefunden: {len(tif_files)} TIF-Datei(en) → Analysiere Timestamps...")

    # ------------------------------------------------------------------
    # PHASE 1: gdalinfo für alle Dateien (gecacht)
    # ------------------------------------------------------------------
    gdalinfo_cache: Dict[Path, str] = {}
    for tif in tif_files:
        try:
            result = subprocess.run(
                ['gdalinfo', str(tif)],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
            )
            gdalinfo_cache[tif] = result.stdout if result.returncode == 0 else ''
            if result.returncode != 0:
                logger.warning(f"  ⚠ gdalinfo fehlgeschlagen für {tif.name}")
        except Exception as e:
            logger.warning(f"  ⚠ gdalinfo Fehler für {tif.name}: {e}")
            gdalinfo_cache[tif] = ''

    # ------------------------------------------------------------------
    # PHASE 2: Sequentielle ms-Offsets zuweisen
    # ------------------------------------------------------------------
    ts_with_offset = _assign_sequential_ms_offsets(tif_files, gdalinfo_cache)

    # Statistik
    burst_groups = sum(1 for g in
                       __import__('collections').Counter(
                           ts_with_offset[t] for t in tif_files
                       ).values() if g > 1)
    logger.info(f"  Alle {len(tif_files)} Frame(s) werden konvertiert und hochgeladen")

    # ------------------------------------------------------------------
    # PHASE 3: Alle Frames konvertieren (jeder mit eigenem ms-Offset)
    # Burst-Frames werden NICHT übersprungen — alle erhalten eindeutige
    # Timestamps (:01, :02, ...) und werden einzeln hochgeladen.
    # ------------------------------------------------------------------
    jpg_files = []
    converted = 0

    for tif in tif_files:
        effective_ts = ts_with_offset.get(tif, '')
        ms_match = re.search(r'^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}:(\d{2})$', effective_ts)
        offset_str = ms_match.group(1) if ms_match else "??"
        logger.info(f"  🔄 Frame :{offset_str} → {tif.name}")

        jpg = convert_tif_to_jpg_with_exif(
            tif_path=tif,
            output_dir=output_dir,
            quality=quality,
            dt_str_override=effective_ts if effective_ts else None,
            gdalinfo_text=gdalinfo_cache.get(tif),
        )
        if jpg:
            jpg_files.append(jpg)
            converted += 1
        else:
            logger.warning(f"  ⚠ Konvertierung fehlgeschlagen, überspringe: {tif.name}")

    logger.info(f"  ✓ Konvertierung abgeschlossen: {converted}/{len(tif_files)} erfolgreich")
    return jpg_files


# ==============================================================================
# BESTEHENDE FUNKTIONEN (unverändert)
# ==============================================================================

def generate_csv_from_stac(
    stac_url: str,
    collection: str,
    date: str,
    product_suffix: str,
    output_file: Path,
) -> bool:
    """
    Erstellt eine CSV-Datei mit den effektiv im STAC publizierten Foto-URLs.

    Im Gegensatz zur früheren Variante (lokale photos-Liste) fragt diese
    Funktion direkt die STAC-API ab — der CSV-Inhalt ist damit garantiert
    synchron mit dem publizierten Datenstand.

    Keine Thumbnails, keine KML-Overviews, nur Hauptassets (.jpg/.jpeg).
    URLs werden alphabetisch sortiert ausgegeben (= chronologisch, da der
    Item-Name den Zeitstempel enthält).

    Args:
        stac_url (str):        Vollständige STAC-API-URL
        collection (str):      STAC Collection Name
        date (str):            Datum im Format YYYY-MM-DD
        product_suffix (str):  Produkt-Suffix z.B. "ebn", "ebo"
        output_file (Path):    Pfad zur Ausgabe-Datei

    Returns:
        bool: True wenn erfolgreich (auch wenn 0 URLs gefunden), False bei I/O-Fehler
    """
    from utilities.kml_generator import get_published_photo_urls

    logger.info(f"\n→ Generiere CSV aus STAC-Daten: {output_file.name}")

    urls = get_published_photo_urls(
        stac_url=stac_url,
        collection=collection,
        date=date,
        product_suffix=product_suffix
    )

    if not urls:
        logger.warning("  ⚠ Keine publizierten URLs gefunden – leere CSV wird erstellt")

    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            for url in urls:
                f.write(f"{url}\n")

        logger.info(f"  ✓ CSV erstellt: {output_file} ({len(urls)} URLs)")
        return True

    except Exception as e:
        logger.error(f"  ✗ CSV-Erstellung fehlgeschlagen: {e}")
        return False


def parse_exif_timestamp(exif_timestamp: Optional[str], photo_name: str) -> str:
    """
    Parsed EXIF-Timestamp zu Item-Timestamp-String.

    NEU v2.2: Unterstützt das erweiterte Format mit ms-Offset:
      "2025:07:10 08:00:28:01"  →  "2025-07-10t08002801"
                                              ^^^^^^^^^ Sekunden + 2-stelliger Offset

    Das ms-Offset-Suffix (:NN) wird direkt ans Ende des formatierten
    Timestamps angehängt, sodass generate_item_name() einen eindeutigen
    Item-Namen erzeugt.

    Fallback auf Dateinamen oder aktuelles Datum wenn EXIF fehlt.
    """
    # Alle Produkte (EBN/EBO/QDOP) erhalten immer ein 2-stelliges ms-Suffix.
    # Kein Burst-Offset bekannt → "00". Burst-Frame → "01".."99".
    ms_suffix = "00"
    base_ts_str = None

    if exif_timestamp:
        try:
            ext_match = re.match(
                r'(\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}):(\d{2})$',
                exif_timestamp
            )
            if ext_match:
                base_ts_str = ext_match.group(1)
                ms_suffix   = ext_match.group(2)
            else:
                base_ts_str = exif_timestamp
            dt = datetime.strptime(base_ts_str, "%Y:%m:%d %H:%M:%S")
            return dt.strftime("%Y-%m-%dt%H%M%S").lower() + ms_suffix
        except (ValueError, TypeError) as e:
            logger.warning(f"  ⚠ EXIF-Timestamp ungültig: {exif_timestamp}, Fehler: {e}")

    try:
        match = re.search(r'(\d{8})_(\d{6})', photo_name)
        if match:
            dt = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
            logger.info(f"  ℹ Timestamp aus Dateinamen: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
            return dt.strftime("%Y-%m-%dt%H%M%S").lower() + ms_suffix

        match = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{6})', photo_name)
        if match:
            date_str = match.group(1).replace('-', '')
            dt = datetime.strptime(date_str + match.group(2), "%Y%m%d%H%M%S")
            logger.info(f"  ℹ Timestamp aus Dateinamen: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
            return dt.strftime("%Y-%m-%dt%H%M%S").lower() + ms_suffix

    except Exception as e:
        logger.debug(f"  Konnte Timestamp nicht aus Dateinamen extrahieren: {e}")

    logger.warning(f"  ⚠ Kein Timestamp gefunden - verwende aktuelles Datum")
    return datetime.now().strftime("%Y-%m-%dt%H%M%S").lower() + ms_suffix


def dms_to_decimal(degrees: float, minutes: float, seconds: float, direction: str) -> float:
    decimal = degrees + minutes / 60 + seconds / 3600
    if direction in ['S', 'W']:
        decimal *= -1
    return round(decimal, 6)


def extract_exif_data(file_path: Path) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Extrahiert EXIF-Daten aus JPEG-Datei mittels gdalinfo subprocess.
    """
    try:
        try:
            with open(os.devnull, 'w') as devnull:
                result = subprocess.run(
                    ['gdalinfo', '-json', str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
                )

            if result.returncode == 0:
                exif_data = json.loads(result.stdout)
                lat, lon, timestamp = None, None, None

                if 'metadata' in exif_data and '' in exif_data['metadata']:
                    exif = exif_data['metadata']['']

                    if 'EXIF_GPSLatitude' in exif and 'EXIF_GPSLongitude' in exif:
                        lat_parts = exif['EXIF_GPSLatitude']
                        lon_parts = exif['EXIF_GPSLongitude']
                        lat_ref = exif.get('EXIF_GPSLatitudeRef', 'N')
                        lon_ref = exif.get('EXIF_GPSLongitudeRef', 'E')

                        try:
                            lat_vals = [float(x.replace(')', '')) for x in lat_parts.strip('()').split(') (')]
                            lon_vals = [float(x.replace(')', '')) for x in lon_parts.strip('()').split(') (')]
                            lat = dms_to_decimal(lat_vals[0], lat_vals[1], lat_vals[2], lat_ref)
                            lon = dms_to_decimal(lon_vals[0], lon_vals[1], lon_vals[2], lon_ref)
                        except (ValueError, IndexError):
                            lat, lon = None, None

                    if 'EXIF_DateTimeOriginal' in exif:
                        timestamp = exif['EXIF_DateTimeOriginal']

                if lat or lon or timestamp:
                    return lat, lon, timestamp

        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            pass

        logger.debug(f"  Fallback zu Text-Parsing für {file_path.name}")
        result = subprocess.run(
            ['gdalinfo', str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
        )

        if result.returncode != 0:
            return None, None, None

        return parse_gdalinfo_text(result.stdout)

    except subprocess.TimeoutExpired:
        logger.warning(f"  ⚠ Timeout beim EXIF-Lesen von {file_path.name}")
        return None, None, None
    except Exception as e:
        logger.warning(f"  ⚠ Fehler beim EXIF-Lesen von {file_path.name}: {e}")
        return None, None, None


def parse_gdalinfo_text(output: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    lat, lon, timestamp = None, None, None
    lines = output.split('\n')
    lat_vals = None
    lon_vals = None
    lat_ref = 'N'
    lon_ref = 'E'

    for line in lines:
        line = line.strip()

        if 'EXIF_GPSLatitude=' in line and 'Ref' not in line:
            try:
                parts = line.split('=', 1)[1]
                lat_vals = [float(x.strip('()')) for x in parts.split(') (')]
            except (ValueError, IndexError):
                pass

        if 'EXIF_GPSLatitudeRef=' in line:
            lat_ref = line.split('=', 1)[1].strip()

        if 'EXIF_GPSLongitude=' in line and 'Ref' not in line:
            try:
                parts = line.split('=', 1)[1]
                lon_vals = [float(x.strip('()')) for x in parts.split(') (')]
            except (ValueError, IndexError):
                pass

        if 'EXIF_GPSLongitudeRef=' in line:
            lon_ref = line.split('=', 1)[1].strip()

        if 'EXIF_DateTimeOriginal=' in line:
            timestamp = line.split('=', 1)[1].strip()

    if lat_vals and len(lat_vals) >= 3:
        lat = dms_to_decimal(lat_vals[0], lat_vals[1], lat_vals[2], lat_ref)

    if lon_vals and len(lon_vals) >= 3:
        lon = dms_to_decimal(lon_vals[0], lon_vals[1], lon_vals[2], lon_ref)

    return lat, lon, timestamp


def resize_image_gdal(
    input_file: Path,
    output_file: Path,
    max_width: int = THUMBNAIL_CONFIG['max_width'],
    max_height: int = THUMBNAIL_CONFIG['max_height']
) -> bool:
    try:
        with open(os.devnull, 'w') as devnull:
            gdalinfo_result = subprocess.run(
                ['gdalinfo', '-json', str(input_file)],
                capture_output=True,
                text=True,
                timeout=10
            )

        if gdalinfo_result.returncode != 0:
            return False

        image_info = json.loads(gdalinfo_result.stdout)
        width = int(image_info['size'][0])
        height = int(image_info['size'][1])

        aspect_ratio = width / height
        if aspect_ratio > 1:
            new_width = min(max_width, width)
            new_height = int(new_width / aspect_ratio)
        else:
            new_height = min(max_height, height)
            new_width = int(new_height * aspect_ratio)

        new_width = min(new_width, max_width)
        new_height = min(new_height, max_height)

        with open(os.devnull, 'w') as devnull:
            translate_result = subprocess.run(
                [
                    'gdal_translate',
                    '-of', 'JPEG',
                    '-outsize', str(new_width), str(new_height),
                    str(input_file),
                    str(output_file)
                ],
                stdout=devnull,
                stderr=devnull,
                timeout=30,
                env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
            )

        return translate_result.returncode == 0

    except Exception as e:
        logger.warning(f"  ⚠ Fehler beim Thumbnail-Erstellen: {e}")
        return False


def process_single_photo(
    photo_file: Path,
    output_dir: Path,
    product_type: ProductType,
    timestamp: str
) -> Optional[Dict]:
    try:
        lat, lon, exif_timestamp = extract_exif_data(photo_file)

        thumbs_dir = output_dir / "thumbs"
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = thumbs_dir / photo_file.name

        thumbnail_success = resize_image_gdal(
            photo_file,
            thumbnail_path,
            max_width=THUMBNAIL_CONFIG['max_width'],
            max_height=THUMBNAIL_CONFIG['max_height']
        )

        if not thumbnail_success:
            logger.warning(f"  ⚠ Thumbnail-Erstellung fehlgeschlagen: {photo_file.name}")
            thumbnail_path = None

        item_name = generate_item_name(timestamp, product_type)

        return {
            'original_path': photo_file,
            'thumbnail_path': thumbnail_path,
            'item_name': item_name,
            'original_filename': photo_file.name,
            'lat': lat,
            'lon': lon,
            'timestamp': exif_timestamp
        }

    except Exception as e:
        logger.error(f"  ✗ Fehler bei Photo-Verarbeitung: {e}")
        return None


def process_individual_photos(
    input_dir: Path,
    output_dir: Path,
    product_config: Dict,
    product_type: ProductType,
    stac_collection: str,
    geocat_id: str,
    hostname: str,
    environment: str,
    upload_enabled: bool = True,
    debug: bool = False,
) -> Optional[Dict]:
    """
    Verarbeitet alle Photos in einem Verzeichnis.

    Args:
        debug: True → sequentielle Verarbeitung mit vollem Logging (für Debugging).
               False → parallele Konvertierung + Upload (Produktion, Standard).

    NEU v2.3: Parallele Verarbeitung via ThreadPoolExecutor wenn debug=False.
    """
    try:
        temp_dir = output_dir / "temp_photos"

        # Überreste früherer Läufe entfernen — verhindert WinError 183
        # (Datei existiert bereits) und 409-Fehler durch verwaiste Worker-Dirs.
        if temp_dir.exists():
            logger.info(f"  Bereinige temp-Verzeichnis: {temp_dir}")
            import shutil as _shutil
            _shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        if upload_enabled:
            from utilities.stac_publisher import publish_to_stac_wrapper

        # ====================================================================
        # PHASE 1: Arbeitsliste aufbauen
        # TIF-Modus: Dateiauswahl + gdalinfo parallel
        # JPEG-Modus: Dateien direkt aus input_dir
        # ====================================================================
        is_tif_mode = False
        work_items: List[Dict] = []

        if product_type in [ProductType.EBN, ProductType.EBO]:
            logger.info("  Lese Verzeichnis...")
            tif_files_raw = []
            for i, p in enumerate(input_dir.iterdir(), 1):
                if p.suffix.lower() in {'.tif', '.tiff'} and p.is_file():
                    tif_files_raw.append(p)
                if i % 500 == 0:
                    logger.info(f"  Verzeichnis: {i} Einträge gelesen, {len(tif_files_raw)} TIFs...")
            tif_files = sorted(tif_files_raw)
            logger.info(f"  ✓ Verzeichnis gelesen: {len(tif_files)} TIF-Dateien gefunden")

            if tif_files:
                is_tif_mode = True
                logger.info("=" * 70)
                logger.info(f"TIF-MODUS: {len(tif_files)} Datei(en) — Scan, dann einzeln konvertieren")
                logger.info("=" * 70)

                # ----------------------------------------------------------------
                # Schneller Scan: direktes TIFF-Header-Parsing (kein subprocess).
                # Liest nur 64KB pro Datei → auf Netzwerklaufwerken ~2-10ms/Datei
                # statt 500-2000ms für gdalinfo. Für 2391 Dateien: ~12s statt 8min.
                # gdalinfo wird nur als Fallback für unlesbare Dateien aufgerufen.
                # ----------------------------------------------------------------
                from concurrent.futures import ThreadPoolExecutor, as_completed
                import multiprocessing, time as _time

                logger.info(f"  Scanne {len(tif_files)} Dateien (schneller Header-Parser)...")
                t_scan_start = _time.time()

                gdalinfo_cache: Dict[Path, str] = {}
                fallback_needed: List[Path] = []
                total        = len(tif_files)
                log_interval = max(1, min(100, total // 20))

                # Schneller Pfad: paralleles TIFF-Header-Parsing
                n_workers = min(32, max(4, (multiprocessing.cpu_count() or 4) * 4))

                def _scan_fast(tif: Path) -> tuple:
                    text = _fast_tiff_to_gdalinfo_text(tif)
                    return tif, text

                completed = 0
                with ThreadPoolExecutor(max_workers=n_workers) as executor:
                    futures = {executor.submit(_scan_fast, tif): tif for tif in tif_files}
                    logger.info(f"  {total} Aufträge gestartet...")
                    for future in as_completed(futures):
                        tif, text = future.result()
                        if text:
                            gdalinfo_cache[tif] = text
                        else:
                            fallback_needed.append(tif)
                        completed += 1
                        if completed % log_interval == 0 or completed == total:
                            elapsed = _time.time() - t_scan_start
                            rate    = completed / elapsed if elapsed > 0 else 0
                            eta     = (total - completed) / rate if rate > 0 else 0
                            logger.info(
                                f"  Scan: {completed}/{total}"
                                f"  ({rate:.0f}/s, ETA {eta:.0f}s)"
                            )

                # Fallback: gdalinfo für Dateien die nicht geparst werden konnten
                if fallback_needed:
                    logger.info(f"  gdalinfo-Fallback für {len(fallback_needed)} Dateien...")
                    scan_env = {**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
                    for tif in fallback_needed:
                        try:
                            r = subprocess.run(
                                ['gdalinfo', str(tif)],
                                capture_output=True, text=True, timeout=60,
                                env=scan_env
                            )
                            gdalinfo_cache[tif] = r.stdout if r.returncode == 0 else ''
                        except Exception:
                            gdalinfo_cache[tif] = ''

                elapsed_total = _time.time() - t_scan_start
                logger.info(
                    f"  ✓ Scan abgeschlossen: {total} Dateien in {elapsed_total:.1f}s"
                    f"  ({len(fallback_needed)} via gdalinfo-Fallback)"
                )

                # ms-Offsets für alle Dateien (stabile Nummerierung)
                ts_with_offset = _assign_sequential_ms_offsets(tif_files, gdalinfo_cache)

                # ----------------------------------------------------------------
                # Greedy Polygon Set Cover — exakte Footprints, keine AABB
                # ----------------------------------------------------------------
                logger.info("  Berechne minimale Dateiauswahl (Greedy Polygon Set Cover, 99%)...")
                selected_tifs, _ = select_minimal_coverage_files(
                    tif_files=tif_files,
                    gdalinfo_cache=gdalinfo_cache,
                    coverage_threshold=0.99,
                )
                selected_set = set(selected_tifs)
                tif_files_to_process = [t for t in tif_files if t in selected_set]
                dropped = [t for t in tif_files if t not in selected_set]
                if dropped:
                    logger.info(f"  Übersprungen: {len(dropped)} Dateien (vollständig durch andere abgedeckt)")

                # Arbeitsliste aufbauen (noch keine Konvertierung)
                for tif in tif_files_to_process:
                    effective_ts = ts_with_offset.get(tif, '')
                    # JPEG-Stem mit ms-Offset kodieren
                    if effective_ts and len(effective_ts) > 19:
                        time_part = effective_ts[11:19].replace(':', '')
                        ms_part   = effective_ts[20:]
                    else:
                        time_part = effective_ts[11:19].replace(':', '') if len(effective_ts) >= 19 else '000000'
                        ms_part   = '00'
                    jpg_stem = f"{tif.stem}_{time_part}_{ms_part}"

                    # Item-Namen direkt aus effective_ts berechnen (nicht aus EXIF)
                    base_ts = effective_ts[:19] if effective_ts else None
                    if base_ts:
                        try:
                            dt = datetime.strptime(base_ts, "%Y:%m:%d %H:%M:%S")
                            timestamp = dt.strftime("%Y-%m-%dt%H%M%S").lower() + ms_part
                        except ValueError:
                            timestamp = datetime.now().strftime("%Y-%m-%dt%H%M%S").lower() + ms_part
                    else:
                        timestamp = datetime.now().strftime("%Y-%m-%dt%H%M%S").lower() + ms_part

                    work_items.append({
                        'source_path':   tif,
                        'is_tif':        True,
                        'jpg_stem':      jpg_stem,
                        'effective_ts':  effective_ts,
                        'item_name':     generate_item_name(timestamp, product_type),
                        'gdalinfo_text': gdalinfo_cache.get(tif, ''),
                    })

                logger.info(f"  Plan: {len(work_items)} Datei(en)")
                for w in work_items:
                    logger.info(f"    {w['source_path'].name}  →  {w['jpg_stem']}.jpg  →  {w['item_name']}")

        if not is_tif_mode:
            # Standard-JPEG-Modus
            for jpg in get_jpg_files(input_dir, recursive=False):
                work_items.append({
                    'source_path': jpg,
                    'is_tif':      False,
                    'jpg_stem':    jpg.stem,
                    'item_name':   None,  # wird aus EXIF berechnet
                })

        total = len(work_items)
        logger.info(f"  Temp-Verzeichnis: {temp_dir}")

        # ====================================================================
        # PHASE 2: Verarbeitung + Upload
        # debug=True  → sequentiell, volles Logging (Debugging)
        # debug=False → parallel, ThreadPoolExecutor (Produktion)
        # ====================================================================

        # Per-Item-Lock: verhindert 409-Kollision wenn zwei Worker dasselbe
        # item_name gleichzeitig hochladen (z.B. bei identischen Timestamps).
        import threading as _threading
        _upload_locks: dict = {}
        _locks_mutex  = _threading.Lock()

        def _get_item_lock(name: str) -> _threading.Lock:
            with _locks_mutex:
                if name not in _upload_locks:
                    _upload_locks[name] = _threading.Lock()
                return _upload_locks[name]

        # Per-Datei-Verarbeitungsfunktion (wird sequentiell oder parallel aufgerufen)
        def _process_one(work: Dict, idx: int, total: int) -> Dict:
            """Konvertiert, erstellt Thumbnail und lädt eine Datei hoch."""
            source_path = work['source_path']
            log_prefix  = f"[{idx}/{total}] {source_path.name}"

            if debug:
                logger.info(f"\n{log_prefix}")
                logger.info("-" * 70)

            try:
                # Worker-Verzeichnis sofort anlegen — alle Dateien dieses Workers
                # landen hier, vollständig isoliert von anderen Workers.
                # (asset_name = item_name, bekannt für TIF-Modus aus work_items)
                _worker_asset = work.get('item_name') or work['jpg_stem']
                worker_dir = temp_dir / f"_worker_{_worker_asset}"
                worker_dir.mkdir(exist_ok=True)

                if work['is_tif']:
                    if debug: logger.info("  1️⃣  Konvertiere TIF → JPEG...")
                    jpg_result = convert_tif_to_jpg_with_exif(
                        tif_path=source_path,
                        output_dir=worker_dir,
                        quality=85,
                        dt_str_override=work['effective_ts'] or None,
                        gdalinfo_text=work['gdalinfo_text'] or None,
                        jpg_stem_override=work['jpg_stem'],
                        verbose=debug,
                    )
                    if jpg_result is None:
                        logger.error(f"{log_prefix}: ✗ Konvertierung fehlgeschlagen")
                        return {'source_path': source_path, 'error': 'conversion failed',
                                'photo_upload_success': False, 'thumbnail_upload_success': False,
                                'lat': None, 'lon': None}

                    jpg_file   = jpg_result
                    item_name  = work['item_name']
                    asset_name = item_name
                    lat, lon, exif_timestamp = extract_exif_data(jpg_file)
                    if debug:
                        if lat: logger.info(f"     ✓ GPS: {lat:.6f}, {lon:.6f}")
                        else:   logger.warning("     ⚠ Keine GPS-Daten")

                else:
                    if debug: logger.info("  1️⃣  Extrahiere EXIF-Daten (gdalinfo)...")
                    jpg_file = source_path
                    lat, lon, exif_timestamp = extract_exif_data(jpg_file)
                    if debug:
                        if lat: logger.info(f"     ✓ GPS: {lat:.6f}, {lon:.6f}")
                        else:   logger.warning("     ⚠ Keine GPS-Daten")
                    timestamp  = parse_exif_timestamp(exif_timestamp, jpg_file.name)
                    item_name  = generate_item_name(timestamp, product_type)
                    asset_name = item_name

                if debug: logger.info(f"  2️⃣  Item-Name: {item_name}")

                # Photo in worker_dir ablegen
                temp_photo_path = worker_dir / (asset_name + '.jpg')
                if work['is_tif']:
                    if jpg_file != temp_photo_path:
                        jpg_file.replace(temp_photo_path)  # replace() works even if dst exists (Windows-safe)
                        jpg_file = temp_photo_path
                else:
                    shutil.copy2(jpg_file, temp_photo_path)
                if debug: logger.info(f"     ✓ Foto: {temp_photo_path.name}")

                # Thumbnail in worker_dir (Dateiname thumbnail.jpg bleibt fix
                # damit get_published_photo_urls es korrekt herausfiltern kann)
                temp_thumbnail_path = worker_dir / "thumbnail.jpg"
                if debug: logger.info("  4️⃣  Erstelle Thumbnail...")
                thumbnail_success = resize_image_gdal(
                    temp_photo_path, temp_thumbnail_path,
                    max_width=THUMBNAIL_CONFIG['max_width'],
                    max_height=THUMBNAIL_CONFIG['max_height']
                )
                if not thumbnail_success:
                    if debug: logger.warning("     ⚠ Thumbnail fehlgeschlagen")
                    temp_thumbnail_path = None
                elif debug:
                    logger.info(f"     ✓ Thumbnail: {temp_thumbnail_path.stat().st_size} bytes")

                # Upload
                photo_upload_success     = False
                thumbnail_upload_success = False

                if upload_enabled:
                    # Lock pro item_name: verhindert 409-Kollision wenn zwei Worker
                    # denselben item_name gleichzeitig hochladen würden.
                    _item_lock = _get_item_lock(item_name)
                    with _item_lock:
                        if debug: logger.info("  5️⃣  Lade Foto zu STAC hoch...")
                        photo_upload_success = publish_to_stac_wrapper(
                            asset_path=temp_photo_path,
                            item_name=item_name,
                            collection=stac_collection,
                            geocat_id=geocat_id,
                            hostname=hostname,
                            asset_title=product_config['asset_title'],
                            environment=environment
                        )
                        if debug:
                            if photo_upload_success: logger.info("     ✓ Foto hochgeladen")
                            else: logger.error("     ✗ Foto-Upload fehlgeschlagen")

                        if photo_upload_success and temp_thumbnail_path and temp_thumbnail_path.exists():
                            if debug: logger.info("  6️⃣  Lade Thumbnail zu STAC hoch...")
                            thumbnail_upload_success = publish_to_stac_wrapper(
                                asset_path=temp_thumbnail_path,
                                item_name=item_name,
                                collection=stac_collection,
                                geocat_id=geocat_id,
                                hostname=hostname,
                                asset_title="THUMBNAIL",
                                environment=environment
                            )
                            if debug:
                                if thumbnail_upload_success: logger.info("     ✓ Thumbnail hochgeladen")
                                else: logger.warning("     ⚠ Thumbnail-Upload fehlgeschlagen")

                    if photo_upload_success:
                        temp_photo_path.unlink(missing_ok=True)
                        if temp_thumbnail_path and temp_thumbnail_path.exists():
                            temp_thumbnail_path.unlink(missing_ok=True)
                        try:
                            worker_dir.rmdir()
                        except Exception:
                            pass
                else:
                    if debug: logger.info("  ℹ️  Upload deaktiviert")

                if photo_upload_success and thumbnail_upload_success:
                    status = "✅ OK"
                elif photo_upload_success:
                    status = "⚠️  OK (Thumbnail fehlgeschlagen)"
                else:
                    status = "❌ UPLOAD FEHLGESCHLAGEN"

                if not debug:
                    # Im Produktionsmodus: kompakte Zeile — Fehler immer, Erfolg immer
                    if photo_upload_success:
                        logger.info(f"{log_prefix}: {status}")
                    else:
                        logger.error(f"{log_prefix}: {status}")
                elif upload_enabled:
                    logger.info("-" * 70)
                    if photo_upload_success and thumbnail_upload_success:
                        logger.info(f"✅ [{idx}/{total}] VOLLSTÄNDIG ERFOLGREICH")
                    elif photo_upload_success:
                        logger.info(f"⚠️  [{idx}/{total}] TEILWEISE ERFOLGREICH (nur Foto)")
                    else:
                        logger.error(f"❌ [{idx}/{total}] UPLOAD FEHLGESCHLAGEN")
                else:
                    logger.info(f"✅ [{idx}/{total}] VERARBEITUNG ERFOLGREICH (kein Upload)")

                return {
                    'source_path': source_path,
                    'temp_photo_path': temp_photo_path,
                    'temp_thumbnail_path': temp_thumbnail_path if thumbnail_success else None,
                    'item_name': item_name,
                    'asset_name': asset_name,
                    'original_filename': source_path.name,
                    'lat': lat,
                    'lon': lon,
                    'timestamp': exif_timestamp,
                    'photo_upload_success': photo_upload_success,
                    'thumbnail_upload_success': thumbnail_upload_success,
                }

            except Exception as e:
                logger.error(f"\n❌ FEHLER bei {source_path.name}: {e}")
                import traceback as _tb
                logger.error(_tb.format_exc() if debug else str(e))
                return {
                    'source_path': source_path,
                    'original_filename': source_path.name,
                    'error': str(e),
                    'photo_upload_success': False,
                    'thumbnail_upload_success': False,
                    'lat': None, 'lon': None,
                }

        # --- Ausführung: sequentiell (debug) oder parallel ---
        logger.info("\n" + "=" * 70)
        if debug:
            logger.info("VERARBEITE PHOTOS — DEBUG-MODUS (sequentiell)")
        else:
            n_proc = min(8, max(2, total))
            logger.info(f"VERARBEITE PHOTOS — PARALLEL ({n_proc} Workers)")
        logger.info("=" * 70)

        # Im Produktionsmodus: noisy Unter-Module auf WARNING setzen.
        # print()-Ausgaben von util_publish_stac_fsdi werden via _QuietStdout
        # unterdrückt (nur ERROR-Level-Meldungen werden durchgelassen).
        _noisy_modules = [
            'utilities.stac_publisher',
            'utilities.credentials',
            'utilities.proxy_handler',
            'main_multipart_upload_via_api',
            'util_publish_stac_fsdi',
        ]
        _saved_levels = {}
        if not debug:
            import logging as _logging
            for _mod in _noisy_modules:
                _lg = _logging.getLogger(_mod)
                _saved_levels[_mod] = _lg.level
                _lg.setLevel(_logging.WARNING)

        import io, sys as _sys

        class _QuietStdout(io.TextIOBase):
            """Filtert stdout: lässt nur Zeilen durch die Fehler-Keywords enthalten."""
            _ERROR_KW = ('error', 'fehler', '✗', 'failed', 'exception',
                         'traceback', 'critical', '❌')
            def __init__(self, orig): self._orig = orig
            def write(self, s):
                if not s or not s.strip(): return len(s)
                sl = s.lower()
                if any(kw in sl for kw in self._ERROR_KW):
                    return self._orig.write(s)
                return len(s)  # silently drop
            def flush(self): self._orig.flush()

        _orig_stdout = _sys.stdout
        if not debug:
            _sys.stdout = _QuietStdout(_orig_stdout)

        photos = []
        successful_uploads = 0
        missing_gps = 0

        if debug:
            # Sequentiell — jede Datei einzeln mit vollem Logging
            for idx, work in enumerate(work_items, 1):
                result = _process_one(work, idx, total)
                photos.append(result)
                if result.get('photo_upload_success'): successful_uploads += 1
                if result.get('lat') is None:          missing_gps += 1

        else:
            # Parallel — mehrere Dateien gleichzeitig konvertieren + hochladen
            from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed
            import multiprocessing as _mp, time as _time
            n_proc = min(8, max(2, _mp.cpu_count() or 2))

            # Proxy VOR dem Start der Worker initialisieren, damit alle Worker
            # die bereits fertige Konfiguration vorfinden und nicht 8×
            # gleichzeitig Proxy-Tests ausführen (→ 409-Kollisionen).
            try:
                from utilities.proxy_handler import initialize_proxy as _init_proxy
                _init_proxy()
            except Exception:
                pass

            with ThreadPoolExecutor(max_workers=n_proc) as executor:
                future_to_idx = {}
                for idx, work in enumerate(work_items, 1):
                    future_to_idx[executor.submit(_process_one, work, idx, total)] = idx
                    # Kleiner Versatz zwischen den ersten Starts damit Worker 1
                    # die Proxy-Session aufbaut bevor Worker 2 beginnt.
                    if idx <= n_proc:
                        _time.sleep(0.3)
                done = 0
                for future in _as_completed(future_to_idx):
                    result = future.result()
                    photos.append(result)
                    if result.get('photo_upload_success'): successful_uploads += 1
                    if result.get('lat') is None:          missing_gps += 1
                    done += 1
                    if done % max(1, total // 10) == 0 or done == total:
                        logger.info(f"  Fortschritt: {done}/{total} "
                                    f"({successful_uploads} erfolgreich hochgeladen)")

        # Logging-Level und stdout wiederherstellen
        if not debug:
            _sys.stdout = _orig_stdout
        if not debug and _saved_levels:
            import logging as _logging
            for _mod, _lvl in _saved_levels.items():
                _logging.getLogger(_mod).setLevel(_lvl if _lvl != 0 else _logging.NOTSET)

        # ====================================================================
        # ZUSAMMENFASSUNG
        # ====================================================================
        logger.info("\n" + "=" * 70)
        logger.info("📊 VERARBEITUNGSZUSAMMENFASSUNG")
        logger.info("=" * 70)
        logger.info(f"Gesamt verarbeitet:      {len(photos)}/{total}")
        logger.info(f"Ohne GPS-Daten:          {missing_gps}")

        if upload_enabled:
            logger.info(f"Erfolgreich hochgeladen: {successful_uploads}/{total}")
            failed = total - successful_uploads
            if failed > 0:
                logger.warning(f"Fehlgeschlagen:          {failed}")
        else:
            logger.info(f"Upload:                  Deaktiviert")

        logger.info("=" * 70)

        return {
            'photos': photos,
            'temp_dir': temp_dir,
            'missing_gps_count': missing_gps,
            'successful_uploads': successful_uploads if upload_enabled else 0
        }

    except Exception as e:
        logger.error(f"✗ Fehler in Photo-Verarbeitung: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None