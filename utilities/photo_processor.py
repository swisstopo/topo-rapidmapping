"""
Individual Photo Processing mit subprocess (GDAL command-line tools).

Verarbeitet Einzelbilder (Nadir/Oblique) - EXIF-Extraktion und Thumbnail-Erstellung.
Basiert auf dem ursprünglichen rm_publish_einzelbilder.py Ansatz.

ÄNDERUNGEN:
- Kopiert Original-Foto in temp_dir und benennt gemäß Asset-Definition um
- Upload erfolgt DIREKT nach Verarbeitung jedes Fotos (vor photos.append)
- Verwendet ausschließlich proxy_handler.py für Proxy-Verwaltung
- NEU v2.1: TIF-zu-JPEG Konvertierung für EBN/EBO mit GPS-EXIF aus GeoTransform
"""

import os
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
from util_publish_stac_fsdi import publish_to_stac
from utilities.file_handler import get_jpg_files

logger = logging.getLogger(__name__)


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
    # Sekunden als Rational mit Nenner 100 (2 Dezimalstellen)
    sec_num = int(round(seconds * 100))
    return [(deg, 1), (minutes, 1), (sec_num, 100)]


def _write_minimal_exif_gps(jpg_path: Path, lat: float, lon: float, dt_str: Optional[str]) -> bool:
    """
    Schreibt GPS-EXIF + DateTimeOriginal direkt in ein JPEG (in-place).

    Struktur des generierten APP1-Segments:
      TIFF-Header (8)
      IFD0 (2 + 2*12 + 4 = 30):  Tag 0x8769 (Exif SubIFD), Tag 0x8825 (GPS IFD)
      Exif SubIFD (2 + 1*12 + 4 = 18):  Tag 0x9003 DateTimeOriginal → ASCII value
      GPS IFD     (2 + 4*12 + 4 = 54):  LatRef, Lat, LonRef, Lon → value data
      Value-Daten:
        DateTimeOriginal ASCII (20 bytes: "YYYY:MM:DD HH:MM:SS\0")
        GPSLatitudeRef  ASCII  (2 bytes)
        GPSLongitudeRef ASCII  (2 bytes)
        GPSLatitude  Rational  (24 bytes)
        GPSLongitude Rational  (24 bytes)

    Tags:
      - DateTimeOriginal  (0x9003) im Exif SubIFD
      - GPSLatitudeRef  (N/S)
      - GPSLatitude     (DMS Rational)
      - GPSLongitudeRef (E/W)
      - GPSLongitude    (DMS Rational)

    Returns:
        True bei Erfolg, False bei Fehler
    """
    try:
        with open(jpg_path, 'rb') as f:
            jpeg_data = f.read()

        if jpeg_data[:2] != b'\xff\xd8':
            logger.warning(f"  ⚠ Kein gültiges JPEG: {jpg_path.name}")
            return False

        BIG = '>'  # Motorola / Big-Endian

        def pack_rational(num, den):
            return struct.pack(f'{BIG}II', num, den)

        TYPE_ASCII    = 2
        TYPE_LONG     = 4
        TYPE_RATIONAL = 5

        # ------------------------------------------------------------------
        # Konstanten: Blockgrößen
        # ------------------------------------------------------------------
        TIFF_HDR_SIZE  = 8   # "MM\x00\x2a" + uint32 offset_to_IFD0
        IFD0_ENTRIES   = 2   # ExifIFD-pointer + GPS-IFD-pointer
        IFD0_SIZE      = 2 + IFD0_ENTRIES * 12 + 4   # = 30
        EXIF_IFD_ENTRIES = 1  # DateTimeOriginal
        EXIF_IFD_SIZE  = 2 + EXIF_IFD_ENTRIES * 12 + 4  # = 18
        GPS_IFD_ENTRIES = 4  # LatRef, Lat, LonRef, Lon
        GPS_IFD_SIZE   = 2 + GPS_IFD_ENTRIES * 12 + 4   # = 54

        # Absolute Offsets (relativ zu TIFF-Header-Beginn)
        ifd0_offset     = TIFF_HDR_SIZE                          # 8
        exif_ifd_offset = ifd0_offset    + IFD0_SIZE             # 38
        gps_ifd_offset  = exif_ifd_offset + EXIF_IFD_SIZE        # 56
        values_offset   = gps_ifd_offset  + GPS_IFD_SIZE         # 110

        # Offsets der einzelnen Werte innerhalb des Value-Bereichs
        dt_ascii        = dt_str.encode('ascii') + b'\x00' if dt_str else b'\x00' * 20
        dt_ascii        = dt_ascii[:20].ljust(20, b'\x00')  # immer genau 20 bytes

        off_dt          = values_offset          # 20 bytes  → DateTimeOriginal
        off_lat_ref     = off_dt     + 20        # 2  bytes  → GPSLatitudeRef
        off_lon_ref     = off_lat_ref + 2        # 2  bytes  → GPSLongitudeRef
        off_lat         = off_lon_ref + 2        # 24 bytes  → GPSLatitude  (3×Rational)
        off_lon         = off_lat    + 24        # 24 bytes  → GPSLongitude (3×Rational)

        # ------------------------------------------------------------------
        # GPS-Daten vorbereiten
        # ------------------------------------------------------------------
        lat_ref      = b'N\x00' if lat >= 0 else b'S\x00'
        lon_ref      = b'E\x00' if lon >= 0 else b'W\x00'
        lat_rational = b''.join(pack_rational(n, d) for n, d in _decimal_to_dms_rational(lat))
        lon_rational = b''.join(pack_rational(n, d) for n, d in _decimal_to_dms_rational(lon))

        # ------------------------------------------------------------------
        # IFD0  (2 Tags: ExifIFD-Pointer + GPS-IFD-Pointer)
        # ------------------------------------------------------------------
        ifd0  = struct.pack(f'{BIG}H', IFD0_ENTRIES)
        ifd0 += struct.pack(f'{BIG}HHII', 0x8769, TYPE_LONG, 1, exif_ifd_offset)  # Exif SubIFD
        ifd0 += struct.pack(f'{BIG}HHII', 0x8825, TYPE_LONG, 1, gps_ifd_offset)   # GPS IFD
        ifd0 += struct.pack(f'{BIG}I', 0)  # next IFD = 0

        # ------------------------------------------------------------------
        # Exif SubIFD  (1 Tag: DateTimeOriginal 0x9003)
        # ------------------------------------------------------------------
        exif_ifd  = struct.pack(f'{BIG}H', EXIF_IFD_ENTRIES)
        exif_ifd += struct.pack(f'{BIG}HHII', 0x9003, TYPE_ASCII, 20, off_dt)
        exif_ifd += struct.pack(f'{BIG}I', 0)  # next IFD = 0

        # ------------------------------------------------------------------
        # GPS IFD  (4 Tags)
        # ------------------------------------------------------------------
        gps_ifd  = struct.pack(f'{BIG}H', GPS_IFD_ENTRIES)
        gps_ifd += struct.pack(f'{BIG}HHII', 0x0001, TYPE_ASCII,    2, off_lat_ref)
        gps_ifd += struct.pack(f'{BIG}HHII', 0x0002, TYPE_RATIONAL, 3, off_lat)
        gps_ifd += struct.pack(f'{BIG}HHII', 0x0003, TYPE_ASCII,    2, off_lon_ref)
        gps_ifd += struct.pack(f'{BIG}HHII', 0x0004, TYPE_RATIONAL, 3, off_lon)
        gps_ifd += struct.pack(f'{BIG}I', 0)  # next IFD = 0

        # ------------------------------------------------------------------
        # Value-Daten
        # ------------------------------------------------------------------
        values = dt_ascii + lat_ref + lon_ref + lat_rational + lon_rational

        # ------------------------------------------------------------------
        # TIFF zusammensetzen
        # ------------------------------------------------------------------
        tiff_header  = b'MM\x00\x2a' + struct.pack(f'{BIG}I', ifd0_offset)
        exif_payload = tiff_header + ifd0 + exif_ifd + gps_ifd + values

        # ------------------------------------------------------------------
        # APP1-Segment
        # ------------------------------------------------------------------
        app1_data    = b'Exif\x00\x00' + exif_payload
        app1_length  = len(app1_data) + 2
        app1_segment = b'\xff\xe1' + struct.pack('>H', app1_length) + app1_data

        # ------------------------------------------------------------------
        # JPEG neu zusammenbauen (altes APP1 ersetzen falls vorhanden)
        # ------------------------------------------------------------------
        rest = jpeg_data[2:]  # nach SOI (FF D8)
        if rest[:2] == b'\xff\xe1':
            old_len = struct.unpack('>H', rest[2:4])[0]
            rest = rest[2 + old_len:]

        with open(jpg_path, 'wb') as f:
            f.write(b'\xff\xd8' + app1_segment + rest)

        if dt_str:
            logger.info(f"     ✓ EXIF geschrieben: lat={lat:.6f}, lon={lon:.6f}, dt={dt_str}")
        else:
            logger.info(f"     ✓ EXIF GPS geschrieben: lat={lat:.6f}, lon={lon:.6f} (kein Datum)")
        return True

    except Exception as e:
        logger.warning(f"     ⚠ EXIF-Schreiben fehlgeschlagen: {e}")
        return False


