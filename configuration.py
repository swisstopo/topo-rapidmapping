"""
Konfigurationsmodul für Rapid Mapping Processor.

Enthält Produktdefinitionen, Namenskonventionen und Validierungsfunktionen.
"""

from enum import Enum
import re
from typing import Dict, Any

# STAC Konfiguration
STAC_COLLECTION = "ch.swisstopo.spezialbefliegungen"
GEOCAT_ID = "1d0fc41e-9526-41ef-bdcf-94ed7626abbd"
STAC_HOSTNAME = "sys-data.int.bgdi.ch"  # INT Environment
STAC_HOSTNAME_PROD = "data.geo.admin.ch"  # PROD Environment
STAC_SCHEME = "https"
STAC_API_PATH = "/api/stac/v0.9/"

# Collection Base URL
COLLECTION_BASE_URL = "https://data.geo.admin.ch/ch.swisstopo.rapidmapping/data/"

# Namenskonventionen
PREFIX = "ram"  # Rapid Mapping Prefix

# COG Creation Settings
COG_CONFIG = {
    'compress': 'JPEG',
    'quality': 75,
    'blocksize': 256,
    'bigtiff': 'YES',
    'num_threads': 'ALL_CPUS'
}

# Mosaic Creation Settings
MOSAIC_CONFIG = {
    'srs': 'EPSG:2056',  # LV95
    'resample': 'cubic',
    'compress': 'LZW',
    'tiled': 'YES',
    'bigtiff': 'YES',
    'warp_memory': '512',
    'num_threads': 'ALL_CPUS'
}

# Photo Processing Settings
THUMBNAIL_CONFIG = {
    'max_width': 640,
    'max_height': 480,
    'format': 'JPEG'
}


class ProductType(Enum):
    """Verfügbare Rapid Mapping Produkttypen."""
    QDOP_RGB = "qdop-rgb"
    QDOP_NRG = "qdop-nrg"
    EBN = "ebn"  # Einzelbilder Nadir
    EBO = "ebo"  # Einzelbilder Oblique


def get_product_config(product_type: ProductType) -> Dict[str, Any]:
    """
    Gibt die Konfiguration für einen Produkttyp zurück.
    
    Args:
        product_type (ProductType): Produkttyp
        
    Returns:
        Dict: Konfiguration mit Keys: suffix, asset_title, description, icon_url, icon_scale
    """
    configs = {
        ProductType.QDOP_RGB: {
            'suffix': 'qdop-rgb-mosaic',
            'asset_title': 'QDOP-RGB-MOSAIC',
            'description': 'Quick Digital Orthophoto RGB Mosaic',
            'file_extension': '.tif',
            'type': 'mosaic'
        },
        ProductType.QDOP_NRG: {
            'suffix': 'qdop-nrg-mosaic',
            'asset_title': 'QDOP-NRG-MOSAIC',
            'description': 'Quick Digital Orthophoto Near-Infrared Mosaic',
            'file_extension': '.tif',
            'type': 'mosaic'
        },
        ProductType.EBN: {
            'suffix': 'ebn-photo',
            'asset_title': 'EINZELBILDER-NADIR',
            'description': 'Einzelbilder Nadir (Senkrecht)',
            'icon_url': 'https://map.geo.admin.ch/api/icons/sets/default/icons/008-circle-stroked@1x-255,0,0.png',
            'icon_scale': 0.25,
            'file_extension': '.jpg',
            'type': 'photos'
        },
        ProductType.EBO: {
            'suffix': 'ebo-photo',
            'asset_title': 'EINZELBILDER-OBLIQUE',
            'description': 'Einzelbilder Oblique (Schrägaufnahmen)',
            'icon_url': 'https://map.geo.admin.ch/api/icons/sets/default/icons/100-camera@1x-127,0,255.png',
            'icon_scale': 0.75,
            'file_extension': '.jpg',
            'type': 'photos'
        }
    }
    
    return configs[product_type]


