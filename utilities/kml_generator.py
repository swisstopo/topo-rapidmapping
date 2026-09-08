"""
KML Generator - Erstellt Overview-KML aus STAC-Items.

Nach Upload aller Photos eines Tages: Abfrage via requests (kein pystac),
um alle Photos zu finden und KML zu generieren.

Enthält zusätzlich get_published_photo_urls() als gemeinsame Hilfsfunktion
für CSV-Export (genutzt von photo_processor.generate_csv_from_stac).
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional
from utilities.proxy_handler import get_session

logger = logging.getLogger(__name__)


def query_stac_items_by_date(
    stac_url: str,
    collection: str,
    date: str,
    product_suffix: str
) -> List[Dict]:
    """
    Queries STAC for all items of a specific date and product using pure requests.
    Handles pagination to retrieve all results.

    Grenzt die Anfrage serverseitig über den STAC 'datetime'-Intervall-Filter auf den
    angegebenen Tag ein (kein Scan des gesamten Katalogs). Da nicht jede STAC-API-Version
    diesen Filter zwingend korrekt umsetzt, wird jedes Ergebnis zusätzlich clientseitig
    gegen das angefragte Datum geprüft ('datetime'-Präfix) — Items ausserhalb des Tages
    werden verworfen und gezählt, statt ungefiltert ins KML zu landen. Ein ungewöhnlich
    hohes Seiten-/Trefferaufkommen für einen einzelnen Tag wird protokolliert, da das ein
    Hinweis darauf wäre, dass der serverseitige Filter nicht greift.

    Args:
        stac_url:       Vollständige STAC-API-URL (endet auf /api/stac/v0.9/)
        collection:     STAC Collection Name
        date:           Datum YYYY-MM-DD
        product_suffix: z.B. "ebn", "ebo" (ohne "-photo"/"-mosaic")

    Returns:
        List[Dict] mit Keys: item_id, asset_url, thumbnail_url, lat, lon, timestamp
    """
    MAX_PAGES = 50  # grosszuegig fuer einen einzelnen Tag; mehr ist ein starkes Indiz
                    # dass der serverseitige 'datetime'-Filter nicht (mehr) greift
    try:
        session = get_session()
        search_endpoint = f"{stac_url.rstrip('/')}/search"

        logger.info(f" Connecting to STAC (Raw Requests): {search_endpoint}")
        logger.info(f" Searching items for date: {date}, Product: {product_suffix}")

        payload = {
            "collections": [collection],
            "datetime": f"{date}T00:00:00Z/{date}T23:59:59Z",
            "limit": 100
        }
        method = "POST"

        all_results = []
        page_count = 0
        skipped_other_date = 0

        while True:
            page_count += 1
            logger.info(f" Fetching page {page_count}...")

            if method == "GET":
                resp = session.get(search_endpoint)
            else:
                resp = session.post(search_endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

            for feature in data.get("features", []):
                item_id = feature["id"]

                # Skip overview items
                if 'overview' in item_id:
                    continue

                # Filter by asset keys — item names no longer contain the product
                # suffix, but asset filenames still do (e.g. ram-...-ebn-photo.jpg)
                assets = feature.get("assets", {})
                if not any(product_suffix in k for k in assets):
                    continue

                props     = feature.get("properties", {})
                geometry  = feature.get("geometry", {})
                timestamp = props.get('datetime', '')

                # Clientseitiges Sicherheitsnetz: nur Items vom angefragten Tag
                # übernehmen, unabhängig davon ob der serverseitige 'datetime'-Filter
                # tatsächlich greift (sonst würde effektiv der gesamte Katalog verarbeitet).
                if not timestamp.startswith(date):
                    skipped_other_date += 1
                    continue

                asset_url     = None
                thumbnail_url = None

                for asset_key, asset_val in assets.items():
                    href = asset_val.get("href")
                    if asset_key == 'thumbnail.jpg':
                        thumbnail_url = href
                    elif product_suffix in asset_key and asset_key.endswith(('.jpg', '.jpeg')):
                        asset_url = href

                lat, lon = None, None
                if geometry and geometry.get('type') == 'Point':
                    coords = geometry.get('coordinates', [])
                    if len(coords) >= 2:
                        lon, lat = coords[0], coords[1]

                all_results.append({
                    'item_id':       item_id,
                    'asset_url':     asset_url,
                    'thumbnail_url': thumbnail_url,
                    'lat':           lat,
                    'lon':           lon,
                    'timestamp':     timestamp
                })

            # Paginierung über den 'next'-Link (STAC API / OGC API Features Standard).
            # Je nach Server ist die naechste Seite ein GET (href bereits vollstaendig,
            # kein body) oder ein POST mit neuem body — beide Faelle korrekt bedienen,
            # statt wie zuvor bei GET-Links faelschlicherweise weiter zu POSTen.
            next_link = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    next_link    = link.get("href")
                    next_body    = link.get("body")
                    method       = (link.get("method") or ("POST" if next_body is not None else "GET")).upper()
                    payload      = next_body
                    break

            if not next_link:
                logger.info(f" No more pages (fetched {page_count} pages total)")
                break

            search_endpoint = next_link

            if page_count >= MAX_PAGES:
                logger.warning(
                    f" ! Sicherheitslimit von {MAX_PAGES} Seiten erreicht für einen "
                    f"einzelnen Tag — ungewöhnlich viele Treffer. Möglicherweise greift "
                    f"der serverseitige 'datetime'-Filter nicht (stoppe Paginierung)."
                )
                break

        if skipped_other_date:
            logger.warning(
                f" ! {skipped_other_date} Item(s) ausserhalb von {date} clientseitig "
                f"herausgefiltert (STAC 'datetime'-Filter evtl. serverseitig unwirksam)"
            )

        logger.info(f"  ✓ {len(all_results)} Items found across {page_count} pages")
        return all_results

    except Exception as e:
        logger.error(f"  ✗ STAC query failed: {e}")
        return []


def get_published_photo_urls(
    stac_url: str,
    collection: str,
    date: str,
    product_suffix: str
) -> List[str]:
    """
    Gibt eine geordnete Liste der effektiv publizierten Foto-URLs aus dem STAC.

    Baut auf query_stac_items_by_date() auf und extrahiert daraus nur die
    Haupt-Asset-URLs (keine Thumbnails, keine KML-Overviews).
    Primäre Datenquelle für generate_csv_from_stac() in photo_processor.py.

    Args:
        stac_url:       Vollständige STAC-API-URL
        collection:     STAC Collection Name
        date:           Datum YYYY-MM-DD
        product_suffix: z.B. "ebn", "ebo"

    Returns:
        Sortierte Liste der Asset-URLs (alphabetisch = chronologisch).
        Leere Liste bei Fehler oder keinen Resultaten.
    """
    items = query_stac_items_by_date(stac_url, collection, date, product_suffix)

    urls = sorted(
        item['asset_url']
        for item in items
        if item.get('asset_url')
    )

    logger.info(f"  ✓ {len(urls)} publizierte Foto-URLs extrahiert")
    return urls


def generate_kml_from_stac_items(
    items: List[Dict],
    output_file: Path,
    product_config: Dict
) -> bool:
    """
    Generates KML file from the list of item dictionaries.
    """
    date_str = items[0]['item_id'].split('-', 1)[1][:10]
    try:
        with open(output_file, 'w', encoding='utf-8') as kml:
            kml.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            kml.write('<kml\n')
            kml.write('xmlns="http://www.opengis.net/kml/2.2"\n')
            kml.write('xmlns:gx="http://www.google.com/kml/ext/2.2"\n')
            kml.write('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n')
            kml.write('xsi:schemaLocation="http://www.opengis.net/kml/2.2 https://developers.google.com/kml/schema/kml22gx.xsd">\n')
            kml.write(f'<Document><name>{date_str} {product_config.get("description", "Overview")}</name>\n')

            kml.write('<Style id="image_style">\n')
            kml.write('<IconStyle>\n')
            kml.write(f'<scale>{product_config.get("icon_scale", 0.75)}</scale>\n')
            icon_url = product_config.get(
                "icon_url",
                "https://map.geo.admin.ch/api/icons/sets/default/icons/100-camera@1x-127,0,255.png"
            )
            kml.write(f'<Icon><href>{icon_url}</href><gx:w>48</gx:w><gx:h>48</gx:h></Icon>\n')
            kml.write('</IconStyle>\n')
            kml.write('<LabelStyle>\n')
            kml.write('<color>ff0000ff</color><scale>1.5</scale>\n')
            kml.write('</LabelStyle>\n')
            kml.write('</Style>\n')

            count = 0
            for item in items:
                if item['lat'] is None or item['lon'] is None:
                    continue
                count += 1

                kml.write('<Placemark>\n')
                kml.write('<name></name>\n')
                kml.write('<description><![CDATA[')

                if item["asset_url"]:
                    kml.write(f'<a href="{item["asset_url"]}">Download-View Fullresolution</a> ')

                kml.write(f'{item["timestamp"]}')

                if item.get('thumbnail_url'):
                    kml.write(f'<br><img style="max-width:400px;" src="{item["thumbnail_url"]}">')

                kml.write(']]></description>\n')
                kml.write('<styleUrl>#image_style</styleUrl>\n')
                kml.write('<Point>\n')
                kml.write(f'<coordinates>{item["lon"]},{item["lat"]},0</coordinates>\n')
                kml.write('</Point>\n')
                kml.write('</Placemark>\n')

            kml.write('</Document>\n')
            kml.write('</kml>\n')

        logger.info(f"  ✓ KML created: {output_file} ({count} Placemarks)")
        return True

    except Exception as e:
        logger.error(f"  ✗ KML creation failed: {e}")
        return False


def create_overview_kml(
    stac_url: str,
    collection: str,
    date: str,
    product_suffix: str,
    product_config: Dict,
    output_file: Path
) -> bool:
    """
    Complete Workflow: Query STAC -> Generate KML.
    """
    logger.info("=" * 70)
    logger.info("KML-OVERVIEW GENERATION")
    logger.info("=" * 70)

    items = query_stac_items_by_date(stac_url, collection, date, product_suffix)

    if not items:
        logger.warning(" ! No items found - KML not created")
        return False

    return generate_kml_from_stac_items(items, output_file, product_config)