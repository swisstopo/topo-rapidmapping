#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rapid Mapping Processor - Hauptskript v2.0 (subprocess version)
Version: 2.0

Workflow:
1. Orthophotos: Single COG-File Check → Copy + Thumbnail → Upload
2. Einzelbilder: EXIF + Thumbnails → Upload einzeln → KML-Overview via STAC

Usage:
    python rapidmapping_processor.py
    python rapidmapping_processor.py --upload=False  # Nur lokale Verarbeitung
    python rapidmapping_processor.py --prod  # PROD-Environment
"""

import argparse
import logging
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
from utilities.photo_processor import process_individual_photos,generate_csv_from_photos
from utilities.kml_generator import create_overview_kml
from utilities.stac_publisher import publish_to_stac_wrapper
from utilities.proxy_handler import initialize_proxy
from utilities.credentials import load_stac_credentials
from util_publish_stac_fsdi import publish_to_stac

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    """Print application banner."""
    print("=" * 70)
    print(" " * 12 + "SWISSTOPO RAPID MAPPING PROCESSOR v2.0")
    print(" " * 18 + "(subprocess version)")
    print("=" * 70)
    print()


def prompt_input_directory():
    """Interaktive Abfrage des Input-Verzeichnisses."""
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
    """Interaktive Auswahl des Produkttyps."""
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
    """Interaktive Abfrage des Aufnahmezeitpunkts."""
    if product_type in [ProductType.EBN, ProductType.EBO]:
        # Für Einzelbilder: Nur Datum
        print("\n🕐 Bitte Aufnahmedatum angeben:")
        print("   Format: YYYY-MM-DD")
        print("   Beispiel: 2024-07-15")
        
        while True:
            date_input = input("-> ").strip()
            try:
                datetime.strptime(date_input, '%Y-%m-%d')
                logger.info(f"✓ Datum validiert: {date_input}")
                return date_input
            except ValueError:
                logger.error("✗ Ungültiges Format. Bitte YYYY-MM-DD verwenden.")
    else:
        # Für Mosaike: Vollständiger Timestamp
        print("\n🕐 Bitte Aufnahmezeitpunkt angeben:")
        print("   Format: YYYY-MM-DDthhmmss")
        print("   Beispiel: 2024-07-15t143000")
        
        while True:
            timestamp = input("-> ").strip().lower()
            if validate_timestamp(timestamp):
                logger.info(f"✓ Zeitstempel validiert: {timestamp}")
                return timestamp
            else:
                logger.error("✗ Ungültiges Format. Bitte YYYY-MM-DDthhmmss verwenden.")


def process_mosaic_workflow(
    input_dir: Path,
    product_type: ProductType,
    timestamp: str,
    upload_enabled: bool,
    environment: str,
    hostname: str
):
    """Workflow für Orthophoto-Mosaike (Single COG-File)."""
    try:
        temp_dir = Path("temp")
        temp_dir.mkdir(exist_ok=True)
        
        config = get_product_config(product_type)
        
        logger.info("=" * 70)
        logger.info("ORTHOPHOTO SINGLE COG-FILE PROCESSING")
        logger.info("=" * 70)
        
        # Item-Name und Asset-Name
        item_name = generate_item_name(timestamp, product_type)
        asset_name_base = generate_asset_name(timestamp, product_type)
        
        logger.info(f"STAC Item: {item_name}")
        logger.info(f"STAC Asset: {asset_name_base}")
        
        # Single COG-File Processing
        output_file = process_single_cog_file(
            input_dir=input_dir,
            output_dir=temp_dir,
            filename=Path(asset_name_base).stem # filename without extension
        )
        
        if not output_file:
            logger.error("✗ COG-File-Processing fehlgeschlagen")
            return False
        
        # Thumbnail-Pfad
        thumbnail_file = temp_dir / "thumbnail.jpg"
        
        # STAC Upload
        if upload_enabled:
            # 1. Upload Haupt-Asset (COG-Tiff)
            # Temporär umbenennen für Upload
            upload_temp_dir = temp_dir 
            #upload_temp_dir.mkdir(exist_ok=True)
            
            temp_cog_path = upload_temp_dir / asset_name_base
            #shutil.copy2(output_file, temp_cog_path)
            
            logger.info(f"\n→ Upload COG-Tiff als: {asset_name_base}")           
            
            cog_success = publish_to_stac_wrapper(
                asset_path=temp_cog_path,
                item_name=item_name,
                collection=STAC_COLLECTION,
                geocat_id=GEOCAT_ID,
                hostname=hostname,
                asset_title=config['asset_title'],
                environment=environment
            )
            

            # 2. Upload Thumbnail (falls vorhanden)
            thumbnail_success = False
            if thumbnail_file.exists():
                temp_thumb_path = upload_temp_dir / "thumbnail.jpg"
                #shutil.copy2(thumbnail_file, temp_thumb_path)
                
                logger.info(f"\n→ Upload Thumbnail als: thumbnail.jpg")
                thumbnail_success = publish_to_stac_wrapper(
                    asset_path=temp_thumb_path,
                    item_name=item_name,
                    collection=STAC_COLLECTION,
                    geocat_id=GEOCAT_ID,
                    hostname=hostname,
                    asset_title="THUMBNAIL",
                    environment=environment
                )
            
            # Cleanup Temp-Dateien
            if cog_success and thumbnail_success:
                cleanup_temp_directory(temp_dir)
                        #Übergabe für CMS
                logger.info("\n" + "=" * 70)
                logger.info(f"Nächster Schritt für {config['description']}: URL für rapidmapping.ch")
                logger.info(f"1) URL öffnen: https://map.geo.admin.ch/#/map?layers=COG|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{item_name}/{asset_name_base}")
                logger.info(f"2) Kartenausschnitt: als iFrame in rapidmapping.ch integrieren")
                logger.info("=" * 70)
            
            return cog_success
        else:
            logger.info(f"ℹ Upload deaktiviert. Dateien gespeichert in: {temp_dir}")
            return True
            
    except Exception as e:
        logger.error(f"✗ Fehler im Mosaic-Workflow: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def process_photos_workflow(
    input_dir: Path,
    product_type: ProductType,
    date: str,
    upload_enabled: bool,
    environment: str,
    hostname: str
):
    """Workflow für Einzelbilder mit Upload und KML-Overview."""
    try:
        temp_dir = Path("temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        config = get_product_config(product_type)
        
        logger.info("=" * 70)
        logger.info("INDIVIDUAL PHOTOS PROCESSING")
        logger.info("=" * 70)
        
        # Photos verarbeiten (EXIF + Thumbnails)
        result = process_individual_photos(
            input_dir=input_dir,
            output_dir=temp_dir,
            product_config=config,
            product_type=product_type,
            stac_collection=STAC_COLLECTION,
            geocat_id=GEOCAT_ID, 
            hostname=hostname,
            environment=environment,
            upload_enabled=upload_enabled
        )
        
        if not result:
            logger.error("✗ Photo-Verarbeitung fehlgeschlagen")
            return False
        
        # Generiere ein Downloadliste für alle photos
        photos = result['photos']
        generate_csv_from_photos(photos,output_file=f"{date}-{product_type.value}.txt",stac_scheme=STAC_SCHEME, hostname=hostname,stac_collection=STAC_COLLECTION)
        
              
            
        # KML-Overview generieren (via STAC-Abfrage)
        if result['successful_uploads']> 0:
            logger.info("\n" + "=" * 70)
            logger.info("GENERIERE KML-OVERVIEW (via STAC-Abfrage)")
            logger.info("=" * 70)
            
            kml_timestamp = f"{date}t235959"
            kml_item_name = generate_item_name(kml_timestamp, product_type) + "-overview"
            kml_asset_name = kml_item_name + ".kml"
            kml_file = temp_dir / kml_asset_name
            
            # STAC-URL
            stac_url = f"{STAC_SCHEME}://{hostname}{STAC_API_PATH}"
            
            # Produkt-Suffix für Abfrage
            product_suffix = config['suffix'].replace('-mosaic', '')
            
            # KML erstellen via STAC-Abfrage
            kml_success = create_overview_kml(
                stac_url=stac_url,
                collection=STAC_COLLECTION,
                date=date,
                product_suffix=product_suffix,
                product_config=config,
                output_file=kml_file
            )
           
            if kml_success:
                # Upload KML
                logger.info(f"\n→ Upload KML-Overview als: {kml_asset_name}")
                publish_to_stac_wrapper(
                    asset_path=kml_file,
                    item_name=kml_item_name,
                    collection=STAC_COLLECTION,
                    geocat_id=GEOCAT_ID,
                    hostname=hostname,
                    asset_title=f"{config['asset_title']}-OVERVIEW",
                    environment=environment
                )
                
        # Cleanup
        if result['successful_uploads'] == len(photos):
            cleanup_temp_directory(temp_dir)
            
            #Übergabe für CMS
            logger.info("\n" + "=" * 70)
            logger.info(f"Nächster Schritt für {config['description']}: URL für rapidmapping.ch")
            logger.info(f"1) URL öffnen: https://map.geo.admin.ch/#/map?layers=KML|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{kml_item_name}/{kml_asset_name}")
            logger.info(f"2) Kartenausschnitt: als iFrame in rapidmapping.ch integrieren")
            logger.info(f"3) Downloadliste: {date}-{product_type.value}.txt")
            logger.info("=" * 70)

        return result['successful_uploads'] > 0
            
    except Exception as e:
        logger.error(f"✗ Fehler im Photos-Workflow: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """Hauptfunktion mit CLI-Argumenten."""
    parser = argparse.ArgumentParser(
        description='Swisstopo Rapid Mapping Processor v2.0 (subprocess);  POC!',
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
    
    args = parser.parse_args()
    environment = "PROD" if args.prod else "INT"
    
    try:
        print_banner()
        
        # Proxy
        # logger.info("=" * 70)
        # logger.info("PROXY INITIALISIERUNG")
        # logger.info("=" * 70)
        # initialize_proxy()
        
        # Credentials
        if args.upload:
            logger.info("=" * 70)
            logger.info(f"CREDENTIALS ({environment})")
            logger.info("=" * 70)
            username, password, hostname = load_stac_credentials(environment=environment)
            logger.info(f"✓ Credentials geladen: {hostname}")
        else:
            hostname = None
        
        # Eingaben
        logger.info("=" * 70)
        logger.info("KONFIGURATION")
        logger.info("=" * 70)
        
        input_dir = prompt_input_directory()
        product_type = prompt_product_type()
        timestamp_or_date = prompt_timestamp(product_type)
        
        # Zusammenfassung
        print("\n" + "=" * 70)
        print("ZUSAMMENFASSUNG")
        print("=" * 70)
        print(f"  Environment:    {environment}")
        print(f"  Input-Verz.:    {input_dir}")
        print(f"  Produkttyp:     {product_type.value}")
        print(f"  Zeitstempel:    {timestamp_or_date}")
        print(f"  STAC Upload:    {'Aktiviert' if args.upload else 'Deaktiviert'}")
        if args.upload:
            print(f"  STAC Hostname:  {hostname}")
        print("=" * 70)
        
        confirm = input("\n▶ Verarbeitung starten? [j/N]: ").strip().lower()
        if confirm not in ['j', 'ja', 'y', 'yes']:
            logger.info("Abbruch")
            return 0
        
        # Workflow
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
                args.upload, environment, hostname
            )
        
        # Finale Meldung
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