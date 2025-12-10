import os
import requests
import rasterio
from datetime import datetime
import pyproj
import re
import time
import json
import logging
import main_multipart_upload_via_api


"""
Simplified STAC Publisher - publish geospatial data to FSDI using direct parameters.
Supports credentials from config file, environment variables, or command-line arguments.
Includes automatic proxy detection and configuration.
"""

# Multipart upload settings
part_size_mb = 100
attempts = 5

# Global proxy configuration
PROXY_CONFIG = {
    'enabled': False,
    'proxies': None,
    'session': None
}

# Define coordinate systems
lv95 = pyproj.CRS.from_epsg(2056)  # LV95 EPSG code
wgs84 = pyproj.CRS.from_epsg(4326)  # WGS84 EPSG code
transformer_lv95_to_wgs84 = pyproj.Transformer.from_crs(lv95, wgs84, always_xy=True)


def detect_proxy_requirement(test_url="https://data.geo.admin.ch/browser/index.html", timeout=5):
    """
    Detect if a proxy is required to access the internet.
    Tests direct connection first, then tries with proxy if direct fails.
    
    Args:
        test_url (str): URL to test connectivity
        timeout (int): Timeout in seconds for the test
    
    Returns:
        dict: Proxy configuration with 'enabled', 'proxies', and 'session' keys
    """
    proxy_url = "http://proxy-bvcol.admin.ch:8080"
    
    logging.info("Testing internet connectivity...")
    
    # Test 1: Direct connection (no proxy)
    try:
        response = requests.get(test_url, timeout=timeout)
        if response.status_code == 200:
            logging.info("✓ Direct internet access available (no proxy needed)")
            return {
                'enabled': False,
                'proxies': None,
                'session': requests.Session()
            }
    except (requests.exceptions.ConnectionError, 
            requests.exceptions.Timeout,
            requests.exceptions.RequestException) as e:
        logging.info(f"✗ Direct connection failed: {type(e).__name__}")
    
    # Test 2: Connection with proxy
    try:
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
        # Disable SSL warnings
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        response = requests.get(test_url, proxies=proxies, verify=False)
        if response.status_code == 200:
            logging.warning("⚠ Internet access via proxy (SSL verification disabled)")
            session = requests.Session()
            session.proxies = proxies
            session.verify = False  # Disable SSL verification
            return {
                'enabled': True,
                'proxies': proxies,
                'session': session,
                'verify_ssl': False  # Flag to indicate SSL is disabled
            }
    except (requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException) as e:
        logging.error(f"✗ Proxy connection withh SSL disabled also failed: {type(e).__name__}")
    
    # If both fail
    logging.error("✗ Cannot establish internet connection (tried direct and proxy)")
    raise ConnectionError(
        "Cannot access internet. Tried:\n"
        f"  1. Direct connection to {test_url}\n"
        f"  2. Connection via proxy {proxy_url}\n"
        "Please check your network settings."
    )


def get_session():
    """
    Get the configured requests session (with or without proxy).
    
    Returns:
        requests.Session: Configured session object
    """
    if PROXY_CONFIG['session'] is None:
        # Initialize if not already done
        config = detect_proxy_requirement()
        PROXY_CONFIG.update(config)
    
    return PROXY_CONFIG['session']


def load_credentials(config_path: str) -> tuple:
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


def get_credentials(args_username=None, args_password=None, config_path=None):
    """
    Get credentials from multiple sources with priority:
    1. Command-line arguments
    2. Environment variables
    3. Config file
    
    Args:
        args_username (str): Username from command-line args
        args_password (str): Password from command-line args
        config_path (str): Path to config file
    
    Returns:
        tuple: (username, password)
    """
    username = None
    password = None
    
    # Priority 1: Command-line arguments
    if args_username and args_password:
        username = args_username
        password = args_password
        logging.info("Using credentials from command-line arguments")
    
    # Priority 2: Environment variables
    elif os.environ.get('STAC_USERNAME') and os.environ.get('STAC_PASSWORD'):
        username = os.environ.get('STAC_USERNAME')
        password = os.environ.get('STAC_PASSWORD')
        logging.info("Using credentials from environment variables")
    
    # Priority 3: Config file
    elif config_path and os.path.exists(config_path):
        try:
            username, password = load_credentials(config_path)
            logging.info(f"Using credentials from config file: {config_path}")
        except Exception as e:
            logging.error(f"Failed to load credentials from config file: {e}")
    
    if not username or not password:
        raise ValueError(
            "Credentials not found. Please provide credentials via:\n"
            "  1. Command-line arguments (-u/--username and -p/--password)\n"
            "  2. Environment variables (STAC_USERNAME and STAC_PASSWORD)\n"
            "  3. Config file (--config-path or default: secrets/int_stac.json)"
        )
    
    return username, password


