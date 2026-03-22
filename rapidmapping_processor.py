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
    choices = {
        '1': ProductType.QDOP_RGB,
        '2': ProductType.QDOP_NRG,
        '3': ProductType.EBN,
        '4': ProductType.EBO
    }
    while True:
        choice = input("-> ").strip()
        if choice in choices:
            product = choices[choice]
            logger.info(f"✓ Produkttyp gewählt: {product.value}")
            return product
        else:
            logger.error("✗ Ungültige Auswahl. Bitte 1-4 eingeben.")


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


def process_mosaic_workflow(
    input_dir, product_type, timestamp, upload_enabled, environment, hostname
):
    """Workflow fuer Orthophoto-Mosaike.

    v2.2: Item/Asset-Namen haben immer ms-Suffix "00".
    """
    try:
        temp_dir = Path("temp")
        temp_dir.mkdir(exist_ok=True)

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


def process_photos_workflow(
    input_dir, product_type, date, upload_enabled, environment, hostname,
    debug: bool = False,
):
    import logging as _logging
    if not debug:
        for _mod in ['utilities.stac_publisher', 'utilities.credentials',
                     'utilities.proxy_handler', 'main_multipart_upload_via_api',
                     'util_publish_stac_fsdi', 'utilities.kml_generator']:
            _logging.getLogger(_mod).setLevel(_logging.WARNING)
    """Workflow fuer Einzelbilder: Upload -> KML -> CSV.

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

        temp_dir = Path("temp")
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
            kml_item_name  = generate_item_name(kml_timestamp, product_type) + "-overview"
            kml_asset_name = kml_item_name + ".kml"
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

                csv_asset_name = kml_item_name + ".txt"
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
                    f"/{kml_item_name}/{kml_item_name}.txt"
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


def main():
    parser = argparse.ArgumentParser(
        description='Swisstopo Rapid Mapping Processor v2.0 (subprocess); POC!',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Beispiele:
    python rapidmapping_processor.py              # INT
    python rapidmapping_processor.py --prod       # PROD
    python rapidmapping_processor.py --upload=False  # Kein Upload
        """
    )
    parser.add_argument('--upload', type=lambda x: x.lower() != 'false', default=True)
    parser.add_argument('--prod', action='store_true')
    parser.add_argument('--debug', action='store_true', help='Debug-Modus: sequentielle Verarbeitung mit vollem Logging')

    args = parser.parse_args()
    environment = "PROD" if args.prod else "INT"

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

        input_dir         = prompt_input_directory()
        product_type      = prompt_product_type()
        timestamp_or_date = prompt_timestamp(product_type)

        print("\n" + "=" * 70)
        print("ZUSAMMENFASSUNG")
        print("=" * 70)
        print(f"  Environment:    {environment}")
        print(f"  Input-Verz.:    {input_dir}")
        print(f"  Produkttyp:     {product_type.value}")
        print(f"  Zeitstempel:    {timestamp_or_date}")
        print(f"  STAC Upload:    {'Aktiviert' if args.upload else 'Deaktiviert'}")
        print(f"  Debug-Modus:    {'AN (sequentiell)' if args.debug else 'AUS (parallel)'}")
        if args.upload:
            print(f"  STAC Hostname:  {hostname}")
        print("=" * 70)

        confirm = input("\n▶ Verarbeitung starten? [j/N]: ").strip().lower()
        if confirm not in ['j', 'ja', 'y', 'yes']:
            logger.info("Abbruch")
            return 0

        print("\n" + "=" * 70)
        print("VERARBEITUNG GESTARTET")
        print("=" * 70 + "\n")

        if product_type in [ProductType.QDOP_RGB, ProductType.QDOP_NRG]:
            success = process_mosaic_workflow(
                input_dir, product_type, timestamp_or_date,
                args.upload, environment, hostname
            )
        else:
            success = process_photos_workflow(
                input_dir, product_type, timestamp_or_date,
                args.upload, environment, hostname,
                debug=args.debug
            )

        print("\n" + "=" * 70)
        if success:
            logger.info("✓ VERARBEITUNG ERFOLGREICH")
        else:
            logger.error("✗ VERARBEITUNG MIT FEHLERN")
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