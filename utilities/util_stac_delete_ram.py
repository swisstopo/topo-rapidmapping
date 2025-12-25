"""
STAC Asset and Item Deletion Script - Spezialbefliegungen RAM Items

This script deletes RAM (Rapid Mapping) assets and items from the ch.swisstopo.spezialbefliegungen 
collection in a STAC API. It provides options to delete all RAM items or items from a specific date.

Author: David Oesch (adapted)
Date: 2025-12-24
License: MIT License

Usage:
    python util_stac_delete_ram.py

Features:
    - Targets only "ch.swisstopo.spezialbefliegungen" collection
    - Filters for items starting with "spezialbefliegungen_ram"
    - Option to delete all RAM items or filter by specific date
    - Lists all items/assets before deletion
    - Multiple confirmation steps for safety
    - Supports both INT and PROD environments

Dependencies:
    - requests
    - logging
    - json
"""

import requests
from typing import Dict, List, Optional
import logging
from urllib.parse import urljoin
import json
import sys
from pathlib import Path

# Add utilities to path if needed
try:
    from proxy_handler import initialize_proxy, get_session
    from credentials import load_stac_credentials
    PROXY_AVAILABLE = True
except ImportError:
    PROXY_AVAILABLE = False
    print("⚠ Warning: Proxy handler not available. Will use direct connection.")


