"""
STAC Asset and Item Deletion - Spezialbefliegungen RAM Items

Löscht RAM (Rapid Mapping) Assets und Items aus der Collection
ch.swisstopo.spezialbefliegungen. Drei Varianten:

    1) asset - EIN Asset      z.B. ram-2017-08-25t10092400-ebn-photo.jpg
    2) item  - EIN Item inkl. aller Assets   z.B. 2017-08-25t10092400
    3) date  - ALLE Items eines Datums       z.B. 2024-07-15

Verwendung:
    - Als erweiterte Option in rapidmapping_processor.py (Dialog oder CLI):
          rapidmapping_processor.exe --delete item --target 2017-08-25t10092400
    - Weiterhin eigenständig startbar (Dialog):
          python utilities/util_stac_delete_ram.py

Sicherheit:
    - Vor dem Löschen wird angezeigt, was gelöscht wird.
    - Zwei Bestätigungen: "yes" und danach "I agree". Alles andere bricht ab.
    - Gelöscht wird nur in Items, die mit "ram-" (bzw. "spezialbefliegungen_ram")
      beginnen.

Author: David Oesch (adapted)
Date: 2025-12-24
License: MIT License
"""

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

# Repo-Root in den Suchpfad, damit "configuration" und "utilities.*" auch beim
# eigenständigen Start (python utilities/util_stac_delete_ram.py) gefunden werden
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from configuration import (
    STAC_COLLECTION,
    STAC_SCHEME,
    STAC_API_PATH,
    ensure_hundredths_suffix,
    validate_timestamp,
)

try:
    from utilities.proxy_handler import initialize_proxy, get_session
    from utilities.credentials import load_stac_credentials
    PROXY_AVAILABLE = True
except ImportError:
    PROXY_AVAILABLE = False
    print("! Warning: Proxy handler not available. Will use direct connection.")

logger = logging.getLogger(__name__)

# Erlaubte Löschvarianten (Wert von --delete)
DELETE_MODES = ('asset', 'item', 'date')


def load_credentials_from_file(config_path: str) -> tuple:
    """
    Load FSDI credentials from config file

    Args:
        config_path (str): Path to the config file

    Returns:
        tuple: (username, password)
    """
    import json
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return (config['FSDI']['username'], config['FSDI']['password'])
    except Exception as e:
        logging.error(f"Error loading credentials: {str(e)}")
        raise


def get_collection_items(base_url: str, collection_id: str, auth: tuple) -> List[Dict]:
    """ Holt ALLE Items einer Collection unter Berücksichtigung der Paginierung """
    all_items = []
    items_url = urljoin(base_url, f"collections/{collection_id}/items")

    # Start-Parameter
    params = {"limit": 1000}

    while items_url:
        try:
            if PROXY_AVAILABLE:
                session = get_session()
                response = session.get(items_url, auth=auth, params=params, timeout=(30, 60))
            else:
                response = requests.get(items_url, auth=auth, params=params, timeout=(30, 60))

            response.raise_for_status()
            data = response.json()

            # Features zur Liste hinzufügen
            features = data.get('features', [])
            all_items.extend(features)

            # Paginierung: Suche nach dem 'next' Link
            next_link = next((link for link in data.get('links', []) if link.get('rel') == 'next'), None)

            if next_link:
                items_url = next_link.get('href')
                # Bei Folgerequests sind die Parameter oft schon in der URL enthalten
                params = None
                logging.info(f"Lade nächste Seite... (Bisher gefunden: {len(all_items)})")
            else:
                items_url = None

        except Exception as e:
            logging.error(f"Fehler beim Abrufen der Items: {str(e)}")
            raise

    return all_items


def filter_ram_items(items: List[Dict], date_filter: Optional[str] = None) -> List[Dict]:
    """
    Filter items that start with 'spezialbefliegungen_ram' and optionally by date

    Args:
        items (List[Dict]): List of all items
        date_filter (Optional[str]): Date filter in format YYYY-MM-DD (e.g., "2024-07-15")

    Returns:
        List[Dict]: Filtered list of RAM items
    """
    filtered = []

    for item in items:
        item_id = item.get('id', '')

        # Check if item starts with 'spezialbefliegungen_ram' or 'ram-'
        if not (item_id.startswith('spezialbefliegungen_ram') or item_id.startswith('ram-')):
            continue

        # If date filter specified, check if item matches the date
        if date_filter:
            # Extract date from item ID (format: ram-YYYY-MM-DDt...)
            # or spezialbefliegungen_ram-YYYY-MM-DDt...
            if date_filter not in item_id:
                continue

        filtered.append(item)

    return filtered


