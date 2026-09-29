#!/usr/bin/env python3
"""
Script to upload large assets to STAC via the REST API

This script facilitates the upload of large asset files to a STAC (SpatioTemporal Asset Catalog) API
using multipart uploads. It supports various environments (localhost, dev, int, prod) and provides
options for customizing the upload process.

Key features:
- Multipart file upload to STAC API
- MD5 checksum generation for file parts
- Support for different environments
- Configurable part size
- Ability to force upload and abort existing uploads
- Verbose logging option
- Proxy support for corporate environments
- VPN-compatible SSL handling

Usage:
    python script_name.py <env> <collection> <item> <asset> <filepath> [options]

    env: Environment to be used (choices: localhost, dev, int, prod)
    collection: Name of the asset's collection
    item: Name of the asset's item
    asset: Name of the asset to be uploaded
    filepath: Local path of the asset file to be uploaded
    [options]
        --part-size: Size of the file parts in MB (default: 250 MB)
        --username: Username for authentication
        --password: Password for authentication
        -v, --verbose: Increase output verbosity
        --force: Cancel any existing upload before starting a new one

Dependencies:
    requests, multihash

Author: Unknown (based on geoadmin/bgdi-scripts, orginal  https://github.com/geoadmin/bgdi-scripts/blob/master/system-utilities/sys-data/py-scripts/multipart_upload_via_api.py)

changes to the original:
 - added def multipart_upload
 - added in def _create_multipart_upload(self) : "update_interval": 30
 - added proxy support via proxy_config parameter
 - added VPN-compatible SSL handling for S3 uploads

"""

import argparse
import hashlib
import io
import json
import os
import sys
from base64 import b64encode
from datetime import datetime
from hashlib import md5

import logging
import multihash
import requests
# retry and timeout support
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry  # pylint: disable=import-error

logger = logging.getLogger(__name__)

# Windows: ist stdout nicht an eine echte Konsole angehängt (z.B. Pipe/GUI-
# Subprocess), fällt Python auf die ANSI-Codepage zurück (meist cp1252), die
# die Fortschrittsbalken-Zeichen (█ ░ ✓ ...) unten in _generate_hashes() nicht
# kodieren kann -> UnicodeEncodeError, obwohl der Upload selbst erfolgreich war.
# TextIOWrapper.reconfigure() gibt es erst ab Python 3.7 — falls nicht
# vorhanden (Python 3.6), stdout/stderr manuell um den Rohbuffer neu wrappen.
for _name in ("stdout", "stderr"):
    _stream = getattr(sys, _name)
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
            continue
        except Exception:
            pass
    _buffer = getattr(_stream, "buffer", None)
    if _buffer is not None:
        try:
            setattr(sys, _name, io.TextIOWrapper(
                _buffer, encoding="utf-8", errors="replace", line_buffering=True
            ))
        except Exception:
            pass

# Lock: sys.argv is global — parallel workers must not mutate it simultaneously
import threading as _threading
_ARGV_LOCK = _threading.Lock()

# For large parts, it might help to increase the DEFAULT_TIMEOUT
DEFAULT_TIMEOUT = 180  # Increased from 60 to 180 seconds for VPN/large files
MAX_PARTS_NUMBER = 100
DEFAULT_PART_SIZE = 250  # MB

# Global session objects
http = None  # Main session for STAC API
s3_session = None  # Separate session for S3 uploads


class TimeoutHTTPAdapter(HTTPAdapter):
    '''Session-wide timeout for requests'''

    def __init__(self, *args, **kwargs):
        self.timeout = DEFAULT_TIMEOUT
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):  # pylint: disable=arguments-differ
        timeout = kwargs.get("timeout")
        if timeout is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


class HttpError(requests.exceptions.HTTPError):

    def __init__(self, response, message=None):
        msg = f'Error {response.status_code} for url "{response.url}"'
        try:
            msg += f' and response "{json.dumps(response.json()["description"])}"'
        except (requests.exceptions.JSONDecodeError, KeyError):
            pass  # Ignore if response if not json or if "description" does not exist
        if message:
            msg += f': {message}'
        super().__init__(msg, response=response)