def is_existing(stac_item_path):
    """Check if a STAC item exists."""
    session = get_session()
    response = session.get(url=stac_item_path)
    return response.status_code // 200 == 1


def item_create_json_payload(id, coordinates, dt_iso8601, title, geocat_id, current, stac_hostname, asset):
    """Create JSON payload for a STAC item."""
    domain = f"https://{stac_hostname}/"

    pattern = r'_\d{4}-\d{2}-\d{2}t\d{5}$'

    # Remove the date pattern
    cleaned = re.sub(pattern, '', title)

    # Create the product name with prefix
    product = f'ch.swisstopo.{cleaned}'

    thumbnail_url = f"{domain}ch.swisstopo.{product}/{id}/thumbnail.jpg"

    payload = {
        "id": id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [coordinates],
        },
        "properties": {
            "datetime": dt_iso8601,
            "title": title
        },
        "links": [
            {
                "href": f"https://map.geo.admin.ch/#/map?layers=COG|{domain}{product}/{id}/{asset}",
                "rel": "visual"
            },
            {
                "href": thumbnail_url,
                "rel": "preview"
            }
        ]
    }
    return payload


def upload_item(item_path, item_payload, username, password):
    """Upload a STAC item."""
   
    try:
        session = get_session()
        response = session.put(
            url=item_path,
            json=item_payload,
            auth=(username, password)
        )

        if response.status_code // 200 == 1:
            return True
        else:
            print(response.json())
            return False
    except Exception as e:
        print(f"An error occurred in upload_item: {e}")
        return False


def asset_create_title(asset, current):
    """Create a title for a STAC asset."""
    if asset == "thumbnail.jpg":
        return "THUMBNAIL"

    if current is not None:
        match = re.search(r'current', asset)
    else:
        match = re.search(r'\d{4}-\d{2}-\d{2}t\d{6}', asset)

    underscore_pos = asset.find('_', match.end())
    text_after_date = asset[underscore_pos + 1:]
    filename_without_extension = text_after_date.rsplit('.', 1)[0]
    file_extension = os.path.splitext(asset)[1]

    if "warnregions" in filename_without_extension and file_extension.lower() in [".csv", ".geojson", ".parquet"]:
        filename_without_extension = filename_without_extension + "-" + file_extension.lstrip('.')

    return filename_without_extension.upper()


def asset_create_json_payload(id, asset_type, current, asset_title=None):
    """Create JSON payload for a STAC asset."""
    #if we have the asset stored in path remove the path
    id_no_path=os.path.basename(id)

    if asset_title is not None:
        title = asset_title
    else:
        title = asset_create_title(id_no_path, current)
   
    if asset_type == "TIF":
        with rasterio.open(id) as src:
            original_res_x = abs(src.transform[0])
            original_res_y = abs(src.transform[4])
            gsd = int(max(original_res_x, original_res_y))

        payload = {
            "id": id_no_path,
            "title": title,
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "proj:epsg": 2056,
            "eo:gsd": int(gsd)
        }
    elif asset_type == "JSON":
        payload = {"id": id_no_path, "title": title, "type": "application/json"}
    elif asset_type == "GEOJSON":
        payload = {"id": id_no_path, "title": title, "type": "application/geo+json"}
    elif asset_type == "CSV":
        payload = {"id": id_no_path, "title": title, "type": "text/csv"}
    elif asset_type == "PARQUET":
        payload = {"id": id_no_path, "title": title, "type": "application/vnd.apache.parquet"}
    else:
        payload = {"id": id_no_path, "title": title, "type": "image/jpeg"}

    return payload


def create_asset(stac_asset_url, payload, username, password):
    """Create a STAC asset with retry logic."""
    max_retries = 3
    delay = 20

    for attempt in range(max_retries):
        try:
            session = get_session()
            response = session.put(
                url=stac_asset_url,
                auth=(username, password),
                json=payload
            )

            if response.status_code in [200, 201]:
                try:
                    data = response.json()
                    return True
                except requests.exceptions.JSONDecodeError as e:
                    print(f"Error decoding JSON: {e}")
                    print(f"Response content: {response.text}")
            else:
                print(f"Attempt {attempt + 1}: Received status code {response.status_code}")
                print(f"Response content: {response.text}")
                if attempt < max_retries - 1:
                    print(f"Retrying in {delay} seconds...")
                    time.sleep(delay)

        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)

    print("Failed to receive a successful response after multiple attempts.")
    return False