def get_item_assets(base_url: str, collection_id: str, item_id: str, auth: tuple) -> List[str]:
    """
    Get all asset keys for a specific item

    Args:
        base_url (str): Base URL of the STAC API
        collection_id (str): Collection ID
        item_id (str): Item ID
        auth (tuple): Authentication credentials

    Returns:
        List[str]: List of asset keys
    """
    item_url = urljoin(base_url, f"collections/{collection_id}/items/{item_id}")

    try:
        if PROXY_AVAILABLE:
            session = get_session()
            response = session.get(item_url, auth=auth, timeout=(30, 60))
        else:
            response = requests.get(item_url, auth=auth, timeout=(30, 60))

        response.raise_for_status()
        data = response.json()
        return list(data.get('assets', {}).keys())
    except Exception as e:
        logging.error(f"Error fetching assets for item {item_id}: {str(e)}")
        return []


def get_item(base_url: str, collection_id: str, item_id: str, auth: tuple) -> Optional[Dict]:
    """
    Holt ein einzelnes Item.

    Returns:
        Dict mit dem Item, oder None wenn es nicht existiert (HTTP 404).
        Andere Fehler (Netzwerk, 401, 500 ...) werden als Exception weitergegeben,
        damit "nicht vorhanden" nicht mit "nicht erreichbar" verwechselt wird.
    """
    item_url = urljoin(base_url, f"collections/{collection_id}/items/{item_id}")
    if PROXY_AVAILABLE:
        response = get_session().get(item_url, auth=auth, timeout=(30, 60))
    else:
        response = requests.get(item_url, auth=auth, timeout=(30, 60))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def delete_asset(base_url: str, collection_id: str, item_id: str, asset_key: str, auth: tuple) -> bool:
    """
    Delete a specific asset from an item

    Args:
        base_url (str): Base URL of the STAC API
        collection_id (str): Collection ID
        item_id (str): Item ID
        asset_key (str): Asset key to delete
        auth (tuple): Authentication credentials

    Returns:
        bool: True if deletion was successful, False otherwise
    """
    delete_url = urljoin(base_url, f"collections/{collection_id}/items/{item_id}/assets/{asset_key}")

    try:
        if PROXY_AVAILABLE:
            session = get_session()
            response = session.delete(delete_url, auth=auth, timeout=(30, 60))
        else:
            response = requests.delete(delete_url, auth=auth, timeout=(30, 60))

        success = response.status_code in [200, 204]
        if success:
            logger.info(f"  ✓ Asset gelöscht: {asset_key}")
        else:
            logger.error(f"  ✗ Asset NICHT gelöscht: {asset_key} (HTTP-Status {response.status_code})")
        return success
    except Exception as e:
        logger.error(f"  ✗ Fehler beim Löschen von Asset {asset_key} (Item {item_id}): {str(e)}")
        return False


def delete_item(base_url: str, collection_id: str, item_id: str, auth: tuple) -> bool:
    """
    Delete a specific item from a collection

    Args:
        base_url (str): Base URL of the STAC API
        collection_id (str): Collection ID
        item_id (str): Item ID
        auth (tuple): Authentication credentials

    Returns:
        bool: True if deletion was successful, False otherwise
    """
    delete_url = urljoin(base_url, f"collections/{collection_id}/items/{item_id}")

    try:
        if PROXY_AVAILABLE:
            session = get_session()
            response = session.delete(delete_url, auth=auth, timeout=(30, 60))
        else:
            response = requests.delete(delete_url, auth=auth, timeout=(30, 60))

        success = response.status_code in [200, 204]
        if success:
            logger.info(f"✓ Item gelöscht: {item_id}")
        else:
            logger.error(f"✗ Item NICHT gelöscht: {item_id} (HTTP-Status {response.status_code})")
        return success
    except Exception as e:
        logger.error(f"✗ Fehler beim Löschen von Item {item_id}: {str(e)}")
        return False