def initialize_http_session(proxy_config=None):
    """
    Initialize the global HTTP sessions with retry logic and optional proxy support.
    Creates TWO separate sessions:
    1. http: For STAC API calls (with proxy if needed)
    2. s3_session: For S3 presigned URL uploads (direct connection, no proxy)
    
    Args:
        proxy_config (dict): Optional proxy configuration with 'proxies' and 'verify_ssl' keys
    """
    global http, s3_session
    
    # ===========================================================================
    # SESSION 1: STAC API (with proxy if configured)
    # ===========================================================================
    retries = Retry(
        total=3, 
        backoff_factor=1, 
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False  # Don't raise exception, let us handle it
    )
    adapter = TimeoutHTTPAdapter(max_retries=retries, timeout=DEFAULT_TIMEOUT)

    http = requests.Session()
    
    # Configure proxy if provided
    if proxy_config and proxy_config.get('enabled') and proxy_config.get('proxies'):
        http.proxies.update(proxy_config['proxies'])
        
        # Configure SSL verification
        if proxy_config.get('verify_ssl') is False:
            http.verify = False
            # Disable SSL warnings
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.debug(f"STAC API session: proxy (SSL disabled): {proxy_config['proxies'].get('https', proxy_config['proxies'].get('http'))}")
        else:
            http.verify = True
            logger.debug(f"✓ STAC API session: proxy {proxy_config['proxies'].get('https', proxy_config['proxies'].get('http'))}")
    else:
        http.verify = True
        logger.debug("✓ STAC API session: direct connection")
    
    http.mount("http://", adapter)
    http.mount("https://", adapter)
    
    # ===========================================================================
    # SESSION 2: S3 Upload (SAME PROXY as STAC API, SSL disabled)
    # ===========================================================================
    # CRITICAL INSIGHT: When on VPN, AWS S3 endpoints are BLOCKED by firewall
    # and MUST go through the corporate proxy. We cannot bypass the proxy.
    # However, we still disable SSL verification due to corporate certificates.
    
    s3_retries = Retry(
        total=5,  # More retries for S3 due to VPN issues
        backoff_factor=2,  # Exponential backoff
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    s3_adapter = TimeoutHTTPAdapter(max_retries=s3_retries, timeout=DEFAULT_TIMEOUT)
    
    s3_session = requests.Session()
    
    # CRITICAL: For VPN environments, S3 must use SAME proxy as STAC API
    # but with SSL disabled due to corporate SSL inspection
    if proxy_config and proxy_config.get('enabled'):
        # Use SAME proxy as STAC API - VPN blocks direct S3 access
        s3_session.proxies.update(proxy_config['proxies'])
        # Always disable SSL for S3 uploads in corporate environments
        s3_session.verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.debug(f"S3 session: proxy (SSL disabled): {proxy_config['proxies'].get('https', proxy_config['proxies'].get('http'))}")
    else:
        # No proxy = no corporate network = normal SSL verification, no proxy
        s3_session.verify = True
        s3_session.proxies = {}
        logger.debug("✓ S3 session: direct connection")
    
    s3_session.mount("http://", s3_adapter)
    s3_session.mount("https://", s3_adapter)


def b64_md5(data):
    '''Return the Base64 encoded MD5 digest of the given data

    Args:
        data: string
            input data

    Returns:
        string - base64 encoded MD5 digest of data
    '''
    return b64encode(md5(data).digest()).decode('utf-8')


def get_args():
    '''Returns parsed CLI arguments'''
    parser = argparse.ArgumentParser(
        description="Utility script for uploading large asset files as a multipart upload " \
            "using the STAC API."
    )
    parser.add_argument(
        "env",
        choices=['localhost', 'dev', 'int', 'prod'],
        help="Environment to be used: localhost, DEV, INT or PROD",
        type=str.lower
    )
    parser.add_argument("collection", help="Name of the asset's collection")
    parser.add_argument("item", help="Name of the asset's item")
    parser.add_argument("asset", help="Name of the asset to be uploaded")
    parser.add_argument("filepath", help="Local path of the asset file to be uploaded")
    parser.add_argument(
        "--part-size",
        type=int,
        default=DEFAULT_PART_SIZE,
        dest="part_size_in_mb",
        help=
        f"Size of the file parts in MB [Integer, default: {DEFAULT_PART_SIZE} MB] " \
        f"(Number of parts must be smaller than {MAX_PARTS_NUMBER})"
    )
    parser.add_argument("--username", help="If username is provided as argument, " \
        "the potentially defined STAC_USER environment variable will be IGNORED",
        default=os.environ.get('STAC_USER'))
    parser.add_argument("--password", help="If password is provided as argument, " \
        "the potentially defined STAC_PASSWORD environment variable will be IGNORED",
        default=os.environ.get('STAC_PASSWORD'))
    parser.add_argument("-v", "--verbose", help="Increase output verbosity", action="store_true")
    parser.add_argument(
        '--force',
        help="If an upload is already in progress, cancel it before starting this one.",
        action="store_true"
    )

    args = parser.parse_args()

    return args


class StacMultipartUploader:

    def __init__(self, proxy_config=None):
        '''Read the command line arguments and set the corresponding instance variables'''
        
        # Initialize HTTP sessions with proxy config if not already done
        global http, s3_session
        if http is None or s3_session is None:
            initialize_http_session(proxy_config)
        
        args = get_args()

        if not os.path.isfile(args.filepath):
            self._log(f"Error. The file {args.filepath} doesn't exists")
            sys.exit(1)

        scheme = "https"
        hostname = "data.geo.admin.ch"

        if args.env == "localhost":
            hostname = "127.0.0.1:8000"
            scheme = "http"
        elif args.env == "dev":
            hostname = "sys-data.dev.bgdi.ch"
        elif args.env == "int":
            hostname = "sys-data.int.bgdi.ch"

        self.stac_base_url = f"{scheme}://{hostname}/api/stac/v0.9"
        self.uploads_url = f"{self.stac_base_url}/collections/{args.collection}" \
            f"/items/{args.item}/assets/{args.asset}/uploads"

        if not args.username or not args.password:
            print(
                "ERROR: username and password must be provided, either as environment variables " \
                "\"STAC_USER\" and \"STAC_PASSWORD\" or as arguments \"--username\" and " \
                "\"--password\""
            )
            sys.exit(1)

        self.credentials = (args.username, args.password)

        self.part_size = args.part_size_in_mb * 1024 * 1024
        self.asset_file_name = args.filepath
        self.verbose = args.verbose
        self.force = args.force

        # Generate hashes
        (self.checksum_multihash, self.md5_parts) = self._generate_hashes()

    def _log(self, message, verbose=True, request=None, response=None):
        '''Log message and optional request/response details'''
        if verbose:
            if request and self.verbose:
                logger.debug(f"  Request: {request.method} {request.url}")
                if request.body:
                    try:
                        body_dict = json.loads(request.body)
                        logger.debug(f"  Body: {json.dumps(body_dict, indent=2)}")
                    except (json.JSONDecodeError, TypeError):
                        logger.debug(f"  Body (raw): {request.body[:200]}")
            if response and self.verbose:
                logger.debug(f"  Response: {response.status_code} {response.reason}")
                try:
                    logger.debug(f"  Body: {json.dumps(response.json(), indent=2)}")
                except (json.JSONDecodeError, ValueError):
                    logger.debug(f"  Body (raw): {response.text}")
        else:
            logger.debug(message)

    def _generate_hashes(self):
        '''Returns the hashes for the file parts to upload. Called by the constructor.'''
        sha256 = hashlib.sha256()
        md5_parts = []
        file_size = os.path.getsize(self.asset_file_name)
        total_parts = max(1, (file_size + self.part_size - 1) // self.part_size)
        file_size_mb = file_size / 1_048_576

        print(f"  Prüfsummen berechnen: {file_size_mb:.0f} MB  ({total_parts} Teile à {self.part_size // 1_048_576} MB) ...")
        with open(self.asset_file_name, 'rb') as file_descriptor:
            while True:
                data = file_descriptor.read(self.part_size)
                if data in (b'', ''):
                    break
                sha256.update(data)
                md5_parts.append({'part_number': len(md5_parts) + 1, 'md5': b64_md5(data)})
                pct     = len(md5_parts) / total_parts * 100
                bar     = "█" * int(pct / 4) + "░" * (25 - int(pct / 4))
                read_mb = len(md5_parts) * self.part_size / 1_048_576
                print(f"\r    [{bar}] {pct:5.1f}%  Teil {len(md5_parts)}/{total_parts}  ({read_mb:.0f} MB gelesen)",
                      end="", flush=True)
        print(f"\r    [{'█' * 25}] 100.0%  {total_parts}/{total_parts} Teile  ({file_size_mb:.0f} MB)  ✓", flush=True)

        sha2_256 = multihash.encode(sha256.digest(), 'sha2-256')
        checksum_multihash = multihash.to_hex_string(sha2_256)
        return (checksum_multihash, md5_parts)

    def _abort_upload(self, upload_id):
        response = http.post(f"{self.uploads_url}/{upload_id}/abort", auth=self.credentials)
        self._log(
            "Abort response received.",
            verbose=self.verbose,
            request=response.request,
            response=response
        )
        if response.status_code != 200 or response.json().get('status') != 'aborted':
            raise HttpError(response, "Aborting unsuccessful!")
        self._log("Aborted.", self.verbose)

    def upload_file(self):
        '''Upload the file to STAC'''
        if self.force:
            self._abort_previous_upload()
        upload_id, upload_urls = self._create_multipart_upload()
        try:
            uploaded_part_etags = self._upload_parts(upload_urls)
            self._complete_upload(upload_id, uploaded_part_etags)
        except (KeyboardInterrupt, requests.exceptions.RequestException) as ex:
            self._log(f"{type(ex).__name__} was raised. Gracefully abort...", verbose=self.verbose)
            self._abort_upload(upload_id)
            raise ex

    def _abort_previous_upload(self):
        self._log("Abort an upload that was already in progress...", verbose=self.verbose)
        response = http.get(self.uploads_url, params={"status": "in-progress"})
        if response.status_code != 200:
            raise HttpError(response)
        uploads = response.json()['uploads']
        if len(uploads) > 0:
            self._abort_upload(uploads[0]['upload_id'])
        else:
            self._log("No previous upload found", verbose=self.verbose)

    def _create_multipart_upload(self):
        '''Create a multipart upload'''
        self._log("First POST request for creating the multipart upload...", verbose=self.verbose)
        payload = {
            "number_parts": len(self.md5_parts),
            "md5_parts": self.md5_parts,
            "checksum:multihash": self.checksum_multihash,
            "update_interval": 30
        }
        response = http.post(self.uploads_url, auth=self.credentials, json=payload)
        self._log(
            f"Response status code was: {response.status_code}",
            verbose=self.verbose,
            request=response.request,
            response=response
        )
        if response.status_code == 409 and 'Upload already in progress' in response.json(
        )["description"]:
            raise HttpError(
                response,
                "Another upload is already in progress. To force upload, use \"--force\"."
            )
        if response.status_code != 201:
            raise HttpError(response)
        return (response.json()['upload_id'], response.json()['urls'])

    def _upload_parts(self, upload_urls):
        '''Upload the parts using the presigned urls'''
        parts = []
        number_of_parts = len(upload_urls)
        file_size_mb    = os.path.getsize(self.asset_file_name) / 1_048_576
        part_size_mb    = self.part_size / 1_048_576
        _upload_start   = datetime.now()

        print(f"  Upload: {file_size_mb:.0f} MB in {number_of_parts} Teile  → {self.asset_file_name}")

        with open(self.asset_file_name, 'rb') as file_descriptor:
            for url in upload_urls:
                part_num   = url['part']
                uploaded_mb = (part_num - 1) * part_size_mb
                pct        = uploaded_mb / file_size_mb * 100
                elapsed    = (datetime.now() - _upload_start).total_seconds()
                speed      = uploaded_mb / elapsed if elapsed > 1 else 0
                eta_s      = (file_size_mb - uploaded_mb) / speed if speed > 0.5 else 0
                eta_str    = f"  ETA ~{int(eta_s // 60)}m{int(eta_s % 60):02d}s" if eta_s > 5 else ""
                bar        = "█" * int(pct / 4) + "░" * (25 - int(pct / 4))
                print(f"\r    [{bar}] {pct:5.1f}%  Teil {part_num - 1}/{number_of_parts}"
                      f"  {uploaded_mb:.0f}/{file_size_mb:.0f} MB"
                      f"  {speed:.1f} MB/s{eta_str}",
                      end="", flush=True)
                data = file_descriptor.read(self.part_size)
                retry = 5  # Increased from 3 to 5 for VPN stability
                last_error = None
                
                while retry:
                    try:
                        # CRITICAL: Use s3_session (not http) for S3 presigned URL uploads
                        # This session has NO proxy and SSL verification disabled for VPN
                        response = s3_session.put(
                            url['url'],
                            data=data,
                            headers={'Content-MD5': self.md5_parts[url['part'] - 1]["md5"]},
                            timeout=DEFAULT_TIMEOUT  # Explicit timeout for large uploads
                        )
                        
                        self._log(
                            f"Part {url['part']} upload complete.",
                            verbose=self.verbose,
                            request=response.request,
                            response=response
                        )
                        
                        if response.status_code == 200:
                            parts.append({'etag': response.headers['ETag'], 'part_number': url['part']})
                            retry = 0
                            last_error = None
                        else:
                            last_error = f"HTTP {response.status_code}: {response.reason}"
                            retry -= 1
                            if retry > 0:
                                import time
                                wait_time = (6 - retry) * 2  # Progressive backoff: 2, 4, 6, 8 seconds
                                logger.warning(f"  ⚠ Part {url['part']} failed: {last_error}. Retry in {wait_time}s ({retry} left)")
                                time.sleep(wait_time)
                            else:
                                raise HttpError(response, f'Failed to upload part {url["part"]} after 5 attempts')
                    
                    except requests.exceptions.SSLError as ssl_err:
                        last_error = f"SSL Error: {str(ssl_err)}"
                        retry -= 1
                        if retry > 0:
                            import time
                            wait_time = (6 - retry) * 2
                            logger.warning(f"  ⚠ Part {url['part']} SSL error. Retry in {wait_time}s ({retry} left)")
                            time.sleep(wait_time)
                        else:
                            logger.error(f"  ✗ Part {url['part']} failed after 5 attempts: {last_error}")
                            raise
                    
                    except requests.exceptions.RequestException as req_err:
                        last_error = f"Request Error: {str(req_err)}"
                        retry -= 1
                        if retry > 0:
                            import time
                            wait_time = (6 - retry) * 2
                            logger.warning(f"  ⚠ Part {url['part']} request error. Retry in {wait_time}s ({retry} left)")
                            time.sleep(wait_time)
                        else:
                            logger.error(f"  ✗ Part {url['part']} failed after 5 attempts: {last_error}")
                            raise

        elapsed_total = (datetime.now() - _upload_start).total_seconds()
        avg_speed     = file_size_mb / elapsed_total if elapsed_total > 0 else 0
        print(f"\r    [{'█' * 25}] 100.0%  {number_of_parts}/{number_of_parts} Teile"
              f"  {file_size_mb:.0f} MB  ∅ {avg_speed:.1f} MB/s  ✓", flush=True)
        return parts

    def _complete_upload(self, upload_id, parts):
        '''Complete the upload'''
        print("  Upload abschliessen (Server-seitige Verarbeitung) ...")
        self._log("Checking for multipart upload completness...", verbose=self.verbose)
        payload = {'parts': parts}
        response = http.post(
            f"{self.uploads_url}/{upload_id}/complete", auth=self.credentials, json=payload
        )
        self._log(
            "Completed multipart upload.",
            verbose=self.verbose,
            request=response.request,
            response=response
        )
        if response.status_code != 200 or response.json().get('status') != 'completed':
            raise HttpError(response)
        self._log("Completed!", verbose=self.verbose)


def main():
    '''Upload large file to STAC using multi-part uploads'''
    try:
        # Initialize without proxy config for CLI usage
        initialize_http_session()
        StacMultipartUploader().upload_file()
    except KeyboardInterrupt as interrupt:
        print('\nInterrupted!')
        raise SystemExit(interrupt) from interrupt


def multipart_upload(env, collection, item, asset, filepath, username, password,
                     force=True, verbose=False, proxy_config=None, part_size_mb=None):
    """
    Upload large file to STAC using multi-part uploads.

    Args:
        env (str): Environment (localhost, dev, int, prod)
        collection (str): Collection name
        item (str): Item name
        asset (str): Asset name
        filepath (str): Path to file to upload
        username (str): STAC API username
        password (str): STAC API password
        force (bool): Force upload (cancel existing uploads)
        verbose (bool): Enable verbose logging
        proxy_config (dict): Proxy configuration with 'enabled', 'proxies', and 'session' keys
        part_size_mb (int): Optional part size in MB. Defaults to DEFAULT_PART_SIZE.
            Must be large enough that number_parts = filesize / part_size_mb stays
            below MAX_PARTS_NUMBER (100), otherwise the STAC API rejects the upload.

    Returns:
        bool: True if successful, False otherwise
    """
    import os

    # Initialize HTTP sessions with proxy configuration FIRST
    initialize_http_session(proxy_config)

    # Set environment variables for credentials
    os.environ['STAC_USER'] = username
    os.environ['STAC_PASSWORD'] = password

    # Build command-line arguments for the uploader.
    # CRITICAL: sys.argv is global — use a lock so parallel workers
    # don't overwrite each other's arguments mid-upload.
    argv = [
        'main_multipart_upload_via_api.py',
        env, collection, item, asset, filepath,
        '--username', username,
        '--password', password,
    ]
    if part_size_mb: argv.extend(['--part-size', str(part_size_mb)])
    if verbose: argv.append('--verbose')
    if force:   argv.append('--force')

    # Lock only during construction (reads sys.argv via get_args()).
    # upload_file() uses only instance variables — safe to run in parallel.
    with _ARGV_LOCK:
        sys.argv = argv
        uploader = StacMultipartUploader(proxy_config=proxy_config)

    try:
        uploader.upload_file()
        return True
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        return False


if __name__ == "__main__":
    main()