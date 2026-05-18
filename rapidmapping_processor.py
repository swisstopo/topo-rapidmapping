#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rapid Mapping Processor - Hauptskript v2.0 (subprocess version)
Version: 2.0

CHANGES v2.2:
- All item/asset names always have 2-digit ms-suffix ("00" if no burst)
- Mosaic workflow: appends "00" to timestamp
- KML/CSV overview item: timestamp t23595900

Usage:
    python rapidmapping_processor.py
    python rapidmapping_processor.py --upload=False
    python rapidmapping_processor.py --prod
"""

import argparse
import logging
import re
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime

from configuration import (
    ProductType,
    get_product_config,
    validate_timestamp,
    generate_item_name,
    generate_asset_name,
    get_collection_url,
    STAC_COLLECTION,
    GEOCAT_ID,
    STAC_SCHEME,
    STAC_API_PATH
)
from utilities.file_handler import (
    validate_directory,
    cleanup_temp_directory
)
from utilities.mosaic_processor import process_single_cog_file
from utilities.photo_processor import process_individual_photos, generate_csv_from_stac
from utilities.kml_generator import create_overview_kml
from utilities.stac_publisher import publish_to_stac_wrapper
from utilities.proxy_handler import initialize_proxy
from utilities.credentials import load_stac_credentials
# publish_to_stac importiert lazy (verhindert circular import)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def print_banner():
    print("=" * 70)
    print(" " * 12 + "SWISSTOPO RAPID MAPPING PROCESSOR v2.0")
    print(" " * 18 + "(POC - not for operational use)")
    print("=" * 70)
    print()


def prompt_input_directory():
    while True:
        print("\n📁 Bitte Input-Verzeichnis angeben:")
        print("   Beispiel Windows: C:\\oed\\temp\\rm\\input")
        print("   Beispiel Linux:   /home/user/rm/input")
        input_dir = input("-> ").strip()
        try:
            validated_path = validate_directory(input_dir)
            logger.info(f"✓ Input-Verzeichnis validiert: {validated_path}")
            return validated_path
        except (ValueError, FileNotFoundError) as e:
            logger.error(f"✗ {str(e)}")
            continue


def prompt_product_type():
    print("\n📦 Bitte Produkttyp auswählen:")
    print("   1) QDOP RGB Mosaic (Orthophoto RGB)")
    print("   2) QDOP NRG Mosaic (Orthophoto Nahinfrarot)")
    print("   3) EBN - Einzelbilder Nadir (Senkrecht)")
    print("   4) EBO - Einzelbilder Oblique (Schrägaufnahmen)")
    print("   5) QDOP-DMC4 (4-Kanal DMC4-Streifen → RGB + NRG)")
    choices = {
        '1': ProductType.QDOP_RGB,
        '2': ProductType.QDOP_NRG,
        '3': ProductType.EBN,
        '4': ProductType.EBO,
        '5': ProductType.QDOP_DMC4,
    }
    while True:
        choice = input("-> ").strip()
        if choice in choices:
            product = choices[choice]
            logger.info(f"✓ Produkttyp gewählt: {product.value}")
            return product
        else:
            logger.error("✗ Ungültige Auswahl. Bitte 1-5 eingeben.")


def prompt_timestamp(product_type):
    if product_type in [ProductType.EBN, ProductType.EBO]:
        print("\n🕐 Bitte Aufnahmedatum angeben:")
        print("   Format: YYYY-MM-DD  Beispiel: 2024-07-15")
        while True:
            date_input = input("-> ").strip()
            try:
                datetime.strptime(date_input, '%Y-%m-%d')
                logger.info(f"✓ Datum validiert: {date_input}")
                return date_input
            except ValueError:
                logger.error("✗ Ungültiges Format. Bitte YYYY-MM-DD verwenden.")
    else:
        print("\n🕐 Bitte Aufnahmezeitpunkt angeben:")
        print("   Format: YYYY-MM-DDthhmmss  Beispiel: 2024-07-15t143000")
        while True:
            timestamp = input("-> ").strip().lower()
            if validate_timestamp(timestamp):
                logger.info(f"✓ Zeitstempel validiert: {timestamp}")
                return timestamp
            else:
                logger.error("✗ Ungültiges Format. Bitte YYYY-MM-DDthhmmss verwenden.")


def _ensure_ms_suffix(timestamp: str) -> str:
    """
    Stellt sicher dass ein Timestamp ein 2-stelliges ms-Suffix hat.
    "2024-07-15t143000"   ->  "2024-07-15t14300000"
    "2024-07-15t14300000" ->  "2024-07-15t14300000"  (unveraendert)
    """
    if re.match(r'^\d{4}-\d{2}-\d{2}t\d{6}$', timestamp):
        return timestamp + "00"
    return timestamp


def _run_gdal(label: str, cmd: list) -> bool:
    """
    Run a GDAL subprocess with live progress output.

    Prints a labelled header line, then lets GDAL's own -progress output go
    straight to the terminal (stdout inherited).  Only stderr is captured so
    we can log it on failure.

    Returns True on success, False on non-zero exit.
    """
    import subprocess as _sp
    logger.info(f"  → {label}")
    result = _sp.run(cmd + ["-progress"], stderr=_sp.PIPE, text=True)
    if result.returncode != 0:
        logger.error(f"    ✗ fehlgeschlagen (exit {result.returncode})")
        if result.stderr.strip():
            logger.error(result.stderr.strip())
        return False
    return True


def process_mosaic_workflow(
    input_dir, product_type, timestamp, upload_enabled, environment, hostname,
    debug: bool = False,
):
    """Workflow fuer Orthophoto-Mosaike.

    B) QDOP-Item hat jetzt keine Produktsuffix mehr: ram-YYYY-MM-DDthhmmsscc
       Beide Varianten (RGB + NRG) landen als Assets im selben Item.
    """
    try:
        output_dir = Path("output") if not upload_enabled else Path("temp")
        output_dir.mkdir(exist_ok=True)
        temp_dir = output_dir

        config = get_product_config(product_type)

        logger.info("=" * 70)
        logger.info("ORTHOPHOTO SINGLE COG-FILE PROCESSING")
        logger.info("=" * 70)

        # NEU v2.2: ms-Suffix sicherstellen
        timestamp_ms = _ensure_ms_suffix(timestamp)
        if timestamp_ms != timestamp:
            logger.info(f"  ms-Suffix ergaenzt: {timestamp} -> {timestamp_ms}")

        item_name      = generate_item_name(timestamp_ms, product_type)
        asset_name_base = generate_asset_name(timestamp_ms, product_type)

        logger.info(f"STAC Item:  {item_name}")
        logger.info(f"STAC Asset: {asset_name_base}")

        output_file = process_single_cog_file(
            input_dir=input_dir,
            output_dir=temp_dir,
            filename=Path(asset_name_base).stem
        )

        if not output_file:
            logger.error("✗ COG-File-Processing fehlgeschlagen")
            return False

        thumbnail_file = temp_dir / "thumbnail.jpg"

        if upload_enabled:
            upload_temp_dir = temp_dir
            temp_cog_path   = upload_temp_dir / asset_name_base

            logger.info(f"\n-> Upload COG-Tiff als: {asset_name_base}")
            cog_success = publish_to_stac_wrapper(
                asset_path=temp_cog_path,
                item_name=item_name,
                collection=STAC_COLLECTION,
                geocat_id=GEOCAT_ID,
                hostname=hostname,
                asset_title=config['asset_title'],
                environment=environment
            )

            thumbnail_success = False
            if thumbnail_file.exists():
                temp_thumb_path = upload_temp_dir / "thumbnail.jpg"
                logger.info(f"\n-> Upload Thumbnail als: thumbnail.jpg")
                thumbnail_success = publish_to_stac_wrapper(
                    asset_path=temp_thumb_path,
                    item_name=item_name,
                    collection=STAC_COLLECTION,
                    geocat_id=GEOCAT_ID,
                    hostname=hostname,
                    asset_title="THUMBNAIL",
                    environment=environment
                )

            if cog_success and thumbnail_success:
                cleanup_temp_directory(temp_dir)
                logger.info("\n" + "=" * 70)
                logger.info(f"Naechster Schritt fuer {config['description']}: URL fuer rapidmapping.ch")
                logger.info(f"1) URL oeffnen: https://map.geo.admin.ch/#/map?layers=COG|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{item_name}/{asset_name_base}")
                logger.info(f"2) Kartenausschnitt: als iFrame in rapidmapping.ch integrieren")
                logger.info("=" * 70)

            return cog_success
        else:
            logger.info(f"i Upload deaktiviert. Dateien gespeichert in: {temp_dir}")
            return True

    except Exception as e:
        logger.error(f"✗ Fehler im Mosaic-Workflow: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def process_dmc4_workflow(
    input_dir, timestamp, upload_enabled, environment, hostname,
    debug: bool = False,
):
    """
    Workflow für DMC4 4-Kanal Bildstreifen.

    Eingabe: Verzeichnis mit 4-Band TIF-Streifen (kein CRS, Daten in EPSG:2056).
    Bänder: 1=Rot, 2=Grün, 3=Blau, 4=Nahinfrarot.

    Schritte:
      1. Alle .tif-Dateien im Input-Verzeichnis finden
      2. Für jeden Streifen: CRS EPSG:2056 zuweisen + Bänder extrahieren
         - RGB: Bänder 1, 2, 3
         - NRG: Bänder 4, 1, 2 (Nahinfrarot, Rot, Grün)
      3. VRT-Mosaike bauen (RGB + NRG)
      4. Als COG konvertieren
      5. Thumbnail aus RGB-COG erstellen
      6. RGB-COG, NRG-COG und Thumbnail ins gleiche STAC-Item hochladen
    """
    import tempfile
    import subprocess as _sp  # used for gdalbuildvrt (no -progress support)
    from utilities.file_handler import get_tif_files
    from utilities.mosaic_processor import create_thumbnail_from_cog

    try:
        output_dir = Path("output") if not upload_enabled else Path("temp")
        output_dir.mkdir(exist_ok=True)

        timestamp_ms   = _ensure_ms_suffix(timestamp)
        # Both RGB and NRG share the same item name (no product suffix in item)
        item_name      = generate_item_name(timestamp_ms, ProductType.QDOP_RGB)
        config_rgb     = get_product_config(ProductType.QDOP_RGB)
        config_nrg     = get_product_config(ProductType.QDOP_NRG)
        asset_name_rgb = generate_asset_name(timestamp_ms, ProductType.QDOP_RGB)
        asset_name_nrg = generate_asset_name(timestamp_ms, ProductType.QDOP_NRG)

        logger.info("=" * 70)
        logger.info("DMC4 PROCESSING (RGB + NRG)")
        logger.info("=" * 70)
        logger.info(f"STAC Item:      {item_name}")
        logger.info(f"STAC Asset RGB: {asset_name_rgb}")
        logger.info(f"STAC Asset NRG: {asset_name_nrg}")

        input_files = get_tif_files(input_dir, recursive=False)
        if not input_files:
            logger.error("✗ Keine TIFF-Dateien im Input-Verzeichnis gefunden!")
            return False
        logger.info(f"\nGefunden: {len(input_files)} DMC4 Streifen")

        cog_rgb = output_dir / asset_name_rgb
        cog_nrg = output_dir / asset_name_nrg

        with tempfile.TemporaryDirectory() as _tmp:
            tmp   = Path(_tmp)
            t_rgb = tmp / "rgb"
            t_nrg = tmp / "nrg"
            t_rgb.mkdir()
            t_nrg.mkdir()

            # Step 1: extract bands + assign CRS + tag nodata for each stripe
            # -a_nodata 0 tags nodata in output metadata; gdalbuildvrt reads it
            total = len(input_files)
            for idx, tif in enumerate(input_files, 1):
                stem = tif.stem
                for label, bands, out_dir in [
                    ("RGB", ["1", "2", "3"], t_rgb),
                    ("NRG", ["4", "1", "2"], t_nrg),
                ]:
                    out = out_dir / f"{stem}_{label.lower()}.tif"
                    cmd = ["gdal_translate", "-a_srs", "EPSG:2056"]
                    for b in bands:
                        cmd += ["-b", b]
                    cmd += ["-a_nodata", "0", str(tif), str(out)]
                    if not _run_gdal(
                        f"[{idx}/{total}] Streifen {label}: {tif.name}", cmd
                    ):
                        return False

            logger.info("✓ Bänder extrahiert und CRS EPSG:2056 zugewiesen (nodata=0)")

            # Step 2: build VRT mosaics — honour nodata so stripe gaps are transparent
            # gdalbuildvrt does not support -progress, run quietly
            import subprocess as _sp
            for label, src_dir, vrt_name in [
                ("RGB", t_rgb, "mosaic_rgb.vrt"),
                ("NRG", t_nrg, "mosaic_nrg.vrt"),
            ]:
                vrt = tmp / vrt_name
                files = sorted(str(f) for f in src_dir.glob("*.tif"))
                logger.info(f"  → VRT Mosaic {label} ({len(files)} Streifen) ...")
                r = _sp.run(
                    ["gdalbuildvrt", "-srcnodata", "0 0 0", str(vrt)] + files,
                    stderr=_sp.PIPE, text=True
                )
                if r.returncode != 0:
                    logger.error(f"    ✗ gdalbuildvrt {label} fehlgeschlagen")
                    if r.stderr.strip():
                        logger.error(r.stderr.strip())
                    return False
                logger.info(f"    ✓ {vrt.name}")

            logger.info("✓ VRT-Mosaike erstellt")

            # Step 3: convert VRTs to COG (nodata preserved)
            for label, vrt_name, cog in [
                ("RGB", "mosaic_rgb.vrt", cog_rgb),
                ("NRG", "mosaic_nrg.vrt", cog_nrg),
            ]:
                if not _run_gdal(
                    f"COG {label}: {cog.name}",
                    ["gdal_translate", "-of", "COG",
                     "-co", "COMPRESS=JPEG", "-co", "QUALITY=75",
                     "-co", "BIGTIFF=YES",
                     "-a_nodata", "0",
                     str(tmp / vrt_name), str(cog)]
                ):
                    return False

        logger.info("✓ COG-Dateien erstellt")

        # Step 4: thumbnail from RGB COG
        thumbnail_file = output_dir / "thumbnail.jpg"
        create_thumbnail_from_cog(cog_rgb, thumbnail_file, max_size=256)

        if not upload_enabled:
            logger.info(f"i Upload deaktiviert. Dateien gespeichert in: {output_dir}")
            return True

        # Step 5: upload RGB, NRG and thumbnail to the same STAC item
        ok_rgb = publish_to_stac_wrapper(
            asset_path=cog_rgb, item_name=item_name,
            collection=STAC_COLLECTION, geocat_id=GEOCAT_ID,
            hostname=hostname, asset_title=config_rgb['asset_title'],
            environment=environment
        )
        ok_nrg = publish_to_stac_wrapper(
            asset_path=cog_nrg, item_name=item_name,
            collection=STAC_COLLECTION, geocat_id=GEOCAT_ID,
            hostname=hostname, asset_title=config_nrg['asset_title'],
            environment=environment
        )
        if thumbnail_file.exists():
            publish_to_stac_wrapper(
                asset_path=thumbnail_file, item_name=item_name,
                collection=STAC_COLLECTION, geocat_id=GEOCAT_ID,
                hostname=hostname, asset_title="THUMBNAIL",
                environment=environment
            )

        if ok_rgb and ok_nrg:
            cleanup_temp_directory(output_dir)
            logger.info("\n" + "=" * 70)
            logger.info(f"Nächster Schritt: URL für rapidmapping.ch")
            logger.info(f"  RGB: https://map.geo.admin.ch/#/map?layers=COG|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{item_name}/{asset_name_rgb}")
            logger.info(f"  NRG: https://map.geo.admin.ch/#/map?layers=COG|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{item_name}/{asset_name_nrg}")
            logger.info("=" * 70)

        return ok_rgb and ok_nrg

    except Exception as e:
        logger.error(f"✗ Fehler im DMC4-Workflow: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def process_photos_workflow(
    input_dir, product_type, date, upload_enabled, environment, hostname,
    debug: bool = False,
):
    """
    import logging as _logging
    if not debug:
        for _mod in ['utilities.stac_publisher', 'utilities.credentials',
                     'utilities.proxy_handler', 'main_multipart_upload_via_api',
                     'util_publish_stac_fsdi', 'utilities.kml_generator']:
            _logging.getLogger(_mod).setLevel(_logging.WARNING)
    # Workflow fuer Einzelbilder: Upload -> KML -> CSV.

    v2.2:
    - KML/CSV Overview-Item: Timestamp t23595900 (ms-Suffix "00")
    - generate_csv_from_stac fragt STAC per Datum+Suffix ab -> findet alle
      Items unabhaengig vom ms-Suffix (Bug 3 automatisch geloest)
    """
    try:
        import logging
        from pathlib import Path
        from configuration import (
            STAC_COLLECTION, GEOCAT_ID, STAC_SCHEME, STAC_API_PATH,
            get_product_config, generate_item_name
        )
        from utilities.photo_processor import process_individual_photos, generate_csv_from_stac
        from utilities.kml_generator import create_overview_kml
        from utilities.stac_publisher import publish_to_stac_wrapper

        logger = logging.getLogger(__name__)

        temp_dir = Path("output") if not upload_enabled else Path("temp")
        temp_dir.mkdir(exist_ok=True)

        config         = get_product_config(product_type)
        product_suffix = config['suffix'].replace('-mosaic', '').replace('-photo', '')
        stac_url       = f"{STAC_SCHEME}://{hostname}{STAC_API_PATH}"

        logger.info("=" * 70)
        logger.info("INDIVIDUAL PHOTOS PROCESSING")
        logger.info("=" * 70)

        result = process_individual_photos(
            input_dir=input_dir,
            output_dir=temp_dir,
            product_config=config,
            product_type=product_type,
            stac_collection=STAC_COLLECTION,
            geocat_id=GEOCAT_ID,
            hostname=hostname,
            environment=environment,
            upload_enabled=upload_enabled,
            debug=debug,
        )

        if not result:
            logger.error("✗ Photo-Verarbeitung fehlgeschlagen")
            return False

        kml_item_name  = None
        kml_asset_name = None
        csv_file       = None

        if result['successful_uploads'] > 0:

            logger.info("\n" + "=" * 70)
            logger.info("GENERIERE KML-OVERVIEW (via STAC-Abfrage)")
            logger.info("=" * 70)

            # NEU v2.2: Overview-Item mit ms-Suffix "00"
            kml_timestamp  = f"{date}t23595900"
            kml_item_name  = generate_item_name(kml_timestamp, product_type)
            product_short  = config['suffix'].split('-')[0]  # 'ebn' or 'ebo'
            kml_asset_name = f"{kml_item_name}-{product_short}.kml"
            kml_file       = temp_dir / kml_asset_name

            kml_success = create_overview_kml(
                stac_url=stac_url,
                collection=STAC_COLLECTION,
                date=date,
                product_suffix=product_suffix,
                product_config=config,
                output_file=kml_file
            )

            if kml_success:
                logger.info(f"\n-> Upload KML-Overview als: {kml_asset_name}")
                publish_to_stac_wrapper(
                    asset_path=kml_file,
                    item_name=kml_item_name,
                    collection=STAC_COLLECTION,
                    geocat_id=GEOCAT_ID,
                    hostname=hostname,
                    asset_title=f"{config['asset_title']}-OVERVIEW",
                    environment=environment
                )

            if upload_enabled:
                logger.info("\n" + "=" * 70)
                logger.info("GENERIERE CSV AUS STAC")
                logger.info("=" * 70)

                csv_asset_name = f"{kml_item_name}-{product_short}.txt"
                csv_file       = temp_dir / csv_asset_name

                csv_ok = generate_csv_from_stac(
                    stac_url=stac_url,
                    collection=STAC_COLLECTION,
                    date=date,
                    product_suffix=product_suffix,
                    output_file=csv_file
                )

                if csv_ok and csv_file.exists():
                    logger.info(f"\n-> Upload TXT als: {csv_asset_name} -> Item: {kml_item_name}")
                    publish_to_stac_wrapper(
                        asset_path=csv_file,
                        item_name=kml_item_name,
                        collection=STAC_COLLECTION,
                        geocat_id=GEOCAT_ID,
                        hostname=hostname,
                        asset_title=f"{config['asset_title']}-LISTE",
                        environment=environment
                    )

        elif not upload_enabled:
            logger.info("i Upload deaktiviert - KML/CSV-Generierung uebersprungen")

        photos = result['photos']
        if result['successful_uploads'] == len(photos):
            from utilities.file_handler import cleanup_temp_directory
            cleanup_temp_directory(temp_dir)

            if kml_item_name:
                csv_stac_url = (
                    f"{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}"
                    f"/{kml_item_name}/{csv_asset_name}"
                )
                # Links immer ausgeben — auch im non-debug Modus
                print("\n" + "=" * 70)
                print(f"✅ Nächster Schritt: {config['description']}")
                print(f"🗺  Karte:  https://map.geo.admin.ch/#/map?layers=KML|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{kml_item_name}/{kml_asset_name}")
                print(f"📥 Liste:  {csv_stac_url}")
                print("=" * 70)

        return result['successful_uploads'] > 0

    except Exception as e:
        import logging, traceback
        logging.getLogger(__name__).error(f"Fehler im Photos-Workflow: {str(e)}")
        logging.getLogger(__name__).error(traceback.format_exc())
        return False


def _normalize_cli_timestamp(raw: str) -> str:
    """
    Normalize compact timestamp to standard YYYY-MM-DDthhmmss[cc] format.

    Args:
        raw (str): Raw CLI input, e.g. '20210729t125959' or '20210729'

    Returns:
        str: Normalized timestamp, e.g. '2021-07-29t125959'
    """
    # Already normalized if it contains dashes
    if '-' in raw:
        return raw
    # Match compact: YYYYMMDD[tHHMMSS[CC]]
    m = re.match(r'^(\d{4})(\d{2})(\d{2})(t\d{6}(\d{2})?)?$', raw)
    if m:
        date_part = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        time_part = m.group(4) or ''
        return date_part + time_part
    return raw  # return as-is; validate_timestamp will reject it later


# ============================================================
# C) DEBUG-MODUS: Direkt hier setzen wenn ohne CLI-Argumente gestartet wird.
#    True  = sequentielle Verarbeitung + volles Logging (Debugging)
#    False = parallele Verarbeitung, minimales Logging (Produktion)
DEBUG_MODE_DEFAULT = False
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description='Swisstopo Rapid Mapping Processor v2.0 (subprocess); POC!',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Beispiele (interaktiv):
    python rapidmapping_processor.py
    python rapidmapping_processor.py --prod
    python rapidmapping_processor.py --upload=False

    Beispiele (vollständig via CLI):
    python rapidmapping_processor.py --product ebn --input C:\\data\\rm --timestamp 2025-09-03
    python rapidmapping_processor.py --product qdop-rgb --input /data/rm --timestamp 2024-07-15t143000
    python rapidmapping_processor.py --product ebo --input /data/rm --timestamp 2025-03-12 --upload=False
    python rapidmapping_processor.py --product qdop-nrg --input /data --timestamp 2024-07-15t14300000 --prod
    python rapidmapping_processor.py --product ebn --input /data --timestamp 2025-09-03 --debug
        """
    )
    # Basic options
    parser.add_argument('--upload', type=lambda x: x.lower() != 'false', default=True,
                        help='Upload zu STAC (default: True). False = Ausgabe in ./output/')
    parser.add_argument('--prod', action='store_true',
                        help='Produktionsumgebung verwenden (default: INT)')
    parser.add_argument('--debug', action='store_true', default=None,
                        help='Debug-Modus: sequentiell + volles Logging')

    # D) Full CLI product configuration (optional — falls nicht angegeben: interaktiv)
    parser.add_argument('--input', '--input-dir', dest='input_dir', default=None,
                        metavar='VERZEICHNIS',
                        help='Quellverzeichnis mit Eingabedaten')
    parser.add_argument('--product', dest='product', default=None,
                        choices=['ebn', 'ebo', 'qdop-rgb', 'qdop-nrg', 'qdop-dmc4'],
                        help='Produkttyp: ebn, ebo, qdop-rgb, qdop-nrg, qdop-dmc4')
    parser.add_argument('--timestamp', '--date', dest='timestamp', default=None,
                        metavar='TIMESTAMP',
                        help=('Zeitstempel/Datum. '
                              'QDOP/EBN/EBO: YYYY-MM-DDthhmmss[cc]  '
                              'EBN/EBO Datum: YYYY-MM-DD'))

    args = parser.parse_args()
    environment = "PROD" if args.prod else "INT"

    # C) Resolve debug flag: CLI > DEBUG_MODE_DEFAULT
    if args.debug is None:
        args.debug = DEBUG_MODE_DEFAULT

    try:
        print_banner()

        if args.upload:
            logger.info("=" * 70)
            logger.info(f"CREDENTIALS ({environment})")
            logger.info("=" * 70)
            username, password, hostname = load_stac_credentials(environment=environment)
            logger.info(f"✓ Credentials geladen: {hostname}")
        else:
            hostname = None

        logger.info("=" * 70)
        logger.info("KONFIGURATION")
        logger.info("=" * 70)

        # D) CLI params take priority; fall back to interactive prompts
        _product_map = {
            'ebn': ProductType.EBN, 'ebo': ProductType.EBO,
            'qdop-rgb': ProductType.QDOP_RGB, 'qdop-nrg': ProductType.QDOP_NRG,
            'qdop-dmc4': ProductType.QDOP_DMC4,
        }

        if args.input_dir:
            input_dir = validate_directory(args.input_dir)
            logger.info(f"✓ Input-Verzeichnis (CLI): {input_dir}")
        else:
            input_dir = prompt_input_directory()

        if args.product:
            product_type = _product_map[args.product]
            logger.info(f"✓ Produkttyp (CLI): {product_type.value}")
        else:
            product_type = prompt_product_type()

        if args.timestamp:
            ts = _normalize_cli_timestamp(args.timestamp.lower().strip())
            if product_type in (ProductType.EBN, ProductType.EBO):
                # EBN/EBO: accept date only (YYYY-MM-DD)
                try:
                    datetime.strptime(ts[:10], '%Y-%m-%d')
                    timestamp_or_date = ts[:10]
                except ValueError:
                    logger.error(
                        f"✗ Ungültiges Datum: {args.timestamp}. Erwartet: YYYY-MM-DD"
                    )
                    return 1
            else:
                # QDOP: require full timestamp YYYY-MM-DDthhmmss[cc]
                if not validate_timestamp(ts):
                    logger.error(
                        f"✗ Ungültiger Zeitstempel: {args.timestamp}. "
                        f"Erwartet: YYYY-MM-DDthhmmss[cc] oder YYYYMMDDthhmmss[cc]"
                    )
                    return 1
                timestamp_or_date = ts
            logger.info(f"✓ Zeitstempel (CLI): {timestamp_or_date}")
        else:
            timestamp_or_date = prompt_timestamp(product_type)

        print("\n" + "=" * 70)
        print("ZUSAMMENFASSUNG")
        print("=" * 70)
        print(f"  Environment:    {environment}")
        print(f"  Input-Verz.:    {input_dir}")
        print(f"  Produkttyp:     {product_type.value}")
        print(f"  Zeitstempel:    {timestamp_or_date}")
        print(f"  STAC Upload:    {'Aktiviert' if args.upload else 'Deaktiviert (→ ./output/)'}")
        print(f"  Debug-Modus:    {'AN (sequentiell)' if args.debug else 'AUS (parallel)'}")
        if args.upload:
            print(f"  STAC Hostname:  {hostname}")
        else:
            from pathlib import Path as _P
            _P("output").mkdir(exist_ok=True)
            print(f"  Output-Verz.:   {_P('output').resolve()}")
        print("=" * 70)

        # Skip confirmation when all parameters supplied via CLI
        _all_cli = (args.input_dir is not None
                    and args.product is not None
                    and args.timestamp is not None)
        if _all_cli:
            logger.info("▶ CLI-Modus: Starte ohne Bestätigung")
            confirm = 'j'
        else:
            confirm = input("\n▶ Verarbeitung starten? [j/N]: ").strip().lower()
        if confirm not in ['j', 'ja', 'y', 'yes']:
            logger.info("Abbruch")
            return 0

        print("\n" + "=" * 70)
        print("VERARBEITUNG GESTARTET")
        print("=" * 70 + "\n")

        # ── Log-Datei einrichten ──────────────────────────────────────────────
        _log_ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
        _log_filename = f"Log_{product_type.value}_{_log_ts}.txt"
        _log_handler  = logging.FileHandler(_log_filename, encoding='utf-8')
        _log_handler.setLevel(logging.INFO)
        _log_handler.setFormatter(
            logging.Formatter('%(asctime)s %(levelname)-8s %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')
        )
        logging.getLogger().addHandler(_log_handler)
        logger.info(f"Log-Datei: {_log_filename}")
        # ─────────────────────────────────────────────────────────────────────

        try:
            if product_type in [ProductType.QDOP_RGB, ProductType.QDOP_NRG]:
                success = process_mosaic_workflow(
                    input_dir, product_type, timestamp_or_date,
                    args.upload, environment, hostname,
                    debug=args.debug
                )
            elif product_type == ProductType.QDOP_DMC4:
                success = process_dmc4_workflow(
                    input_dir, timestamp_or_date,
                    args.upload, environment, hostname,
                    debug=args.debug
                )
            else:
                success = process_photos_workflow(
                    input_dir, product_type, timestamp_or_date,
                    args.upload, environment, hostname,
                    debug=args.debug
                )
        finally:
            logging.getLogger().removeHandler(_log_handler)
            _log_handler.close()

        print("\n" + "=" * 70)
        if success:
            logger.info("✓ VERARBEITUNG ERFOLGREICH")
        else:
            logger.error("✗ VERARBEITUNG MIT FEHLERN")
        print(f"  Log:  {Path(_log_filename).resolve()}")
        print("=" * 70 + "\n")

        return 0 if success else 1

    except KeyboardInterrupt:
        logger.warning("\n⚠ Abbruch (Ctrl+C)")
        return 130
    except Exception as e:
        logger.error(f"✗ Fehler: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())