def publish_to_stac(username, password, asset, item_name, collection, geocat_id,
                   stac_hostname, stac_scheme="https", stac_api_path="/api/stac/v0.9",
                   asset_title=None, current=None):
    """
    Publish a STAC asset with direct parameters.

    Args:
        username (str): STAC API username
        password (str): STAC API password
        asset (str): Path to the asset file
        item_name (str): Item name/identifier (format: YYYY-MM-DDTHHMMSS)
        collection (str): Collection name (e.g., 'ch.swisstopo.myproduct')
        geocat_id (str): Geocat ID
        stac_hostname (str): STAC server hostname (e.g., 'data.geo.admin.ch')
        stac_scheme (str, optional): URL scheme, default 'https'
        stac_api_path (str, optional): API path, default '/api/stac/v0.9'
        asset_title (str, optional): Custom title for the asset
        current (str, optional): If not None, indicates 'current' use case

    Returns:
        bool: True if successful, False otherwise
    """
    # Convert to lowercase as required by STAC FSDI
    orig_asset = asset 
    
    raw_asset_path = os.path.dirname(asset)
    raw_item = item_name

    item = raw_item.lower()
    asset_lower = os.path.basename(asset).lower()

    # Rename asset temporarily
    os.rename(asset, os.path.join(raw_asset_path,asset_lower))
    asset = asset_lower

  
    try:
        # Determine item title
        if current is not None:
            item_title = collection.replace('ch.swisstopo.', '')
            item = item_title
        else:
            item_title = collection.replace('ch.swisstopo.', '') + "_" + item

        # Build paths
        item_path = f'collections/{collection}/items/{item}'
        asset_path = f'collections/{collection}/items/{item}/assets/{asset}'
        stac_path = f"{stac_scheme}://{stac_hostname}{stac_api_path}"

        # Determine asset type
        extension = asset.split('.')[-1].lower()
        asset_type_map = {
            'csv': 'CSV',
            'json': 'JSON',
            'jpg': 'JPEG',
            'geojson': 'GEOJSON',
            'parquet': 'PARQUET',
            'tif': 'TIF',
            'tiff': 'TIF'
        }
        asset_type = asset_type_map.get(extension, 'TIF')

        # Create ITEM if needed
        try:
            if asset_type == 'TIF':
                print(f"ITEM object {item}: creating")

                # Get bounds from GeoTIFF
                with rasterio.open(os.path.join(raw_asset_path,asset)) as ds:
                    left, bottom, right, top = ds.bounds

                coordinates_lv95 = [
                    [left, bottom],
                    [right, bottom],
                    [right, top],
                    [left, top],
                    [left, bottom]
                ]

                coordinates_wgs84 = [
                    transformer_lv95_to_wgs84.transform(*coord)
                    for coord in coordinates_lv95
                ]

                # Convert datetime
                dt = datetime.strptime(raw_item, '%Y-%m-%dT%H%M%S')
                dt_iso8601 = dt.strftime('%Y-%m-%dT%H:%M:%SZ')

                # Create and upload item
                payload = item_create_json_payload(
                    item, coordinates_wgs84, dt_iso8601,
                    item_title, geocat_id, current, stac_hostname, asset
                )

                upload_item(stac_path + item_path, payload, username, password)

        except Exception as e:
            print(f"An error occurred creating object {item}: {e}")

        # Create ASSET
        if is_existing(f"{stac_scheme}://{stac_hostname}/{collection}/{item}/{asset}"):
            print(f"ASSET object {asset}: exists ... overwriting")
        else:
            print(f"ASSET object {asset}: does not exist preparing...")

        # Create asset payload
        payload = asset_create_json_payload(os.path.join(raw_asset_path,asset), asset_type, current, asset_title=asset_title)

        # Create Asset
        if not create_asset(stac_path + asset_path, payload, username, password):
            print(f"ASSET object {asset}: creation FAILED")
            return False

        # Determine environment
        env = "int" if ".int." in stac_hostname else "prod"

        # Upload ASSET with proxy configuration
        if not main_multipart_upload_via_api.multipart_upload(
            env, collection, item, asset, os.path.join(raw_asset_path,asset),
            username, password, force=True, verbose=False,
            proxy_config=PROXY_CONFIG  # Pass proxy config to multipart upload
        ):
            print(f"ASSET object {asset}: upload FAILED")
            return False

        print(f"FSDI update done: {stac_scheme}://{stac_hostname}/{collection}/{item}/{asset}")
        return True

    finally:
        # Rename back to original name
        if os.path.exists(os.path.join(raw_asset_path,asset_lower)):
            os.rename(os.path.join(raw_asset_path,asset_lower),orig_asset)