def delete_items_and_assets(base_url: str, collection_id: str, items: List[Dict], auth: tuple) -> Dict[str, List[str]]:
    """
    Delete all assets and items in the correct order

    Args:
        base_url (str): Base URL of the STAC API
        collection_id (str): Collection ID
        items (List[Dict]): List of items to delete
        auth (tuple): Authentication credentials

    Returns:
        Dict[str, List[str]]: Summary of successful and failed deletions
    """
    results = {
        'successful_asset_deletions': [],
        'failed_asset_deletions': [],
        'successful_item_deletions': [],
        'failed_item_deletions': []
    }

    total_items = len(items)

    for idx, item in enumerate(items, 1):
        item_id = item.get('id')

        logger.info("=" * 70)
        logger.info(f"Item {idx}/{total_items}: {item_id}")
        logger.info("=" * 70)

        # Get all assets for this item
        asset_keys = get_item_assets(base_url, collection_id, item_id, auth)

        if not asset_keys:
            logger.info(f"  ℹ Keine Assets gefunden für Item {item_id}")

        # First delete all assets for this item
        all_assets_deleted = True
        for asset_key in asset_keys:
            success = delete_asset(base_url, collection_id, item_id, asset_key, auth)
            if success:
                results['successful_asset_deletions'].append(f"{item_id}/{asset_key}")
            else:
                results['failed_asset_deletions'].append(f"{item_id}/{asset_key}")
                all_assets_deleted = False

        # Only delete the item if all its assets were successfully deleted
        if all_assets_deleted or not asset_keys:
            success = delete_item(base_url, collection_id, item_id, auth)
            if success:
                results['successful_item_deletions'].append(item_id)
            else:
                results['failed_item_deletions'].append(item_id)
        else:
            results['failed_item_deletions'].append(item_id)
            logger.warning(f"Item {item_id} wird nicht gelöscht, weil nicht alle Assets gelöscht werden konnten")

    return results


# ============================================================================
# Ziel prüfen / normalisieren
# ============================================================================

