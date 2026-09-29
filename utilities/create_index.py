"""
Jahres-Übersichtsindex (KML + GPKG + CSV) über alle RAM/KRY STAC-Items.

Eigenes Modul, weil es sich um eine klar abgegrenzte Zusatzfunktion handelt
(Jahres-Reporting über den gesamten STAC-Bestand), die weder in
rapidmapping_processor.py (Einzel-Workflow pro Aufnahme) noch in
configuration.py (reine Konstanten/Namenskonventionen) passt.

Klassifikation pro STAC-Item (siehe query_year_items):
- RAM-Item mit einem Asset vom Typ "application/vnd.google-earth.kml+xml"
  -> Tages-Übersichts-KML (EBN/EBO). Wird in die Jahres-KML gemergt: gleiche
     Icons wie im Original, nur farblich auf RAM=rot umgestellt.
- RAM-Item mit Polygon-Geometrie UND mindestens einem Asset vom Typ
  "image/tiff..." -> Mosaik-Footprint. Die Item-Geometrie wird 1:1 als
  Polygon gezeichnet (keine Rasterdarstellung, kein Zoomstufen-Umschalten).
- KRY-Item mit Polygon-Geometrie -> Mosaik-Footprint (wie oben, ohne
  zusätzliche Asset-Prüfung).
- Alles andere (Einzelbilder, unbekannte Item-Präfixe, ...) wird ignoriert.

Was erzeugt wird (pro Jahr, ein Aufruf = ein Jahr):
- <jahr>.kml   Eine Datei mit den gemergten Tages-KMLs + allen Mosaik-
               Footprint-Polygonen. Klick auf eine Geometrie öffnet einen
               Tooltip mit einem Link auf das Item im STAC-Browser.
- <jahr>.gpkg  Gleiche Mosaik-Footprints als Polygone, EPSG:2056 (LV95) -
               analog zur bestehenden Konvention für Schweizer Geodaten-
               Downloads (vgl. lubis-luftbilder_digital_2056.gpkg).
- <jahr>.csv   Gleiche Mosaik-Footprints als Tabelle (Zentrum lon/lat,
               WGS84), eine Zeile pro Mosaik.

Alle Item-Farben: "ram-..." Items rot, "kry-..." Items blau (Cryosphere).

Datenquelle die STAC-Suche plus (nur für die Tages-KML-Fusion) ein GET auf
die bereits publizierten Tages-Übersichts-KMLs selbst. Keine Anmeldedaten
nötig - reine Lesefunktion.
"""

import argparse
import csv
import json
import logging
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from configuration import (
    STAC_COLLECTION,
    STAC_HOSTNAME,
    STAC_HOSTNAME_PROD,
    STAC_SCHEME,
    STAC_API_PATH,
    get_browser_item_url,
)
from utilities.proxy_handler import get_session

logger = logging.getLogger(__name__)

KML_NS = "{http://www.opengis.net/kml/2.2}"
GX_NS = "{http://www.google.com/kml/ext/2.2}"

# Item-Präfixe und ihre Darstellungsfarbe (KML: AABBGGRR, RGB-Tupel für Icons)
RAM_PREFIX = "ram"
KRY_PREFIX = "kry"
PREFIX_STYLE = {
    RAM_PREFIX: {"kml_color": "ff0000ff", "fill_color": "7f0000ff", "rgb": "255,0,0"},   # rot
    KRY_PREFIX: {"kml_color": "ffff0000", "fill_color": "7fff0000", "rgb": "0,0,255"},   # blau
}
MAX_PAGES_PER_YEAR = 500  # ein Jahres-Sweep durchsucht deutlich mehr Items als ein Tages-Sweep


def resolve_hostname(prod: bool) -> str:
    """
    Wählt den STAC-Hostname anhand der Umgebung.

    INT bleibt Default (siehe CLAUDE.md) - PROD nur bei explizitem --prod.
    """
    return STAC_HOSTNAME_PROD if prod else STAC_HOSTNAME