# CLI Interface
if __name__ == "__main__":
    import argparse

    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(
        description='Publish geospatial assets to FSDI STAC catalog',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using config file (default: secrets/int_stac.json)
  python util_publish_stac_fsdi.py -a file.tif -i 2024-01-15T120000 -c ch.swisstopo.product -g geocat-id -H data.geo.admin.ch

  # Using custom config file
  python util_publish_stac_fsdi.py --config-path secrets/prod_stac.json -a file.tif -i 2024-01-15T120000 -c ch.swisstopo.product -g geocat-id -H data.geo.admin.ch

  # Using environment variables
  export STAC_USERNAME=myuser
  export STAC_PASSWORD=mypass
  python util_publish_stac_fsdi.py -a file.tif -i 2024-01-15T120000 -c ch.swisstopo.product -g geocat-id -H data.geo.admin.ch

  # Using command-line arguments (overrides config and env vars)
  python util_publish_stac_fsdi.py -u myuser -p mypass -a file.tif -i 2024-01-15T120000 -c ch.swisstopo.product -g geocat-id -H data.int.bgdi.ch

  # With custom asset title
  python util_publish_stac_fsdi.py -a file.tif -i 2024-01-15T120000 -c ch.swisstopo.product -g geocat-id -H data.int.bgdi.ch -t "My Custom Title"

Credential Priority (highest to lowest):
  1. Command-line arguments (-u/--username and -p/--password)
  2. Environment variables (STAC_USERNAME and STAC_PASSWORD)
  3. Config file (--config-path or default: secrets/int_stac.json)
        """
    )

    # Credential options
    parser.add_argument('--config-path',
                        default=os.path.join('secrets', 'int_stac.json'),
                        help='Path to config file containing credentials (default: secrets/int_stac.json)')
    parser.add_argument('-u', '--username',
                        help='STAC API username (overrides config file and env vars)')
    parser.add_argument('-p', '--password',
                        help='STAC API password (overrides config file and env vars)')

    # Required parameters
    parser.add_argument('-a', '--asset',
                        default=r'C:\oed\temp\rm2021\ram-2021-07-23t120000-qdop-rgb-mosaic.tif',
                        help=r'Path to asset file (default: C:\oed\temp\rm2021\ram-2021-07-23t120000-qdop-rgb-mosaic.tif)')
    parser.add_argument('-i', '--item-name',
                        default='2021-07-23t120000',
                        help='Item name in format YYYY-MM-DDTHHMMSS (default: 2021-07-23t120000)')
    parser.add_argument('-c', '--collection',
                        default='ch.swisstopo.spezialbefliegungen',
                        help='Collection name (default: ch.swisstopo.spezialbefliegungen)')
    parser.add_argument('-g', '--geocat-id',
                        default='1d0fc41e-9526-41ef-bdcf-94ed7626abbd',
                        help='Geocat ID (default: 1d0fc41e-9526-41ef-bdcf-94ed7626abbd)')
    parser.add_argument('-H', '--hostname',
                        default='sys-data.int.bgdi.ch',
                        help='STAC hostname (default: sys-data.int.bgdi.ch)')

    # Optional parameters
    parser.add_argument('-s', '--scheme',
                        default='https',
                        help='URL scheme (default: https)')
    parser.add_argument('-P', '--api-path',
                        default='/api/stac/v0.9/',
                        help='API path (default: /api/stac/v0.9)')
    parser.add_argument('-t', '--asset-title',
                        default='QDOP',
                        help='Custom asset title (default: QDOP)')
    parser.add_argument('--current',
                        help='Current use case flag (optional)')

    args = parser.parse_args()

    try:
        # Initialize proxy detection FIRST
        logging.info("=" * 60)
        logging.info("INITIALIZING PROXY CONFIGURATION")
        logging.info("=" * 60)
        config = detect_proxy_requirement()
        PROXY_CONFIG.update(config)
        logging.info("=" * 60)
        
        # Get credentials using priority system
        username, password = get_credentials(
            args_username=args.username,
            args_password=args.password,
            config_path=args.config_path
        )

        # Call the function
        success = publish_to_stac(
            username=username,
            password=password,
            asset=args.asset,
            item_name=args.item_name,
            collection=args.collection,
            geocat_id=args.geocat_id,
            stac_hostname=args.hostname,
            stac_scheme=args.scheme,
            stac_api_path=args.api_path,
            asset_title=args.asset_title,
            current=args.current
        )

        exit(0 if success else 1)

    except ConnectionError as e:
        logging.error(f"Connection error: {str(e)}")
        exit(1)
    except ValueError as e:
        logging.error(str(e))
        exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        exit(1)