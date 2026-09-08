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
    'quality': 85,
    'blocksize': 256,
    'bigtiff': 'YES',
    'num_threads': 'ALL_CPUS'
}

# Im GUI/CLI wählbare COMPRESS-Verfahren für die COG-Erzeugung.
COG_COMPRESS_OPTIONS = ['JPEG', 'LZW', 'DEFLATE', 'ZSTD', 'WEBP', 'NONE']

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
    QDOP_DMC4 = "qdop-dmc4"  # DMC4 4-Kanal Streifen → erzeugt RGB + NRG
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


def normalize_cli_timestamp(raw: str) -> str:
    """
    Normalisiert einen kompakten Zeitstempel auf das Standardformat
    YYYY-MM-DDthhmmss[cc].

    Args:
        raw (str): Roher CLI-Input, z.B. '20210729t125959' oder '20210729'

    Returns:
        str: Normalisierter Zeitstempel, z.B. '2021-07-29t125959'
    """
    # Bereits normalisiert, wenn Bindestriche vorhanden sind
    if '-' in raw:
        return raw
    # Match kompakt: YYYYMMDD[tHHMMSS[CC]]
    m = re.match(r'^(\d{4})(\d{2})(\d{2})(t\d{6}(\d{2})?)?$', raw)
    if m:
        date_part = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        time_part = m.group(4) or ''
        return date_part + time_part
    return raw  # unverändert zurückgeben; validate_timestamp weist es später ab


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
    # Accept 6-digit (hhmmss) or 8-digit (hhmmsscc) time parts
    pattern = r'^\d{4}-\d{2}-\d{2}t\d{6}(\d{2})?$'

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


def ensure_hundredths_suffix(timestamp: str) -> str:
    """
    Ensures timestamp has 2-digit hundredths-of-seconds suffix.
    "2024-07-15t143000"     ->  "2024-07-15t14300000"
    "2024-07-15t14300000"   ->  "2024-07-15t14300000"  (unchanged)
    """
    import re as _re
    if _re.match(r'^\d{4}-\d{2}-\d{2}t\d{6}$', timestamp):
        return timestamp + "00"
    return timestamp


def generate_item_name(timestamp: str, product_type: ProductType) -> str:
    """
    Generiert STAC Item Name: ram-YYYY-MM-DDthhmmsscc.

    Alle Produkttypen verwenden das gleiche Format ohne Produktsuffix.
    Das Produktsuffix erscheint nur im Asset-Namen (generate_asset_name).

    Args:
        timestamp (str): Zeitstempel (YYYY-MM-DDthhmmss oder YYYY-MM-DDthhmmsscc)
        product_type (ProductType): Produkttyp (unbenutzt, für API-Kompatibilität)

    Returns:
        str: Item Name (lowercase), z.B. 'ram-2024-07-15t14300000'

    Examples:
        >>> generate_item_name("2024-07-15t143000", ProductType.QDOP_RGB)
        'ram-2024-07-15t14300000'
        >>> generate_item_name("2024-07-15t14300000", ProductType.EBN)
        'ram-2024-07-15t14300000'
        >>> generate_item_name("2024-07-15t14300000", ProductType.EBO)
        'ram-2024-07-15t14300000'
    """
    ts = ensure_hundredths_suffix(timestamp).lower()
    return f"{PREFIX}-{ts}"


def generate_asset_name(timestamp: str, product_type: ProductType) -> str:
    """
    Generiert STAC Asset Name (Dateiname) mit Hundertelsekunden-Suffix.

    Format: ram-YYYY-MM-DDthhmmsscc-{suffix}.ext
    Beispiele:
      ram-2024-07-15t14300000-qdop-rgb-mosaic.tif
      ram-2024-07-15t14300000-qdop-nrg-mosaic.tif
      ram-2024-07-15t14300000-ebn-photo.jpg

    Args:
        timestamp (str): Zeitstempel (YYYY-MM-DDthhmmss oder YYYY-MM-DDthhmmsscc)
        product_type (ProductType): Produkttyp

    Returns:
        str: Asset Name (mit Extension)
    """
    ts = ensure_hundredths_suffix(timestamp).lower()
    config = get_product_config(product_type)
    return f"{PREFIX}-{ts}-{config['suffix']}{config['file_extension']}"


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