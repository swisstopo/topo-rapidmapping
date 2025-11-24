import os
import requests
import rasterio
from datetime import datetime
import pyproj
import re
import time
import main_multipart_upload_via_api


"""
Simplified STAC Publisher - publish geospatial data to FSDI using direct parameters.
No configuration file needed - all settings passed as parameters.
"""

# Multipart upload settings
part_size_mb = 100
attempts = 5

# Define coordinate systems
lv95 = pyproj.CRS.from_epsg(2056)  # LV95 EPSG code
wgs84 = pyproj.CRS.from_epsg(4326)  # WGS84 EPSG code
transformer_lv95_to_wgs84 = pyproj.Transformer.from_crs(lv95, wgs84, always_xy=True)


def is_existing(stac_item_path):
    """Check if a STAC item exists."""
    response = requests.get(url=stac_item_path)
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
        response = requests.put(
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
    if asset_title is not None:
        title = asset_title
    else:
        title = asset_create_title(id, current)

    if asset_type == "TIF":
        with rasterio.open(id) as src:
            original_res_x = abs(src.transform[0])
            original_res_y = abs(src.transform[4])
            gsd = int(max(original_res_x, original_res_y))

        payload = {
            "id": id,
            "title": title,
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "proj:epsg": 2056,
            "eo:gsd": int(gsd)
        }
    elif asset_type == "JSON":
        payload = {"id": id, "title": title, "type": "application/json"}
    elif asset_type == "GEOJSON":
        payload = {"id": id, "title": title, "type": "application/geo+json"}
    elif asset_type == "CSV":
        payload = {"id": id, "title": title, "type": "text/csv"}
    elif asset_type == "PARQUET":
        payload = {"id": id, "title": title, "type": "application/vnd.apache.parquet"}
    else:
        payload = {"id": id, "title": title, "type": "image/jpeg"}

    return payload


def create_asset(stac_asset_url, payload, username, password):
    """Create a STAC asset with retry logic."""
    max_retries = 3
    delay = 20

    for attempt in range(max_retries):
        try:
            response = requests.put(
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
    raw_asset = asset
    raw_item = item_name

    item = raw_item.lower()
    asset_lower = raw_asset.lower()

    # Rename asset temporarily
    os.rename(raw_asset, asset_lower)
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
                with rasterio.open(asset) as ds:
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
                    item_title, geocat_id, current, stac_hostname,asset
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
        payload = asset_create_json_payload(asset, asset_type, current, asset_title=asset_title)

        # Create Asset
        if not create_asset(stac_path + asset_path, payload, username, password):
            print(f"ASSET object {asset}: creation FAILED")
            return False

        # Determine environment
        env = "int" if ".int." in stac_hostname else "prod"

        # Upload ASSET
        if not main_multipart_upload_via_api.multipart_upload(
            env, collection, item, asset, asset,
            username, password, force=True, verbose=False
        ):
            print(f"ASSET object {asset}: upload FAILED")
            return False

        print(f"FSDI update done: {stac_scheme}://{stac_hostname}/{collection}/{item}/{asset}")
        return True

    finally:
        # Rename back to original name
        if os.path.exists(asset):
            os.rename(asset, raw_asset)


# CLI Interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description='Publish geospatial assets to FSDI STAC catalog',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python util_publish_stac_fsdi.py -u myuser -p mypass -a file.tif -i 2024-01-15T120000 -c ch.swisstopo.product -g geocat-id -H data.geo.admin.ch

  # With custom asset title
  python util_publish_stac_fsdi.py -u myuser -p mypass -a file.tif -i 2024-01-15T120000 -c ch.swisstopo.product -g geocat-id -H data.int.bgdi.ch -t "My Custom Title"

  # Using environment variables for credentials
  python util_publish_stac_fsdi.py -a file.tif -i 2024-01-15T120000 -c ch.swisstopo.product -g geocat-id -H data.geo.admin.ch
        """
    )

    parser.add_argument('-u', '--username',
                        default='user',
                        help='STAC API username (or set STAC_USERNAME env var) [default: user]')
    parser.add_argument('-p', '--password',
                        default='password',
                        help='STAC API password (or set STAC_PASSWORD env var) [default: pw]')
    parser.add_argument('-a', '--asset',
                        default='ram-2025-05-19t1211500-qdop-rgb-mosaic.tif',
                        help='Path to asset file (default: ram-2025-05-19t1211500-qdop-rgb-mosaic.tif)')
    parser.add_argument('-i', '--item-name',
                        default='2025-05-19t12115',
                        help='Item name in format YYYY-MM-DDTHHMMSS (default: 2025-05-19t12115)')
    parser.add_argument('-c', '--collection',
                        default='ch.swisstopo.spezialbefliegungen',
                        help='Collection name (default: ch.swisstopo.spezialbefliegungen)')
    parser.add_argument('-g', '--geocat-id',
                        default='1d0fc41e-9526-41ef-bdcf-94ed7626abbd',
                        help='Geocat ID (default: 1d0fc41e-9526-41ef-bdcf-94ed7626abbd)')
    parser.add_argument('-H', '--hostname',
                        default='sys-data.int.bgdi.ch',
                        help='STAC hostname (default: sys-data.int.bgdi.ch)')
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

    # Get credentials from args or environment variables
    username = args.username or os.environ.get('STAC_USERNAME')
    password = args.password or os.environ.get('STAC_PASSWORD')

    if not username or not password:
        parser.error('Username and password required (via args or STAC_USERNAME/STAC_PASSWORD env vars)')

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