def load_credentials_from_file(config_path: str) -> tuple:
    """
    Load FSDI credentials from config file
    
    Args:
        config_path (str): Path to the config file
        
    Returns:
        tuple: (username, password)
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return (config['FSDI']['username'], config['FSDI']['password'])
    except Exception as e:
        logging.error(f"Error loading credentials: {str(e)}")
        raise


def get_collection_items(base_url: str, collection_id: str, auth: tuple) -> List[Dict]:
    """
    Get all items from a collection using STAC API
    
    Args:
        base_url (str): Base URL of the STAC API
        collection_id (str): Collection ID
        auth (tuple): Authentication credentials
        
    Returns:
        List[Dict]: List of items
    """
    items_url = urljoin(base_url, f"collections/{collection_id}/items")
    
    try:
        if PROXY_AVAILABLE:
            session = get_session()
            response = session.get(items_url, auth=auth, params={"limit": 1000}, timeout=(30, 60))
        else:
            response = requests.get(items_url, auth=auth, params={"limit": 1000}, timeout=(30, 60))
        
        response.raise_for_status()
        data = response.json()
        return data.get('features', [])
    except requests.exceptions.Timeout as e:
        logging.error(f"Timeout fetching items from collection {collection_id}: {str(e)}")
        logging.error("Try increasing timeout or check network connection")
        raise
    except Exception as e:
        logging.error(f"Error fetching items from collection {collection_id}: {str(e)}")
        raise


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
            print(f"  ✓ Deleted asset: {asset_key}")
        else:
            print(f"  ✗ Failed to delete asset: {asset_key} (Status: {response.status_code})")
        return success
    except Exception as e:
        logging.error(f"Error deleting asset {asset_key} from item {item_id}: {str(e)}")
        print(f"  ✗ Error deleting asset: {asset_key} - {str(e)}")
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
            print(f"✓ Deleted item: {item_id}")
        else:
            print(f"✗ Failed to delete item: {item_id} (Status: {response.status_code})")
        return success
    except Exception as e:
        logging.error(f"Error deleting item {item_id}: {str(e)}")
        print(f"✗ Error deleting item: {item_id} - {str(e)}")
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
        
        print(f"\n{'='*70}")
        print(f"Processing item {idx}/{total_items}: {item_id}")
        print(f"{'='*70}")
        
        # Get all assets for this item
        asset_keys = get_item_assets(base_url, collection_id, item_id, auth)
        
        if not asset_keys:
            print(f"  ℹ No assets found for item {item_id}")
        
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
            logging.warning(f"Skipping item deletion for {item_id} due to failed asset deletions")
    
    return results


def main():
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    logger = logging.getLogger(__name__)
    
    print("="*70)
    print("STAC RAM ITEM DELETION TOOL")
    print("="*70)
    print()
    
    # ========================================================================
    # STEP 1: Choose Environment
    # ========================================================================
    print("Select environment:")
    print("  1) INT (sys-data.int.bgdi.ch)")
    print("  2) PROD (data.geo.admin.ch)")
    
    env_choice = input("\nEnter choice (1 or 2): ").strip()
    
    if env_choice == "1":
        environment = "INT"
        base_url = "https://sys-data.int.bgdi.ch/api/stac/v0.9/"
        hostname = "sys-data.int.bgdi.ch"
    elif env_choice == "2":
        environment = "PROD"
        base_url = "https://data.geo.admin.ch/api/stac/v0.9/"
        hostname = "data.geo.admin.ch"
    else:
        print("❌ Invalid choice. Exiting.")
        sys.exit(1)
    
    print(f"\n✓ Selected environment: {environment}")
    print(f"  URL: {base_url}")
    
    # ========================================================================
    # STEP 2: Initialize Proxy (if available)
    # ========================================================================
    if PROXY_AVAILABLE:
        print("\n" + "="*70)
        print("INITIALIZING PROXY")
        print("="*70)
        try:
            initialize_proxy()
        except Exception as e:
            print(f"⚠ Proxy initialization failed: {e}")
            print("  Continuing without proxy...")
    
    # ========================================================================
    # STEP 3: Load Credentials
    # ========================================================================
    print("\n" + "="*70)
    print("LOADING CREDENTIALS")
    print("="*70)
    
    try:
        if PROXY_AVAILABLE:
            username, password, _ = load_stac_credentials(environment=environment)
        else:
            # Fallback to manual config file
            config_path = Path("secrets") / "stac_credentials.json"
            with open(config_path, 'r') as f:
                config = json.load(f)
            env_config = config.get(environment, {})
            username = env_config.get('username')
            password = env_config.get('password')
        
        auth = (username, password)
        print(f"✓ Credentials loaded for {environment}")
    except Exception as e:
        print(f"❌ Error loading credentials: {e}")
        sys.exit(1)
    
    # ========================================================================
    # STEP 4: Specify Collection
    # ========================================================================
    collection_id = "ch.swisstopo.spezialbefliegungen"
    print(f"\n✓ Target collection: {collection_id}")
    
    # ========================================================================
    # STEP 5: Choose Deletion Mode
    # ========================================================================
    print("\n" + "="*70)
    print("DELETION MODE")
    print("="*70)
    print("Select what to delete:")
    print("  1) All RAM items (spezialbefliegungen_ram-*)")
    print("  2) RAM items from specific date (e.g., 2024-07-15)")
    
    mode_choice = input("\nEnter choice (1 or 2): ").strip()
    
    date_filter = None
    if mode_choice == "1":
        print("\n✓ Mode: Delete ALL RAM items")
    elif mode_choice == "2":
        date_filter = input("\nEnter date (YYYY-MM-DD, e.g., 2024-07-15): ").strip()
        print(f"\n✓ Mode: Delete RAM items from date: {date_filter}")
    else:
        print("❌ Invalid choice. Exiting.")
        sys.exit(1)
    
    # ========================================================================
    # STEP 6: Fetch and Filter Items
    # ========================================================================
    print("\n" + "="*70)
    print("FETCHING ITEMS")
    print("="*70)
    
    try:
        print(f"Querying collection: {collection_id}...")
        all_items = get_collection_items(base_url, collection_id, auth)
        print(f"✓ Found {len(all_items)} total items in collection")
        
        # Filter for RAM items
        filtered_items = filter_ram_items(all_items, date_filter)
        print(f"✓ Filtered to {len(filtered_items)} RAM items")
        
        if not filtered_items:
            print("\n⚠ No matching items found. Nothing to delete.")
            sys.exit(0)
    
    except Exception as e:
        print(f"❌ Error fetching items: {e}")
        sys.exit(1)
    
    # ========================================================================
    # STEP 7: List Items to be Deleted
    # ========================================================================
    print("\n" + "="*70)
    print("ITEMS TO BE DELETED")
    print("="*70)
    
    for idx, item in enumerate(filtered_items, 1):
        item_id = item.get('id')
        print(f"{idx:3d}. {item_id}")
    
    print(f"\nTotal items to delete: {len(filtered_items)}")
    
    # ========================================================================
    # STEP 8: First Confirmation
    # ========================================================================
    print("\n" + "="*70)
    print("⚠ WARNING: DELETION IS PERMANENT!")
    print("="*70)
    print(f"Environment: {environment}")
    print(f"Collection: {collection_id}")
    print(f"Items: {len(filtered_items)}")
    if date_filter:
        print(f"Date filter: {date_filter}")
    
    confirm1 = input('\nType "yes" to continue: ').strip().lower()
    if confirm1 != "yes":
        print("❌ Deletion cancelled.")
        sys.exit(0)
    
    # ========================================================================
    # STEP 9: Second Confirmation
    # ========================================================================
    print("\n" + "="*70)
    print("FINAL CONFIRMATION")
    print("="*70)
    print(f"You are about to DELETE {len(filtered_items)} items from {environment}!")
    
    confirm2 = input('\nType "I agree" to proceed with deletion: ').strip()
    if confirm2 != "I agree":
        print("❌ Deletion cancelled.")
        sys.exit(0)
    
    # ========================================================================
    # STEP 10: Execute Deletion
    # ========================================================================
    print("\n" + "="*70)
    print("🗑️  STARTING DELETION")
    print("="*70)
    
    try:
        results = delete_items_and_assets(base_url, collection_id, filtered_items, auth)
        
        # ====================================================================
        # STEP 11: Summary
        # ====================================================================
        print("\n" + "="*70)
        print("DELETION SUMMARY")
        print("="*70)
        print(f"✓ Successfully deleted assets: {len(results['successful_asset_deletions'])}")
        print(f"✗ Failed asset deletions: {len(results['failed_asset_deletions'])}")
        print(f"✓ Successfully deleted items: {len(results['successful_item_deletions'])}")
        print(f"✗ Failed item deletions: {len(results['failed_item_deletions'])}")
        
        if results['failed_asset_deletions']:
            print("\nFailed asset deletions:")
            for asset in results['failed_asset_deletions']:
                print(f"  - {asset}")
        
        if results['failed_item_deletions']:
            print("\nFailed item deletions:")
            for item in results['failed_item_deletions']:
                print(f"  - {item}")
        
        print("\n✓ Deletion process completed")
        
        return results
    
    except Exception as e:
        logger.error(f"Error during deletion: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    try:
        results = main()
        print("\nDone.")
    except KeyboardInterrupt:
        print("\n\n❌ Deletion cancelled by user (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)