def convert_tif_to_jpg_with_exif(
    tif_path: Path,
    output_dir: Path,
    quality: int = 85
) -> Optional[Path]:
    """
    Konvertiert ein georeferenziertes GeoTIFF (EBN/EBO) zu JPEG (Qualität 85)
    und schreibt GPS-EXIF aus den Center-Koordinaten des GeoTransform.

    Workflow:
      1. gdalinfo aufrufen → Center-Koordinaten + TIFFTAG_DATETIME extrahieren
      2. gdal_translate → JPEG mit gewünschter Qualität
      3. GPS-EXIF in das JPEG schreiben (reines Python, kein exiftool nötig)

    Das Output-JPEG hat denselben Stammnamen wie das TIF, aber .jpg Endung.
    Es landet in output_dir.

    Args:
        tif_path:   Pfad zur GeoTIFF-Quelldatei
        output_dir: Verzeichnis für das konvertierte JPEG
        quality:    JPEG-Qualität (Standard: 85)

    Returns:
        Path zum erzeugten JPEG oder None bei Fehler
    """
    logger.info(f"  🔄 TIF→JPG Konvertierung: {tif_path.name}")

    # ------------------------------------------------------------------
    # SCHRITT 1: gdalinfo – Koordinaten + Datum
    # ------------------------------------------------------------------
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

    # Center-Koordinaten
    lat, lon = _parse_geotransform_center(gdalinfo_text)
    if lat is None or lon is None:
        logger.warning(f"     ⚠ Keine Center-Koordinaten gefunden – EXIF wird ohne GPS geschrieben")
    else:
        logger.info(f"     ✓ Center: lat={lat:.6f}, lon={lon:.6f}")

    # Datum/Zeit
    dt_str = _parse_tifftag_datetime(gdalinfo_text)
    if dt_str:
        logger.info(f"     ✓ Datum: {dt_str}")
    else:
        logger.warning(f"     ⚠ Kein TIFFTAG_DATETIME gefunden")

    # ------------------------------------------------------------------
    # SCHRITT 2: gdal_translate → JPEG
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    jpg_path = output_dir / (tif_path.stem + '.jpg')

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

        # .aux.xml aufräumen (GDAL_PAM_ENABLED=NO sollte das verhindern, aber sicherheitshalber)
        aux_file = jpg_path.with_suffix('.jpg.aux.xml')
        if aux_file.exists():
            aux_file.unlink()

        logger.info(f"     ✓ JPEG erstellt: {jpg_path.name} ({jpg_path.stat().st_size // 1024} KB)")

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
        _write_minimal_exif_gps(jpg_path, lat, lon, dt_str)
    else:
        logger.warning(f"     ⚠ GPS-EXIF übersprungen (keine Koordinaten)")

    return jpg_path


