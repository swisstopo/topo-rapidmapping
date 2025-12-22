"""
KML Generator - Erstellt Overview-KML aus STAC-Items.

Nach Upload aller Photos eines Tages: Abfrage via pystac-client,
um alle Photos zu finden und KML zu generieren.
"""

import logging
import requests
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
    Replaces pystac-client to avoid sqlite3/DLL issues.
    """
    try:
        session = get_session()
        # Ensure endpoint ends with /search
        search_endpoint = f"{stac_url.rstrip('/')}/search"
        
        logger.info(f"  Connecting to STAC (Raw Requests): {search_endpoint}")
        logger.info(f"  Searching items for date: {date}, Product: {product_suffix}")

        # STAC Search Body
        payload = {
            "collections": [collection],
            "datetime": f"{date}T00:00:00Z/{date}T23:59:59Z",
            "limit": 500  # Increased limit to cover a full day in one request
        }
        
        # Execute POST request
        resp = session.post(search_endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        features = data.get("features", [])
        results = []
        
        for feature in features:
            item_id = feature["id"]
            
            # Filter Logic
            if product_suffix not in item_id or 'overview' in item_id:
                continue
            
            assets = feature.get("assets", {})
            props = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            
            # Extract Asset URL
            asset_url = None
            thumbnail_url = None
            
            for asset_key, asset_val in assets.items():
                href = asset_val.get("href")
                if asset_key == 'thumbnail.png':
                    thumbnail_url = href
                elif product_suffix in asset_key and asset_key.endswith(('.jpg', '.jpeg')):
                    asset_url = href
            
            # Extract Geometry (Lat/Lon)
            lat, lon = None, None
            if geometry and geometry.get('type') == 'Point':
                coords = geometry.get('coordinates', [])
                if len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
                    
            timestamp = props.get('datetime', '')
            
            results.append({
                'item_id': item_id,
                'asset_url': asset_url,
                'thumbnail_url': thumbnail_url,
                'lat': lat,
                'lon': lon,
                'timestamp': timestamp
            })

        logger.info(f"  ✓ {len(results)} Items found")
        return results

    except Exception as e:
        logger.error(f"  ✗ STAC query failed: {e}")
        # import traceback
        # logger.error(traceback.format_exc())
        return []

def generate_kml_from_stac_items(
    items: List[Dict],
    output_file: Path,
    product_config: Dict
) -> bool:
    """
    Generates KML file from the list of item dictionaries.
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as kml:
            # KML Header
            kml.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            kml.write('<kml\n')
            kml.write('xmlns="http://www.opengis.net/kml/2.2"\n')
            kml.write('xmlns:gx="http://www.google.com/kml/ext/2.2"\n')
            kml.write('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n')
            kml.write('xsi:schemaLocation="http://www.opengis.net/kml/2.2 https://developers.google.com/kml/schema/kml22gx.xsd">\n')
            kml.write(f'<Document><name>{product_config.get("description", "Overview")} Overview</name>\n')
            
            # Style Definition
            kml.write('<Style id="image_style">\n')
            kml.write('<IconStyle>\n')
            kml.write(f'<scale>{product_config.get("icon_scale", 1.0)}</scale>\n')
            icon_url = product_config.get("icon_url", "http://maps.google.com/mapfiles/kml/shapes/camera.png")
            kml.write(f'<Icon><href>{icon_url}</href><gx:w>48</gx:w><gx:h>48</gx:h></Icon>\n')
            kml.write('</IconStyle>\n')
            kml.write('<LabelStyle>\n')
            kml.write('<color>ff0000ff</color><scale>1.5</scale>\n')
            kml.write('</LabelStyle>\n')
            kml.write('</Style>\n')
            
            # Placemarks
            count = 0
            for item in items:
                if item['lat'] is None or item['lon'] is None:
                    continue
                
                count += 1
                kml.write('<Placemark>\n')
                kml.write(f'<name>{item["item_id"]}</name>\n')
                kml.write(f'<description><![CDATA[')
                if item["asset_url"]:
                    kml.write(f'<a href="{item["asset_url"]}">Download Fullresolution</a><br>')
                kml.write(f'Timestamp: {item["timestamp"]}<br>')
                if item['thumbnail_url']:
                    kml.write(f'<img style="max-width:400px;" src="{item["thumbnail_url"]}">')
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
    
    # Query STAC (using the requests-based function)
    items = query_stac_items_by_date(
        stac_url,
        collection,
        date,
        product_suffix
    )
    
    if not items:
        logger.warning("  ⚠ No items found - KML not created")
        return False
    
    # Generate KML
    return generate_kml_from_stac_items(items, output_file, product_config)
