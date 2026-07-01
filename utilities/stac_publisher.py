"""
STAC Publisher Integration.

Wrapper für util_publish_stac_fsdi.py Funktionalität.
Integriert Proxy-Konfiguration (aus proxy_handler.py) und Credentials-Management.

WICHTIG: Verwendet ausschließlich proxy_handler.py für Proxy-Verwaltung!
Die Proxy-Einstellungen wurden bereits in rapidmapping_processor.py mit
initialize_proxy() gesetzt und werden hier automatisch wiederverwendet.
"""

import logging
from pathlib import Path
from typing import Optional

# Import des bestehenden STAC-Publishers
# WICHTIG: util_publish_stac_fsdi.py muss im gleichen Verzeichnis oder in PYTHONPATH sein
try:
    from util_publish_stac_fsdi import publish_to_stac
except ImportError:
    # Fallback für relative Imports
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from util_publish_stac_fsdi import publish_to_stac

from utilities.credentials import load_stac_credentials
# WICHTIG: Verwende proxy_handler für alle Proxy-Operationen!
from utilities.proxy_handler import get_proxy_config, get_session

logger = logging.getLogger(__name__)


def publish_to_stac_wrapper(
    asset_path: Path,
    item_name: str,
    collection: str,
    geocat_id: str,
    hostname: str,
    asset_title: str = None,
    environment: str = "INT",
    current: str = None,
    scheme: str = "https",
    api_path: str = "/api/stac/v0.9/"
) -> bool:
    """
    Wrapper für publish_to_stac mit automatischem Credentials- und Proxy-Management.
    
    WICHTIG: Diese Funktion verwendet die Proxy-Einstellungen aus proxy_handler.py,
    die bereits in rapidmapping_processor.py mit initialize_proxy() gesetzt wurden.
    Es werden KEINE eigenen Proxy-Tests durchgeführt!
    
    Args:
        asset_path (Path): Pfad zur Asset-Datei
        item_name (str): Item Name (z.B. "ram-2024-07-15t143000-qdop-rgb-mosaic")
        collection (str): Collection Name (z.B. "ch.swisstopo.spezialbefliegungen")
        geocat_id (str): Geocat ID
        hostname (str): STAC Hostname (z.B. "sys-data.int.bgdi.ch")
        asset_title (str, optional): Custom Asset-Titel
        environment (str): "INT" oder "PROD" (default: "INT")
        current (str, optional): Current-Flag für spezielle Use Cases
        scheme (str): URL-Scheme (default: "https")
        api_path (str): API-Pfad (default: "/api/stac/v0.9/")
        
    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    try:
        logger.debug("=" * 70)
        logger.debug(f"STAC PUBLIKATION ({environment})")
        logger.debug("=" * 70)
        
        # ====================================================================
        # PROXY-KONFIGURATION AUS PROXY_HANDLER HOLEN
        # ====================================================================
        # Hole die bereits getesteten und konfigurierten Proxy-Einstellungen
        # Dies führt KEINE Tests durch, sondern verwendet nur gespeicherte Werte
        logger.debug("Hole Proxy-Konfiguration aus proxy_handler...")
        proxy_config = get_proxy_config()
        
        if proxy_config.get('enabled', False):
            logger.debug(f"  → Proxy aktiv: {proxy_config.get('active_proxy')}")
            logger.debug(f"  → SSL-Verifikation: {'Deaktiviert' if not proxy_config.get('verify_ssl') else 'Aktiviert'}")
        else:
            logger.debug(f"  → Kein Proxy (direkte Verbindung)")
        
        # ====================================================================
        # CREDENTIALS LADEN
        # ====================================================================
        logger.debug("Lade Credentials...")
        username, password, _ = load_stac_credentials(environment=environment)
        
        # ====================================================================
        # ASSET-DATEI VALIDIEREN
        # ====================================================================
        if not asset_path.exists():
            logger.error(f"✗ Asset-Datei nicht gefunden: {asset_path}")
            return False
        
        # ====================================================================
        # ZUSAMMENFASSUNG
        # ====================================================================
        logger.debug(f"Asset: {asset_path.name}")
        logger.debug(f"Item: {item_name}")
        logger.debug(f"Collection: {collection}")
        logger.debug(f"Hostname: {hostname}")
        if asset_title:
            logger.debug(f"Title: {asset_title}")
        logger.debug("=" * 70)
        
        # ====================================================================
        # STAC-PUBLIKATION
        # ====================================================================
        # util_publish_stac_fsdi.py verwendet intern get_session() aus proxy_handler,
        # daher müssen wir hier keine Session übergeben - sie wird automatisch 
        # mit den richtigen Proxy-Einstellungen verwendet
        # ====================================================================
        
        success = publish_to_stac(
            username=username,
            password=password,
            asset=str(asset_path),
            item_name=item_name,
            collection=collection,
            geocat_id=geocat_id,
            stac_hostname=hostname,
            stac_scheme=scheme,
            stac_api_path=api_path,
            asset_title=asset_title,
            current=current
        )
        
        # ====================================================================
        # ERGEBNIS
        # ====================================================================
        if success:
            logger.debug("=" * 70)
            logger.debug("✓ STAC-Publikation erfolgreich")
            logger.debug(f"URL: {scheme}://{hostname}/{collection}/{item_name}/{asset_path.name}")
            logger.debug("=" * 70)
        else:
            logger.error("=" * 70)
            logger.error("✗ STAC-Publikation fehlgeschlagen")
            logger.error("=" * 70)
        
        return success
        
    except Exception as e:
        logger.error(f"✗ Fehler in STAC-Publikation: {e}")
        logger.error(" Stacktrace für Debugging:")
        import traceback
        logger.error(traceback.format_exc())
        return False


def verify_stac_item_exists(
    hostname: str,
    collection: str,
    item_name: str,
    asset_name: str,
    scheme: str = "https"
) -> bool:
    """
    Überprüft ob ein STAC-Item/Asset bereits existiert.
    
    Verwendet die Session aus proxy_handler.py (mit bereits konfigurierten Proxies).
    
    Args:
        hostname (str): STAC Hostname
        collection (str): Collection Name
        item_name (str): Item Name
        asset_name (str): Asset Name
        scheme (str): URL-Scheme
        
    Returns:
        bool: True wenn existiert, False sonst
    """
    try:
        url = f"{scheme}://{hostname}/{collection}/{item_name}/{asset_name}"
        
        # Verwende Session aus proxy_handler (enthält Proxy-Konfiguration)
        session = get_session()
        response = session.get(url, timeout=10)
        
        exists = response.status_code == 200
        
        if exists:
            logger.debug(f"  ℹ Asset existiert bereits: {url}")
        else:
            logger.debug(f"  ℹ Asset existiert noch nicht")
        
        return exists
        
    except Exception as e:
        logger.warning(f" ! Konnte Existenz nicht prüfen: {e}")
        return False


def batch_publish_assets(
    assets: list,
    collection: str,
    geocat_id: str,
    hostname: str,
    **kwargs
) -> dict:
    """
    Publiziert mehrere Assets nacheinander.
    
    Verwendet die Proxy-Einstellungen aus proxy_handler.py für alle Uploads.
    
    Args:
        assets (list): Liste von Dictionaries mit Asset-Infos:
                      [{'path': Path, 'item_name': str, 'title': str}, ...]
        collection (str): Collection Name
        geocat_id (str): Geocat ID
        hostname (str): STAC Hostname
        **kwargs: Weitere Parameter für publish_to_stac_wrapper
        
    Returns:
        Dict[str, bool]: Dictionary mit Asset-Namen und Erfolgs-Status
    """
    results = {}
    total = len(assets)
    
    logger.debug(f"\nBatch-Upload: {total} Assets")
    logger.debug("=" * 70)
    
    # Zeige Proxy-Status einmal am Anfang
    proxy_config = get_proxy_config()
    if proxy_config.get('enabled', False):
        logger.debug(f"Verwende Proxy: {proxy_config.get('active_proxy')}")
    else:
        logger.debug("Verwende direkte Verbindung (kein Proxy)")
    logger.debug("=" * 70)
    
    for idx, asset_info in enumerate(assets, 1):
        asset_path = asset_info['path']
        item_name = asset_info['item_name']
        asset_title = asset_info.get('title')
        
        logger.debug(f"\n[{idx}/{total}] {asset_path.name}")
        
        # publish_to_stac_wrapper verwendet automatisch proxy_handler
        success = publish_to_stac_wrapper(
            asset_path=asset_path,
            item_name=item_name,
            collection=collection,
            geocat_id=geocat_id,
            hostname=hostname,
            asset_title=asset_title,
            **kwargs
        )
        
        results[asset_path.name] = success
        
        if not success:
            logger.error(f"  ✗ Upload fehlgeschlagen für {asset_path.name}")
    
    # Zusammenfassung
    successful = sum(1 for v in results.values() if v)
    failed = total - successful
    
    logger.debug("\n" + "=" * 70)
    logger.debug(f"Batch-Upload abgeschlossen: {successful}/{total} erfolgreich")
    if failed > 0:
        logger.warning(f" ! {failed} fehlgeschlagen")
    logger.debug("=" * 70)
    
    return results