def convert_tif_files_in_directory(
    input_dir: Path,
    output_dir: Path,
    quality: int = 85
) -> List[Path]:
    """
    Sucht alle .tif/.tiff-Dateien in input_dir und konvertiert sie zu JPEG.

    Gibt eine Liste der erzeugten JPEG-Pfade zurück.
    Dateien, die nicht konvertiert werden konnten, werden übersprungen.

    Args:
        input_dir:  Quellverzeichnis mit TIF-Dateien
        output_dir: Zielverzeichnis für JPEGs
        quality:    JPEG-Qualität (Standard: 85)

    Returns:
        Liste der erzeugten JPEG-Dateien
    """
    tif_files = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {'.tif', '.tiff'}
    )

    if not tif_files:
        return []

    logger.info(f"  Gefunden: {len(tif_files)} TIF-Datei(en) → Konvertiere zu JPEG (Qualität {quality})")
    jpg_files = []

    for tif in tif_files:
        jpg = convert_tif_to_jpg_with_exif(tif, output_dir, quality=quality)
        if jpg:
            jpg_files.append(jpg)
        else:
            logger.warning(f"  ⚠ Konvertierung fehlgeschlagen, überspringe: {tif.name}")

    logger.info(f"  ✓ Konvertierung abgeschlossen: {len(jpg_files)}/{len(tif_files)} erfolgreich")
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
    Parsed EXIF-Timestamp zu Item-Timestamp.
    Fallback auf Dateinamen oder aktuelles Datum wenn EXIF fehlt.
    """
    if exif_timestamp:
        try:
            dt = datetime.strptime(exif_timestamp, "%Y:%m:%d %H:%M:%S")
            return dt.strftime("%Y-%m-%dt%H%M%S").lower()
        except (ValueError, TypeError) as e:
            logger.warning(f"  ⚠ EXIF-Timestamp ungültig: {exif_timestamp}, Fehler: {e}")

    try:
        match = re.search(r'(\d{8})_(\d{6})', photo_name)
        if match:
            dt = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
            logger.info(f"  ℹ Timestamp aus Dateinamen: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
            return dt.strftime("%Y-%m-%dt%H%M%S").lower()

        match = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{6})', photo_name)
        if match:
            date_str = match.group(1).replace('-', '')
            dt = datetime.strptime(date_str + match.group(2), "%Y%m%d%H%M%S")
            logger.info(f"  ℹ Timestamp aus Dateinamen: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
            return dt.strftime("%Y-%m-%dt%H%M%S").lower()

    except Exception as e:
        logger.debug(f"  Konnte Timestamp nicht aus Dateinamen extrahieren: {e}")

    logger.warning(f"  ⚠ Kein Timestamp gefunden - verwende aktuelles Datum")
    return datetime.now().strftime("%Y-%m-%dt%H%M%S").lower()


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
    upload_enabled: bool = True
) -> Optional[Dict]:
    """
    Verarbeitet alle Photos in einem Verzeichnis.

    NEU v2.1: Wenn EBN oder EBO und das Verzeichnis TIF-Dateien enthält,
    werden diese zuerst zu JPEG (Qualität 85) konvertiert und mit GPS-EXIF
    aus den GeoTransform-Center-Koordinaten versehen. Danach läuft der
    Standard-Workflow wie bei normalen JPEGs weiter.
    """
    try:
        # ====================================================================
        # TIF → JPEG VORVERARBEITUNG (NEU v2.1)
        # ====================================================================
        if product_type in [ProductType.EBN, ProductType.EBO]:
            tif_files = sorted(
                p for p in input_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {'.tif', '.tiff'}
            )

            if tif_files:
                logger.info("=" * 70)
                logger.info(f"TIF→JPEG VORVERARBEITUNG ({len(tif_files)} Dateien)")
                logger.info("=" * 70)

                # Konvertierte JPEGs kommen in ein temporäres Unterverzeichnis
                tif_jpg_dir = output_dir / "tif_converted"
                converted = convert_tif_files_in_directory(
                    input_dir=input_dir,
                    output_dir=tif_jpg_dir,
                    quality=85
                )

                if not converted:
                    logger.error("✗ Keine TIF-Dateien konnten konvertiert werden")
                    return None

                # Ab hier weiter mit dem tif_jpg_dir als effektivem input_dir
                logger.info(f"✓ Verwende konvertierte JPEGs aus: {tif_jpg_dir}")
                effective_input_dir = tif_jpg_dir
            else:
                effective_input_dir = input_dir
        else:
            effective_input_dir = input_dir

        # ====================================================================
        # INITIALISIERUNG (Standard-Workflow)
        # ====================================================================
        logger.info(f"Suche JPEG-Dateien in: {effective_input_dir}")
        jpg_files = get_jpg_files(effective_input_dir, recursive=False)
        total = len(jpg_files)
        logger.info(f"  Gefunden: {total} JPEG-Dateien")

        temp_dir = output_dir / "temp_photos"
        temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"  Temp-Verzeichnis: {temp_dir}")

        if upload_enabled:
            from utilities.stac_publisher import publish_to_stac_wrapper

        # ====================================================================
        # FOTOS VERARBEITEN
        # ====================================================================
        logger.info("\n" + "=" * 70)
        logger.info("VERARBEITE PHOTOS MIT DIREKTEM UPLOAD")
        logger.info("=" * 70)

        photos = []
        missing_gps = 0
        successful_uploads = 0

        for idx, jpg_file in enumerate(jpg_files, 1):
            logger.info(f"\n[{idx}/{total}] {jpg_file.name}")
            logger.info("-" * 70)

            try:
                # SCHRITT 1: EXIF extrahieren
                logger.info("  1️⃣  Extrahiere EXIF-Daten (gdalinfo)...")
                lat, lon, exif_timestamp = extract_exif_data(jpg_file)

                if lat is None or lon is None:
                    logger.warning(f"     ⚠ Keine GPS-Daten gefunden")
                    missing_gps += 1
                else:
                    logger.info(f"     ✓ GPS: {lat:.6f}, {lon:.6f}")

                if exif_timestamp:
                    logger.info(f"     ✓ Zeitstempel: {exif_timestamp}")

                # SCHRITT 2: Item- und Asset-Name
                timestamp = parse_exif_timestamp(exif_timestamp, jpg_file.name)
                item_name = generate_item_name(timestamp, product_type)
                asset_name = item_name

                logger.info(f"  2️⃣  Item-Name: {item_name}")
                logger.info(f"     Asset-Name: {asset_name}")

                # SCHRITT 3: Foto kopieren + umbenennen
                logger.info(f"  3️⃣  Kopiere und benenne Foto um...")
                temp_photo_path = temp_dir / (asset_name + jpg_file.suffix)
                shutil.copy2(jpg_file, temp_photo_path)
                logger.info(f"     ✓ Foto kopiert: {temp_photo_path.name}")

                # SCHRITT 4: Thumbnail erstellen
                logger.info(f"  4️⃣  Erstelle Thumbnail (gdal_translate)...")
                temp_thumbnail_path = temp_dir / "thumbnail.jpg"

                thumbnail_success = resize_image_gdal(
                    temp_photo_path,
                    temp_thumbnail_path,
                    max_width=THUMBNAIL_CONFIG['max_width'],
                    max_height=THUMBNAIL_CONFIG['max_height']
                )

                if thumbnail_success:
                    logger.info(f"     ✓ Thumbnail: {temp_thumbnail_path.stat().st_size} bytes")
                else:
                    logger.warning(f"     ⚠ Thumbnail fehlgeschlagen")
                    temp_thumbnail_path = None

                # SCHRITT 5: Foto hochladen
                photo_upload_success = False
                thumbnail_upload_success = False

                if upload_enabled:
                    logger.info(f"  5️⃣  Lade Foto zu STAC hoch...")
                    photo_upload_success = publish_to_stac_wrapper(
                        asset_path=temp_photo_path,
                        item_name=item_name,
                        collection=stac_collection,
                        geocat_id=geocat_id,
                        hostname=hostname,
                        asset_title=product_config['asset_title'],
                        environment=environment
                    )

                    if photo_upload_success:
                        logger.info(f"     ✓ Foto hochgeladen")
                    else:
                        logger.error(f"     ✗ Foto-Upload fehlgeschlagen")

                    # SCHRITT 6: Thumbnail hochladen
                    if photo_upload_success and temp_thumbnail_path and temp_thumbnail_path.exists():
                        logger.info(f"  6️⃣  Lade Thumbnail zu STAC hoch...")
                        thumbnail_upload_success = publish_to_stac_wrapper(
                            asset_path=temp_thumbnail_path,
                            item_name=item_name,
                            collection=stac_collection,
                            geocat_id=geocat_id,
                            hostname=hostname,
                            asset_title="THUMBNAIL",
                            environment=environment
                        )

                        if thumbnail_upload_success:
                            logger.info(f"     ✓ Thumbnail hochgeladen")
                        else:
                            logger.warning(f"     ⚠ Thumbnail-Upload fehlgeschlagen")

                    if photo_upload_success:
                        successful_uploads += 1

                    if photo_upload_success:
                        temp_photo_path.unlink(missing_ok=True)
                        if temp_thumbnail_path and temp_thumbnail_path.exists():
                            temp_thumbnail_path.unlink(missing_ok=True)

                else:
                    logger.info(f"  ℹ️  Upload deaktiviert - Dateien in {temp_dir}")

                # SCHRITT 7: Zur Liste hinzufügen
                photo_info = {
                    'original_path': jpg_file,
                    'temp_photo_path': temp_photo_path,
                    'temp_thumbnail_path': temp_thumbnail_path if thumbnail_success else None,
                    'item_name': item_name,
                    'asset_name': asset_name,
                    'original_filename': jpg_file.name,
                    'lat': lat,
                    'lon': lon,
                    'timestamp': exif_timestamp,
                    'photo_upload_success': photo_upload_success,
                    'thumbnail_upload_success': thumbnail_upload_success
                }
                photos.append(photo_info)

                logger.info("-" * 70)
                if upload_enabled:
                    if photo_upload_success and thumbnail_upload_success:
                        logger.info(f"✅ [{idx}/{total}] VOLLSTÄNDIG ERFOLGREICH")
                    elif photo_upload_success:
                        logger.info(f"⚠️  [{idx}/{total}] TEILWEISE ERFOLGREICH (nur Foto)")
                    else:
                        logger.error(f"❌ [{idx}/{total}] UPLOAD FEHLGESCHLAGEN")
                else:
                    logger.info(f"✅ [{idx}/{total}] VERARBEITUNG ERFOLGREICH (kein Upload)")

            except Exception as e:
                logger.error(f"\n❌ FEHLER bei Foto {jpg_file.name}: {e}")
                import traceback
                traceback.print_exc()

                photos.append({
                    'original_path': jpg_file,
                    'original_filename': jpg_file.name,
                    'error': str(e),
                    'photo_upload_success': False,
                    'thumbnail_upload_success': False
                })

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