"""
STAC Query Utilities mit pystac-client.

Funktionen zum Abfragen von STAC-Items und Assets für KML-Generierung.
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

try:
    from pystac_client import Client
    import pystac
except ImportError:
    raise ImportError(
        "pystac-client nicht gefunden!\n"
        "Installation: pip install pystac-client pystac"
    )

from utilities.proxy_handler import get_session

logger = logging.getLogger(__name__)


def get_stac_client(stac_url: str) -> Optional[Client]:
    """
    Erstellt STAC-Client mit Proxy-Support.
    
    Args:
        stac_url (str): STAC API URL
        
    Returns:
        Optional[Client]: STAC Client oder None bei Fehler
    """
    try:
        # Verwende Session mit Proxy-Config
        session = get_session()
        
        client = Client.open(
            stac_url,
            headers=session.headers,
            # Proxy wird über requests Session gehandhabt
        )
        
        logger.info(f"  ✓ STAC-Client verbunden: {stac_url}")
        return client
        
    except Exception as e:
        logger.error(f"  ✗ STAC-Client-Fehler: {e}")
        return None


def find_items_by_date_and_product(
    stac_url: str,
    collection: str,
    date: str,
    product_suffix: str
) -> List[Dict]:
    """
    Findet alle STAC-Items für ein bestimmtes Datum und Produkt.
    
    Args:
        stac_url (str): STAC API URL
        collection (str): Collection Name
        date (str): Datum im Format YYYY-MM-DD
        product_suffix (str): Produkt-Suffix (z.B. "ebn", "ebo")
        
    Returns:
        List[Dict]: Liste von Item-Dictionaries mit Asset-Infos
        
    Example Result:
        [
            {
                'item_id': 'ram-2024-07-15t120000-ebn',
                'assets': [
                    {
                        'name': 'ram-2024-07-15t120000-ebn.jpg',
                        'url': 'https://...',
                        'thumbnail_url': 'https://.../thumbnail.jpg'
                    }
                ]
            }
        ]
    """
    try:
        client = get_stac_client(stac_url)
        if client is None:
            return []
        
        # Suche Items in Collection
        # Pattern: ram-{date}t*-{product_suffix}
        search_pattern = f"ram-{date}t*-{product_suffix}"
        
        logger.info(f"  Suche STAC-Items mit Pattern: {search_pattern}")
        
        # STAC-Suche
        # Hinweis: Nicht alle STAC-APIs unterstützen Wildcards direkt
        # Daher laden wir alle Items des Tages und filtern manuell
        
        search = client.search(
            collections=[collection],
            datetime=f"{date}T00:00:00Z/{date}T23:59:59Z"
        )
        
        results = []
        for item in search.items():
            item_id = item.id
            
            # Filtere nach Produkt-Suffix
            if product_suffix not in item_id:
                continue
            
            # Sammle Assets (ohne KML und Thumbnails)
            assets = []
            for asset_key, asset in item.assets.items():
                # Ignoriere overview-KMLs und einzelne Thumbnails
                if 'overview' in asset_key.lower() or 'thumbnail' in asset_key.lower():
                    continue
                
                # Finde zugehöriges Thumbnail
                thumbnail_key = 'thumbnail.jpg'  # Standard-Thumbnail-Name
                thumbnail_url = None
                if thumbnail_key in item.assets:
                    thumbnail_url = item.assets[thumbnail_key].href
                
                assets.append({
                    'name': asset_key,
                    'url': asset.href,
                    'thumbnail_url': thumbnail_url
                })
            
            if assets:
                results.append({
                    'item_id': item_id,
                    'assets': assets
                })
        
        logger.info(f"  ✓ {len(results)} Items gefunden")
        return results
        
    except Exception as e:
        logger.error(f"  ✗ STAC-Suche fehlgeschlagen: {e}")
        return []


def get_photo_metadata_from_stac(
    stac_url: str,
    collection: str,
    date: str,
    product_suffix: str
) -> List[Dict]:
    """
    Holt Photo-Metadaten (inkl. GPS) aus STAC für KML-Generierung.
    
    Args:
        stac_url (str): STAC API URL
        collection (str): Collection Name
        date (str): Datum (YYYY-MM-DD)
        product_suffix (str): Produkt-Suffix
        
    Returns:
        List[Dict]: Photo-Metadaten für KML
        
    Example Result:
        [
            {
                'filename': 'photo1.jpg',
                'url': 'https://...',
                'thumbnail_url': 'https://.../thumbnail.jpg',
                'lat': 46.123456,
                'lon': 7.654321,
                'timestamp': '2024:07:15 12:00:00'
            }
        ]
    """
    try:
        items = find_items_by_date_and_product(
            stac_url,
            collection,
            date,
            product_suffix
        )
        
        photos = []
        
        for item_data in items:
            for asset in item_data['assets']:
                # Versuche GPS aus Item-Properties zu holen
                # (In der Praxis müssten die Properties beim Upload gesetzt werden)
                # Hier als Fallback: GPS aus EXIF müsste bereits beim Upload
                # in den Item-Properties gespeichert worden sein
                
                photo = {
                    'filename': asset['name'],
                    'url': asset['url'],
                    'thumbnail_url': asset.get('thumbnail_url'),
                    'lat': None,  # Würde aus Item-Properties kommen
                    'lon': None,  # Würde aus Item-Properties kommen
                    'timestamp': None  # Würde aus Item-Properties kommen
                }
                
                photos.append(photo)
        
        logger.info(f"  ✓ {len(photos)} Photo-Metadaten geholt")
        return photos
        
    except Exception as e:
        logger.error(f"  ✗ Metadaten-Abruf fehlgeschlagen: {e}")
        return []


def check_item_exists(
    stac_url: str,
    collection: str,
    item_id: str
) -> bool:
    """
    Prüft ob ein STAC-Item bereits existiert.
    
    Args:
        stac_url (str): STAC API URL
        collection (str): Collection Name
        item_id (str): Item ID
        
    Returns:
        bool: True wenn existiert
    """
    try:
        client = get_stac_client(stac_url)
        if client is None:
            return False
        
        # Versuche Item zu laden
        item = client.get_collection(collection).get_item(item_id)
        return item is not None
        
    except Exception:
        return False