def _dedupe_ring(ring: List[List[float]]) -> List[Tuple[float, float]]:
    """Entfernt den schliessenden Punkt eines GeoJSON-Rings (erster == letzter Punkt), falls vorhanden."""
    pts = [(pt[0], pt[1]) for pt in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def compute_bbox(exterior_ring: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Gibt (west, south, east, north) für einen Ring aus (lon, lat)-Punkten zurück."""
    lons = [p[0] for p in exterior_ring]
    lats = [p[1] for p in exterior_ring]
    return min(lons), min(lats), max(lons), max(lats)


def _ring_area(ring: List[Tuple[float, float]]) -> float:
    """
    Grobe Flächenschätzung eines Rings über die Shoelace-Formel (in Grad² -
    reicht für den relativen Grössenvergleich zweier Footprints, keine
    exakte geodätische Fläche nötig).
    """
    area = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


# Reine Anzeige-Priorität für den im Tooltip gezeigten Asset-Namen - schliesst
# KEIN Item aus (Ein-/Ausschluss läuft in query_year_items nur über "hat
# mindestens ein image/tiff-Asset" bzw. Polygon-Geometrie). Existiert das
# finale DOP-RGB-MOSAIC, wird das als "der" Asset-Name gezeigt statt QDOP.
MOSAIC_ASSET_TITLE_PRIORITY = ["DOP-RGB-MOSAIC", "QDOP-RGB-MOSAIC"]


def _normalize_title(title: Optional[str]) -> str:
    """Vereinheitlicht Asset-Titel für den Vergleich (Gross-/Kleinschreibung, Leerzeichen vs. Bindestrich)."""
    if not title:
        return ""
    return re.sub(r"[\s_-]+", "-", title.strip().upper())


def _pick_display_asset(assets: Dict) -> Optional[str]:
    """
    Wählt einen Anzeige-Namen für "den" Mosaik-Asset eines Items, rein für
    die Tooltip-Anzeige ("always show ... the asset name") - hat keinen
    Einfluss darauf, ob ein Item überhaupt als Footprint gezeigt wird.

    Priorität: finales DOP-RGB-MOSAIC > QDOP-RGB-MOSAIC > Titel/Dateiname
    des ersten gefundenen TIFF-Assets (z.B. bei DSM- oder Punktwolken-
    Produkten ohne erkannten Titel).
    """
    tiff_assets = {k: v for k, v in assets.items() if str(v.get("type", "")).lower().startswith("image/tiff")}
    if not tiff_assets:
        return None

    by_norm_title = {_normalize_title(a.get("title")): k for k, a in tiff_assets.items() if a.get("title")}
    for wanted in MOSAIC_ASSET_TITLE_PRIORITY:
        if wanted in by_norm_title:
            key = by_norm_title[wanted]
            return tiff_assets[key].get("title") or key

    first_key = next(iter(tiff_assets))
    return tiff_assets[first_key].get("title") or first_key


def _fallback_visual_url(assets: Dict) -> Optional[str]:
    """
    Baut selbst einen map.geo.admin.ch-COG-Viewer-Link, wenn das Item keinen
    rel=visual-Link liefert (kommt vor - siehe z.B. Items ohne "-qdop-" im
    Dateinamen). Priorität (erster Treffer über alle Assets gewinnt):

    1. explizites finales "...-dop-rgb-mosaic.tif"
    2. finales DOP mit blankem Dateinamen "...-rgb-mosaic.tif" (ohne
       "-qdop-"/"-dop-" davor - das reale Namensschema des finalen Produkts)
    3. Quick "...-qdop-rgb-mosaic.tif"
    4. "...-dsm-hillshade.tif" als letzter Ausweg

    Stufe 2 schliesst "-qdop-"/"-dop-" explizit aus, weil ein einfaches
    endswith("rgb-mosaic.tif") sonst auch auf "-qdop-rgb-mosaic.tif" passen
    würde (das endet ja ebenfalls auf "rgb-mosaic.tif") und DOP so nicht
    zuverlässig vor QDOP gewählt würde, wenn ein Item beide Assets hat.

    Gleiche URL-Konvention wie util_publish_stac_fsdi.py ("layers=COG|<href>").
    """
    def href_matching(predicate) -> Optional[str]:
        for key, asset in assets.items():
            if predicate(key.lower()) and asset.get("href"):
                return asset["href"]
        return None

    href = (
        href_matching(lambda k: k.endswith("-dop-rgb-mosaic.tif"))
        or href_matching(lambda k: k.endswith("rgb-mosaic.tif") and "-qdop-" not in k and "-dop-" not in k)
        or href_matching(lambda k: k.endswith("-qdop-rgb-mosaic.tif"))
        or href_matching(lambda k: k.endswith("dsm-hillshade.tif"))
    )
    return f"https://map.geo.admin.ch/#/map?layers=COG|{href}" if href else None


def _style_id_for_item(item_id: str) -> str:
    """Gibt den Style-Key ('ram'/'kry') zurück; unbekannte Präfixe fallen auf 'ram' zurück (mit Warnung)."""
    prefix = item_id.split("-", 1)[0]
    if prefix not in PREFIX_STYLE:
        logger.warning(f" ! Unbekanntes Item-Präfix '{prefix}' bei '{item_id}' - verwende Standardfarbe (rot)")
        return RAM_PREFIX
    return prefix


def query_year_items(stac_url: str, collection: str, year: int) -> Dict[str, List[Dict]]:
    """
    Fragt STAC einmalig für das ganze Jahr ab (serverseitiger datetime-Filter,
    gleiche Paginierungs-/Merge-Logik wie kml_generator.query_stac_items_by_date)
    und klassifiziert die Treffer clientseitig in:

    - "mosaics":       RAM-Items mit Polygon-Geometrie + mind. einem
                        image/tiff-Asset, sowie alle KRY-Items mit
                        Polygon-Geometrie (Footprints).
    - "kml_overviews": RAM-Items mit einem Asset vom Typ
                        application/vnd.google-earth.kml+xml (Tages-
                        Übersichten EBN/EBO).

    Einzelbild-Items (Point-Geometrie) werden hier bewusst NICHT einzeln
    übernommen - sie sind bereits in den Tages-Overview-KMLs enthalten.

    Returns:
        Dict mit den beiden Listen oben.
    """
    session = get_session()
    search_endpoint = f"{stac_url.rstrip('/')}/search"

    payload = {
        "collections": [collection],
        "datetime": f"{year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z",
        "limit": 100,
    }
    method = "POST"

    mosaics: List[Dict] = []
    kml_overviews: List[Dict] = []
    total_scanned = 0
    page_count = 0
    skipped_other_year = 0

    logger.info(f" Durchsuche STAC-Collection '{collection}' für Jahr {year} ...")

    while True:
        page_count += 1

        if method == "GET":
            resp = session.get(search_endpoint)
        else:
            resp = session.post(search_endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()

        for feature in data.get("features", []):
            total_scanned += 1
            item_id = feature["id"]
            props = feature.get("properties", {})
            timestamp = props.get("datetime", "")

            if not timestamp.startswith(str(year)):
                skipped_other_year += 1
                continue

            assets = feature.get("assets", {})
            geometry = feature.get("geometry", {})
            prefix = item_id.split("-", 1)[0]

            if prefix == RAM_PREFIX:
                # Ein Tages-Overview-Item kann sowohl ein EBN- als auch ein
                # EBO-KML-Asset gleichzeitig haben - beide erfassen, nicht nur
                # das erste gefundene.
                kml_hrefs = [
                    a["href"] for a in assets.values()
                    if a.get("type") == "application/vnd.google-earth.kml+xml" and a.get("href")
                ]
                if kml_hrefs:
                    for kml_href in kml_hrefs:
                        kml_overviews.append({"item_id": item_id, "kml_url": kml_href, "timestamp": timestamp})
                    continue

            if geometry.get("type") != "Polygon":
                continue  # Einzelbilder (Point-Geometrie) sind hier nicht relevant

            if prefix == RAM_PREFIX:
                has_tiff = any(str(a.get("type", "")).lower().startswith("image/tiff") for a in assets.values())
                if not has_tiff:
                    continue
            elif prefix != KRY_PREFIX:
                continue  # unbekanntes Präfix (z.B. Katalog-Testitems) wird ignoriert

            ring = _dedupe_ring(geometry["coordinates"][0])
            if len(ring) < 3:
                logger.warning(f" ! {item_id}: ungültige Footprint-Geometrie - übersprungen")
                continue

            # Vorschaubild (rel=preview) und Kartenviewer-Link (rel=visual) stehen
            # auf Item-Ebene in 'links' (siehe util_publish_stac_fsdi.py
            # item_create_json_payload) - nicht in den Assets. Nicht jedes
            # Item hat einen 'preview'-Link (z.B. ältere/andere Publish-Wege) -
            # existiert trotzdem ein thumbnail.jpg-Asset, wird das als
            # Fallback verwendet, damit ein vorhandenes Vorschaubild nie
            # unterschlagen wird.
            item_links = feature.get("links", [])
            preview_url = next((l["href"] for l in item_links if l.get("rel") == "preview" and l.get("href")), None)
            if not preview_url:
                preview_url = assets.get("thumbnail.jpg", {}).get("href")
            visual_url = next((l["href"] for l in item_links if l.get("rel") == "visual" and l.get("href")), None)
            if not visual_url:
                visual_url = _fallback_visual_url(assets)

            mosaics.append({
                "item_id": item_id,
                "timestamp": timestamp,
                "ring": ring,
                "preview_url": preview_url,
                "visual_url": visual_url,
                "asset_name": _pick_display_asset(assets),
            })

        next_link = None
        for link in data.get("links", []):
            if link.get("rel") == "next":
                next_link = link.get("href")
                next_body = link.get("body") or {}
                method = (link.get("method") or ("POST" if next_body else "GET")).upper()
                if link.get("merge") and isinstance(payload, dict):
                    payload = {**payload, **next_body}
                else:
                    payload = next_body
                break

        if not next_link:
            break
        search_endpoint = next_link

        if page_count >= MAX_PAGES_PER_YEAR:
            logger.warning(
                f" ! Sicherheitslimit von {MAX_PAGES_PER_YEAR} Seiten erreicht für Jahr {year} "
                f"- möglicherweise nicht der komplette Jahresbestand erfasst."
            )
            break

    if skipped_other_year:
        logger.warning(f" ! {skipped_other_year} Item(s) ausserhalb von {year} clientseitig herausgefiltert")

    logger.info(
        f"  ✓ {total_scanned} Items gescannt ({page_count} Seiten) -> "
        f"{len(mosaics)} Mosaik(e), {len(kml_overviews)} Tages-Übersichts-KML(s)"
    )
    return {"mosaics": mosaics, "kml_overviews": kml_overviews}


def _recolor_icon_url(href: str, rgb: str) -> str:
    """
    Ersetzt die im Icon-Dateinamen codierte Farbe (z.B. '...-127,0,255.png')
    durch 'rgb' - die Icon-Form (Kamera/Kreis/...) bleibt unverändert.
    """
    new_href, n = re.subn(r"-\d+,\d+,\d+(\.png)$", rf"-{rgb}\1", href)
    return new_href if n else href


def _fetch_day_kml_placemarks(kml_url: str, rgb: str) -> Tuple[Optional[Dict], List[Tuple[str, str]]]:
    """
    Lädt eine bereits publizierte Tages-Übersichts-KML (EBN/EBO) und liefert
    ihre Placemarks zum Einbetten in die Jahres-KML zurück.

    IconStyle (Form, Grösse gx:w/gx:h, scale) wird 1:1 aus dem Original
    übernommen ("keep the icon") - nur die im Icon-Dateinamen codierte Farbe
    wird auf 'rgb' umgestellt ("change the color"), damit die Jahres-KML
    farblich konsistent mit RAM=rot bleibt. EBN und EBO haben unterschiedliche
    scale/Icon-Grösse (siehe configuration.py) - deshalb hier aus der
    Original-KML gelesen statt selbst neu festgelegt.

    Returns:
        (icon_info_oder_None, [(coordinates, description_html), ...])
        icon_info = {"href", "scale", "w", "h"} - "scale"/"w"/"h" sind die
        Original-Rohtexte aus der Quell-KML (w/h können None sein).
    """
    session = get_session()
    resp = session.get(kml_url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    icon_style_el = root.find(f".//{KML_NS}IconStyle")
    icon_info = None
    if icon_style_el is not None:
        href_el = icon_style_el.find(f"{KML_NS}Icon/{KML_NS}href")
        if href_el is not None and href_el.text:
            scale_el = icon_style_el.find(f"{KML_NS}scale")
            w_el = icon_style_el.find(f"{KML_NS}Icon/{GX_NS}w")
            h_el = icon_style_el.find(f"{KML_NS}Icon/{GX_NS}h")
            icon_info = {
                "href": _recolor_icon_url(href_el.text.strip(), rgb),
                "scale": scale_el.text.strip() if scale_el is not None and scale_el.text else "1.0",
                "w": w_el.text.strip() if w_el is not None and w_el.text else None,
                "h": h_el.text.strip() if h_el is not None and h_el.text else None,
            }

    placemarks = []
    for pm in root.iter(f"{KML_NS}Placemark"):
        coords_el = pm.find(f"{KML_NS}Point/{KML_NS}coordinates")
        if coords_el is None or not coords_el.text:
            continue
        desc_el = pm.find(f"{KML_NS}description")
        description = desc_el.text if desc_el is not None and desc_el.text else ""
        placemarks.append((coords_el.text.strip(), description))

    return icon_info, placemarks


def _write_day_kml_folder(kml, year: int, kml_overviews: List[Dict]) -> None:
    """Lädt alle Tages-Übersichts-KMLs und schreibt sie (gemergt, umgefärbt) als eine Folder."""
    ram_rgb = PREFIX_STYLE[RAM_PREFIX]["rgb"]
    ram_label_color = PREFIX_STYLE[RAM_PREFIX]["kml_color"]

    style_id_by_icon: Dict[Optional[str], str] = {}
    style_defs: List[Tuple[str, Optional[Dict]]] = []
    day_placemarks: List[Tuple[str, str, str]] = []

    for day in kml_overviews:
        try:
            icon_info, placemarks = _fetch_day_kml_placemarks(day["kml_url"], ram_rgb)
        except Exception as e:
            logger.warning(f" ! Tages-KML {day['item_id']} konnte nicht geladen werden: {e} - übersprungen")
            continue

        icon_key = icon_info["href"] if icon_info else None
        if icon_key not in style_id_by_icon:
            style_id = f"day_icon_{len(style_id_by_icon)}"
            style_id_by_icon[icon_key] = style_id
            style_defs.append((style_id, icon_info))

        style_id = style_id_by_icon[icon_key]
        for coords, desc in placemarks:
            day_placemarks.append((style_id, coords, desc))

    kml.write(f'<Folder><name>Einzelbilder Tages-Übersichten (EBN/EBO) {year}</name>\n')

    for style_id, icon_info in style_defs:
        kml.write(f'<Style id="{style_id}"><IconStyle>')
        if icon_info:
            kml.write(f'<scale>{icon_info["scale"]}</scale>')
            kml.write(f'<Icon><href>{icon_info["href"]}</href>')
            if icon_info["w"]:
                kml.write(f'<gx:w>{icon_info["w"]}</gx:w>')
            if icon_info["h"]:
                kml.write(f'<gx:h>{icon_info["h"]}</gx:h>')
            kml.write("</Icon>")
        kml.write("</IconStyle>")
        kml.write(f"<LabelStyle><color>{ram_label_color}</color><scale>1.2</scale></LabelStyle>")
        kml.write("</Style>\n")

    for style_id, coords, desc in day_placemarks:
        kml.write("<Placemark>\n<name></name>\n")
        kml.write(f"<description><![CDATA[{desc}]]></description>\n")
        kml.write(f"<styleUrl>#{style_id}</styleUrl>\n")
        kml.write(f"<Point><coordinates>{coords}</coordinates></Point>\n")
        kml.write("</Placemark>\n")

    kml.write("</Folder>\n")
    logger.info(f"  ✓ {len(day_placemarks)} Einzelbild-Placemarks aus {len(kml_overviews)} Tages-KML(s) gemergt")


def _footprint_description(item: Dict, hostname: str) -> str:
    """Tooltip für einen Mosaik-Footprint: Item-/Asset-Name, Link zum Item, optional Kartenviewer-Link + Vorschaubild."""
    browser_url = get_browser_item_url(item["item_id"], hostname=hostname)

    lines = [f'Item: {item["item_id"]}']
    if item.get("asset_name"):
        lines.append(f'Asset: {item["asset_name"]}')
    lines.append(f'<a href="{browser_url}">Item im STAC-Browser öffnen</a>')
    if item.get("visual_url"):
        lines.append(f'<a href="{item["visual_url"]}" target="_blank">open in map.geo.admin.ch</a>')

    description = "<br>".join(lines)
    if item.get("preview_url"):
        description += f'<br><img style="max-width:400px;" src="{item["preview_url"]}">'

    return description


def write_yearly_kml(year: int, mosaics: List[Dict], kml_overviews: List[Dict], output_file: Path, hostname: str) -> bool:
    """Schreibt die kombinierte Jahres-KML-Datei."""
    try:
        with open(output_file, "w", encoding="utf-8") as kml:
            kml.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            kml.write('<kml xmlns="http://www.opengis.net/kml/2.2" '
                       'xmlns:gx="http://www.google.com/kml/ext/2.2">\n')
            kml.write(f"<Document><name>Spezialbefliegungen Übersicht {year}</name>\n")

            for prefix, style in PREFIX_STYLE.items():
                kml.write(f'<Style id="footprint_{prefix}">'
                           f'<LineStyle><color>{style["kml_color"]}</color><width>2</width></LineStyle>'
                           f'<PolyStyle><color>{style["fill_color"]}</color></PolyStyle>'
                           f"</Style>\n")

            # Reihenfolge im Dokument = Zeichenreihenfolge in den meisten Viewern
            # (spaeter geschriebene Elemente werden ueber frueheren gezeichnet -
            # in QGIS z.B. strikt so beim Import). Die Mosaik-Footprint-Polygone
            # muessen deshalb VOR den Einzelbild-Punkten stehen, sonst koennten
            # die Polygonflaechen die EBN/EBO-Punkte optisch verdecken.
            #
            # Innerhalb der Footprints selbst: absteigend nach Fläche sortiert,
            # d.h. grosse Footprints zuerst (unten), kleine zuletzt (oben) -
            # sonst kann ein kleiner Footprint (z.B. eine einzelne RAM-Befliegung)
            # optisch unter einem grossflächigeren KRY-Gletscher-Footprint
            # verschwinden, mit dem er sich überlappt.
            mosaics_sorted = sorted(mosaics, key=lambda m: _ring_area(m["ring"]), reverse=True)

            kml.write(f'<Folder><name>Mosaik-Footprints {year}</name>\n')
            for item in mosaics_sorted:
                closed_ring = item["ring"] + [item["ring"][0]]
                coords_str = " ".join(f"{lon},{lat},0" for lon, lat in closed_ring)
                description = _footprint_description(item, hostname)
                style_id = _style_id_for_item(item["item_id"])

                kml.write("<Placemark>\n<name></name>\n")
                kml.write(f"<description><![CDATA[{description}]]></description>\n")
                kml.write(f"<styleUrl>#footprint_{style_id}</styleUrl>\n")
                kml.write("<Polygon><outerBoundaryIs><LinearRing><coordinates>")
                kml.write(coords_str)
                kml.write("</coordinates></LinearRing></outerBoundaryIs></Polygon>\n")
                kml.write("</Placemark>\n")
            kml.write("</Folder>\n")

            _write_day_kml_folder(kml, year, kml_overviews)

            kml.write("</Document>\n</kml>\n")

        logger.info(f"  ✓ KML erstellt: {output_file} ({len(mosaics)} Mosaik-Footprints, {len(kml_overviews)} Tages-KMLs)")
        return True

    except Exception as e:
        logger.error(f"  ✗ KML-Erstellung fehlgeschlagen: {e}")
        return False


def _mosaics_to_geojson(mosaics: List[Dict], hostname: str) -> Dict:
    features = []
    for item in mosaics:
        ring = item["ring"] + [item["ring"][0]]  # Ring schliessen
        prefix = item["item_id"].split("-", 1)[0]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[lon, lat] for lon, lat in ring]]},
            "properties": {
                "item_id": item["item_id"],
                "prefix": prefix,
                "asset_name": item.get("asset_name"),
                "timestamp": item["timestamp"],
                "browser_url": get_browser_item_url(item["item_id"], hostname=hostname),
                "map_viewer_url": item.get("visual_url"),
                "thumbnail_url": item.get("preview_url"),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def write_index_gpkg(mosaics: List[Dict], output_file: Path, hostname: str) -> bool:
    """
    Schreibt die Mosaik-Footprints als GeoPackage in EPSG:2056 (LV95).

    Nutzt ogr2ogr per subprocess (gleiches GDAL-Toolset, das dieses Projekt
    bereits für gdalinfo/gdal_translate verwendet) statt eines neuen
    Python-GIS-Package (fiona/geopandas) - keine neue Abhängigkeit nötig.
    STAC liefert Geometrien in WGS84 (STAC-Spezifikation); ogr2ogr übernimmt
    die Umprojektion nach EPSG:2056 in einem Schritt.
    """
    geojson = _mosaics_to_geojson(mosaics, hostname)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False, encoding="utf-8") as tmp:
        json.dump(geojson, tmp)
        tmp_path = Path(tmp.name)

    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            output_file.unlink()

        result = subprocess.run(
            [
                "ogr2ogr", "-f", "GPKG",
                "-s_srs", "EPSG:4326", "-t_srs", "EPSG:2056",
                "-nln", "footprints",
                str(output_file), str(tmp_path),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"  ✗ GPKG-Erstellung fehlgeschlagen: {result.stderr.strip()}")
            logger.error("  -> Ist 'ogr2ogr' (Teil von GDAL) installiert und im PATH?")
            return False

        logger.info(f"  ✓ GPKG erstellt: {output_file} ({len(geojson['features'])} Footprints, EPSG:2056)")
        return True

    except FileNotFoundError:
        logger.error("  ✗ 'ogr2ogr' wurde nicht gefunden. Bitte GDAL installieren (siehe requirements.txt).")
        return False
    except Exception as e:
        logger.error(f"  ✗ GPKG-Erstellung fehlgeschlagen: {e}")
        return False
    finally:
        tmp_path.unlink(missing_ok=True)


def write_index_csv(mosaics: List[Dict], output_file: Path, hostname: str) -> bool:
    """Schreibt die Mosaik-Footprints (Zentrum lon/lat, WGS84) als CSV-Tabelle."""
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["item_id", "prefix", "asset_name", "timestamp", "lon", "lat", "browser_url", "map_viewer_url", "thumbnail_url"])
            for item in mosaics:
                west, south, east, north = compute_bbox(item["ring"])
                cx, cy = (west + east) / 2, (south + north) / 2
                prefix = item["item_id"].split("-", 1)[0]
                writer.writerow([
                    item["item_id"], prefix, item.get("asset_name") or "", item["timestamp"], cx, cy,
                    get_browser_item_url(item["item_id"], hostname=hostname),
                    item.get("visual_url") or "",
                    item.get("preview_url") or "",
                ])

        logger.info(f"  ✓ CSV erstellt: {output_file} ({len(mosaics)} Zeilen)")
        return True

    except Exception as e:
        logger.error(f"  ✗ CSV-Erstellung fehlgeschlagen: {e}")
        return False


def create_yearly_index(year: int, output_dir: Path, prod: bool = False) -> bool:
    """
    Kompletter Workflow für ein Jahr: STAC abfragen -> KML + GPKG + CSV schreiben.

    Returns:
        bool: True wenn mindestens eine Datei erfolgreich erstellt wurde.
    """
    hostname = resolve_hostname(prod)
    stac_url = f"{STAC_SCHEME}://{hostname}{STAC_API_PATH}"

    logger.info("=" * 70)
    logger.info(f"JAHRES-INDEX {year} ({'PROD' if prod else 'INT'}: {hostname})")
    logger.info("=" * 70)

    try:
        items = query_year_items(stac_url, STAC_COLLECTION, year)
    except Exception as e:
        logger.error(f"  ✗ STAC-Abfrage fehlgeschlagen: {e}")
        logger.error("  -> Bitte Netzwerk/Proxy und STAC-Erreichbarkeit prüfen.")
        return False

    mosaics = items["mosaics"]
    kml_overviews = items["kml_overviews"]

    if not mosaics and not kml_overviews:
        logger.warning(f" ! Keine Items für Jahr {year} gefunden - es werden keine Dateien erstellt")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"rapidmapping_index_{year}"

    ok_kml = write_yearly_kml(year, mosaics, kml_overviews, output_dir / f"{base_name}.kml", hostname)

    if mosaics:
        ok_gpkg = write_index_gpkg(mosaics, output_dir / f"{base_name}_2056.gpkg", hostname)
        ok_csv = write_index_csv(mosaics, output_dir / f"{base_name}.csv", hostname)
    else:
        logger.warning(" ! Keine Mosaike gefunden - GPKG/CSV werden übersprungen")
        ok_gpkg = ok_csv = False

    success = ok_kml or ok_gpkg or ok_csv
    if success:
        logger.info(f"✓ ERFOLG: Jahres-Index {year} in {output_dir} erstellt")
    else:
        logger.error(f"✗ FEHLER: Für Jahr {year} konnte keine Datei erstellt werden")
    return success


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Erstellt einen Jahres-Übersichtsindex (KML/GPKG/CSV) über RAM/KRY STAC-Items.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
    python -m utilities.create_index --year 2024
    python -m utilities.create_index --year 2024 --prod
    python -m utilities.create_index --year 2024 --output-dir C:\\temp\\rm_index
        """,
    )
    parser.add_argument("--year", type=int, required=True, metavar="YYYY",
                         help="Jahr, für das der Index erstellt wird")
    parser.add_argument("--prod", action="store_true",
                         help="Produktionsumgebung verwenden (default: INT)")
    parser.add_argument("--output-dir", dest="output_dir", default="output/index", metavar="VERZEICHNIS",
                         help="Zielverzeichnis für KML/GPKG/CSV (default: output/index)")
    args = parser.parse_args()

    if not (1990 <= args.year <= 2100):
        logger.error(f"✗ Ungültiges Jahr: {args.year} (erwartet 1990-2100)")
        return 1

    success = create_yearly_index(args.year, Path(args.output_dir), prod=args.prod)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