def validate_timestamp(timestamp: str) -> bool:
    """
    Validiert Zeitstempel im Format YYYY-MM-DDthhmmss.
    
    Args:
        timestamp (str): Zu validierender Zeitstempel
        
    Returns:
        bool: True wenn gültig, False sonst
        
    Examples:
        >>> validate_timestamp("2024-07-15t143000")
        True
        >>> validate_timestamp("2024-13-01t000000")
        False
    """
    pattern = r'^\d{4}-\d{2}-\d{2}t\d{6}$'
    
    if not re.match(pattern, timestamp):
        return False
    
    # Extrahiere Komponenten
    try:
        date_part, time_part = timestamp.split('t')
        year, month, day = map(int, date_part.split('-'))
        hour = int(time_part[0:2])
        minute = int(time_part[2:4])
        second = int(time_part[4:6])
        
        # Validiere Bereiche
        if not (1900 <= year <= 2100):
            return False
        if not (1 <= month <= 12):
            return False
        if not (1 <= day <= 31):
            return False
        if not (0 <= hour <= 23):
            return False
        if not (0 <= minute <= 59):
            return False
        if not (0 <= second <= 59):
            return False
        
        return True
        
    except (ValueError, IndexError):
        return False


def generate_item_name(timestamp: str, product_type: ProductType) -> str:
    """
    Generiert STAC Item Name.
    
    Format: ram-YYYY-MM-DDthhmmss-{product}
    Beispiel: ram-2024-07-15t143000-qdop-rgb
    
    Args:
        timestamp (str): Zeitstempel (YYYY-MM-DDthhmmss)
        product_type (ProductType): Produkttyp
        
    Returns:
        str: Item Name (lowercase)
        
    Examples:
        >>> generate_item_name("2024-07-15t143000", ProductType.QDOP_RGB)
        'ram-2024-07-15t143000-qdop-rgb'
        >>> generate_item_name("2024-07-15t143000", ProductType.EBN)
        'ram-2024-07-15t143000-ebn'
    """
    config = get_product_config(product_type)
    # Suffix enthält bereits den Typ (z.B. "qdop-rgb-mosaic", "ebn")
    # Für Item-Name: Nur Produkt ohne "-mosaic"
    product_name = config['suffix'].replace('-mosaic', '')
    return f"{PREFIX}-{timestamp.lower()}-{product_name}"


def generate_asset_name(timestamp: str, product_type: ProductType) -> str:
    """
    Generiert STAC Asset Name (Dateiname).
    
    Format: ram-YYYY-MM-DDthhmmss-{product}-{type}.ext
    Beispiel: ram-2024-07-15t143000-qdop-rgb-mosaic.tif
    
    Args:
        timestamp (str): Zeitstempel (YYYY-MM-DDthhmmss)
        product_type (ProductType): Produkttyp
        
    Returns:
        str: Asset Name (mit Extension)
        
    Examples:
        >>> generate_asset_name("2024-07-15t143000", ProductType.QDOP_RGB)
        'ram-2024-07-15t143000-qdop-rgb-mosaic.tif'
        >>> generate_asset_name("2024-07-15t143000", ProductType.EBN)
        'ram-2024-07-15t143000-ebn.jpg'
    """
    config = get_product_config(product_type)
    return f"{PREFIX}-{timestamp.lower()}-{config['suffix']}{config['file_extension']}"


def get_collection_url(item_name: str, hostname: str = None) -> str:
    """
    Generiert Collection-URL für ein Item.
    
    Args:
        item_name (str): STAC Item Name
        hostname (str, optional): STAC Hostname (default: STAC_HOSTNAME)
        
    Returns:
        str: Vollständige URL zur Collection
    """
    host = hostname or STAC_HOSTNAME
    return f"https://{STAC_HOSTNAME}/{STAC_COLLECTION}/{item_name}/"


def validate_item_name_format(item_name: str) -> bool:
    """
    Validiert Item Name Format für Einzelbilder (YYYY-###-CAPITALLETTERS).
    
    Nur relevant für alternative Namensschemas bei Einzelbildern.
    
    Args:
        item_name (str): Zu validierender Item Name
        
    Returns:
        bool: True wenn gültig, False sonst
        
    Examples:
        >>> validate_item_name_format("2024-001-WALLIS")
        True
        >>> validate_item_name_format("2024-1-wallis")
        False
    """
    pattern = r'^\d{4}-\d{3}-[A-Z]+$'
    return bool(re.fullmatch(pattern, item_name))


# Koordinatensystem-Definitionen (für EXIF-Verarbeitung)
LV95_EPSG = 2056
WGS84_EPSG = 4326