def normalize_delete_target(mode: str, target: str) -> str:
    """
    Prüft und normalisiert das Löschziel je nach Variante.

    asset: 'ram-2017-08-25t10092400-ebn-photo.jpg' -> unverändert (Kleinschreibung).
           Ohne 'ram-' wird ergänzt; 'ebn-photo-jpg' wird zu 'ebn-photo.jpg' korrigiert.
    item:  '2017-08-25t10092400' oder 'ram-2017-08-25t10092400' -> 'ram-2017-08-25t10092400'
           (6-stellige Uhrzeit bekommt das Hundertstel-Suffix '00').
    date:  '2024-07-15' -> unverändert.

    Raises:
        ValueError: mit verständlicher Meldung, wenn das Ziel nicht passt.
    """
    if mode not in DELETE_MODES:
        raise ValueError(f"Unbekannte Löschvariante '{mode}'. Erlaubt: {', '.join(DELETE_MODES)}.")

    t = (target or '').strip().strip('"').strip("'").lower()
    if not t:
        raise ValueError("Kein Ziel angegeben. Bitte Asset-Name, Item-ID oder Datum angeben.")

    if mode == 'date':
        try:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', t):
                raise ValueError
            datetime.strptime(t, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Datum '{target}' ist ungültig. Erwartet: YYYY-MM-DD, z.B. 2024-07-15.")
        return t

    if mode == 'item':
        ts = t[4:] if t.startswith('ram-') else t
        if not validate_timestamp(ts):
            raise ValueError(
                f"Item '{target}' ist ungültig. Erwartet: YYYY-MM-DDthhmmss[cc], "
                f"z.B. 2017-08-25t10092400 (mit oder ohne 'ram-' davor)."
            )
        return f"ram-{ensure_hundredths_suffix(ts)}"

    # mode == 'asset'
    m = re.match(r'^(?:ram-)?(\d{4}-\d{2}-\d{2}t\d{8})-(.+)$', t)
    if not m:
        raise ValueError(
            f"Asset '{target}' ist ungültig. Erwartet z.B. ram-2017-08-25t10092400-ebn-photo.jpg "
            f"(Thumbnails gehören zum Item: dafür die Variante 'Item' verwenden)."
        )
    rest = m.group(2)
    # Tolerant: 'ebn-photo-jpg' -> 'ebn-photo.jpg'
    if '.' not in rest:
        rest = re.sub(r'-(jpe?g|tiff?|kml|txt)$', r'.\1', rest)
    return f"ram-{m.group(1)}-{rest}"


def item_id_from_asset_name(asset_name: str) -> str:
    """'ram-2017-08-25t10092400-ebn-photo.jpg' -> 'ram-2017-08-25t10092400'"""
    return re.match(r'^(ram-\d{4}-\d{2}-\d{2}t\d{8})-', asset_name).group(1)


def list_ram_item_ids_for_date(hostname: str, auth: tuple, date: str) -> List[str]:
    """
    Listet die Item-IDs aller RAM-Items eines Tages (nur lesend).
    Wird vom Dialog genutzt, um vor der Verarbeitung auf bestehende Items hinzuweisen.
    """
    base_url = f"{STAC_SCHEME}://{hostname}{STAC_API_PATH}"
    items = filter_ram_items(get_collection_items(base_url, STAC_COLLECTION, auth), date)
    return sorted(i.get('id', '') for i in items)


# ============================================================================
# Dialog
# ============================================================================

def prompt_delete_mode_and_target() -> Tuple[Optional[str], Optional[str]]:
    """
    Fragt Löschvariante und Ziel im Dialog ab.

    Returns:
        (mode, target) mit bereits normalisiertem Ziel, oder (None, None) bei Abbruch (Enter).
    """
    print("\n Was soll gelöscht werden?")
    print("   1) EIN Asset            (z.B. ram-2017-08-25t10092400-ebn-photo.jpg)")
    print("   2) EIN Item inkl. aller Assets   (z.B. 2017-08-25t10092400)")
    print("   3) ALLE Items eines Datums       (z.B. 2024-07-15)")
    print("   [Enter = abbrechen]")

    modes = {'1': 'asset', '2': 'item', '3': 'date'}
    while True:
        choice = input("-> ").strip()
        if choice == '':
            return None, None
        if choice in modes:
            mode = modes[choice]
            break
        print(" Ungültige Eingabe. Bitte 1, 2 oder 3 eingeben (Enter = abbrechen).")

    hints = {
        'asset': "Asset-Name, z.B. ram-2017-08-25t10092400-ebn-photo.jpg",
        'item':  "Item, z.B. 2017-08-25t10092400",
        'date':  "Datum, z.B. 2024-07-15",
    }
    while True:
        raw = input(f"\n {hints[mode]}  [Enter = abbrechen]\n-> ").strip()
        if raw == '':
            return None, None
        try:
            return mode, normalize_delete_target(mode, raw)
        except ValueError as e:
            print(f" ✗ {e}")


def _confirm_twice() -> bool:
    """Zwei Bestätigungen: 'yes' und danach 'I agree'. Alles andere = Abbruch."""
    try:
        first = input('\nZum Fortfahren "yes" eintippen: ').strip().lower()
        if first != "yes":
            logger.info("Abbruch: nichts wurde gelöscht.")
            return False
        second = input('Endgültige Bestätigung: bitte "I agree" eintippen: ').strip()
        if second != "I agree":
            logger.info("Abbruch: nichts wurde gelöscht.")
            return False
    except EOFError:
        logger.error("✗ Keine Eingabe möglich (kein Terminal). Abbruch: nichts wurde gelöscht.")
        return False
    return True


# ============================================================================
# Ablauf
# ============================================================================

def run_delete(mode: str, target: str, environment: str, hostname: str, auth: tuple) -> bool:
    """
    Führt eine Löschung komplett aus: Ziel prüfen, anzeigen, 2x bestätigen, löschen.

    Args:
        mode (str): 'asset', 'item' oder 'date'
        target (str): Asset-Name, Item-ID oder Datum (wird normalisiert)
        environment (str): 'INT' oder 'PROD' (nur für die Anzeige)
        hostname (str): STAC-Hostname der Umgebung
        auth (tuple): (username, password)

    Returns:
        bool: True wenn alles Angezeigte gelöscht wurde. False bei Fehler oder Abbruch.
    """
    try:
        target = normalize_delete_target(mode, target)
    except ValueError as e:
        logger.error(f"✗ {e}")
        return False

    base_url = f"{STAC_SCHEME}://{hostname}{STAC_API_PATH}"
    collection_id = STAC_COLLECTION

    # --- 1. Was würde gelöscht? --------------------------------------------
    try:
        if mode == 'date':
            logger.info(f"Suche alle RAM-Items vom {target} ...")
            items = filter_ram_items(get_collection_items(base_url, collection_id, auth), target)
        else:
            item_id = target if mode == 'item' else item_id_from_asset_name(target)
            item = get_item(base_url, collection_id, item_id, auth)
            items = [item] if item else []
    except Exception as e:
        logger.error(f"✗ STAC-Abfrage fehlgeschlagen: {e}")
        logger.error("  Netzwerk/Proxy und Credentials prüfen. Es wurde nichts gelöscht.")
        return False

    if not items:
        what = f"Item '{item_id}'" if mode != 'date' else f"RAM-Items vom {target}"
        logger.error(f"✗ {what} nicht gefunden in {environment} ({hostname}). Es wurde nichts gelöscht.")
        return False

    if mode == 'asset':
        assets = items[0].get('assets', {})
        if target not in assets:
            logger.error(f"✗ Asset '{target}' existiert nicht im Item '{item_id}'. Es wurde nichts gelöscht.")
            if assets:
                logger.error("  Vorhandene Assets in diesem Item:")
                for key in assets:
                    logger.error(f"    - {key}")
            return False

    # --- 2. Anzeige ---------------------------------------------------------
    labels = {'asset': 'EIN ASSET', 'item': 'EIN ITEM inkl. aller Assets', 'date': f'ALLE ITEMS vom {target}'}
    print("\n" + "=" * 70)
    print(f" ! LÖSCHEN in {environment}  ({hostname})")
    print(f"   Collection: {collection_id}")
    print(f"   Variante:   {labels[mode]}")
    print("=" * 70)
    if mode == 'asset':
        print(f" Asset: {target}")
        print(f" Item:  {item_id}  (bleibt bestehen)")
    else:
        total_assets = 0
        for idx, it in enumerate(items, 1):
            keys = list(it.get('assets', {}).keys())
            total_assets += len(keys)
            print(f" {idx:3d}. {it.get('id')}  ({len(keys)} Assets)")
            if mode == 'item':
                for key in keys:
                    print(f"        - {key}")
        print(f"\n Total: {len(items)} Items, {total_assets} Assets")
    print("\n ! Gelöschte Daten können NICHT wiederhergestellt werden.")

    # --- 3. Bestätigen ------------------------------------------------------
    if not _confirm_twice():
        return False

    # --- 4. Löschen ---------------------------------------------------------
    logger.info("=" * 70)
    logger.info(f"LÖSCHEN GESTARTET ({environment})")
    logger.info("=" * 70)

    if mode == 'asset':
        ok = delete_asset(base_url, collection_id, item_id, target, auth)
        remaining = [k for k in items[0].get('assets', {}) if k != target]
        if ok and not remaining:
            logger.warning(
                f"! Item {item_id} hat jetzt keine Assets mehr und bleibt leer bestehen. "
                f"Zum Entfernen: Variante 'Item' (--delete item --target {item_id})."
            )
        logger.info("=" * 70)
        if ok:
            logger.info("✓ SUCCESS: Asset gelöscht")
        else:
            logger.error("✗ ERROR: Asset konnte nicht gelöscht werden (siehe oben)")
        return ok

    results = delete_items_and_assets(base_url, collection_id, items, auth)

    logger.info("=" * 70)
    logger.info("ZUSAMMENFASSUNG")
    logger.info("=" * 70)
    logger.info(f"✓ Assets gelöscht:     {len(results['successful_asset_deletions'])}")
    logger.info(f"✓ Items gelöscht:      {len(results['successful_item_deletions'])}")
    for asset in results['failed_asset_deletions']:
        logger.error(f"✗ Asset NICHT gelöscht: {asset}")
    for failed_item in results['failed_item_deletions']:
        logger.error(f"✗ Item NICHT gelöscht:  {failed_item}")

    failed = len(results['failed_asset_deletions']) + len(results['failed_item_deletions'])
    if failed:
        logger.error(f"✗ ERROR: {failed} Löschungen fehlgeschlagen (siehe oben)")
        return False
    logger.info("✓ SUCCESS: Alles Angezeigte wurde gelöscht")
    return True


def main():
    """Eigenständiger Dialog (ohne rapidmapping_processor.py)."""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    print("=" * 70)
    print("STAC RAM DELETION TOOL")
    print("=" * 70)

    if not PROXY_AVAILABLE:
        print("[FEHLER] utilities/credentials.py bzw. proxy_handler.py nicht gefunden.")
        return 1

    print("\nUmgebung wählen:")
    print("  1) INT  (Standard)")
    print("  2) PROD")
    env_choice = input("-> ").strip()
    if env_choice in ("", "1"):
        environment = "INT"
    elif env_choice == "2":
        environment = "PROD"
    else:
        print("[FEHLER] Ungültige Auswahl.")
        return 1

    try:
        username, password, hostname = load_stac_credentials(environment=environment)
        initialize_proxy()
    except Exception as e:
        print(f"[FEHLER] Credentials/Proxy: {e}")
        return 1

    mode, target = prompt_delete_mode_and_target()
    if mode is None:
        print("Abbruch.")
        return 0

    return 0 if run_delete(mode, target, environment, hostname, (username, password)) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[ABBRUCH] Löschen durch Benutzer abgebrochen (Ctrl+C)")
        sys.exit(1)
