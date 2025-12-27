"""
Individual Photo Processing mit subprocess (GDAL command-line tools).

Verarbeitet Einzelbilder (Nadir/Oblique) - EXIF-Extraktion und Thumbnail-Erstellung.
Basiert auf dem ursprünglichen rm_publish_einzelbilder.py Ansatz.

ÄNDERUNGEN:
- Kopiert Original-Foto in temp_dir und benennt gemäß Asset-Definition um
- Upload erfolgt DIREKT nach Verarbeitung jedes Fotos (vor photos.append)
- Verwendet ausschließlich proxy_handler.py für Proxy-Verwaltung
"""

import os
import subprocess
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from configuration import THUMBNAIL_CONFIG, ProductType, generate_item_name, generate_asset_name
from util_publish_stac_fsdi import publish_to_stac
from utilities.file_handler import get_jpg_files

logger = logging.getLogger(__name__)

def generate_csv_from_photos(
    photos: List[Dict],
    output_file: Path,
    stac_scheme: str = "https",
    hostname: str = "your-domain.com",
    stac_collection: str = "your-collection"
) -> bool:
    """
    Generates CSV file with only URLs from the list of photo dictionaries.
    
    Args:
        photos: List of photo dictionaries
        output_file: Path to output CSV file
        stac_scheme: URL scheme (http/https)
        hostname: Domain hostname
        stac_collection: STAC collection name
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as csvfile:
            count = 0
            for photo in photos:
                # Generate URL
                url = f"{stac_scheme}://{hostname}/{stac_collection}/{photo['item_name']}/{photo['asset_name']}.jpg"
                csvfile.write(f"{url}\n")
                count += 1
            
        print(f"✓ CSV created: {output_file} ({count} URLs)")
        return True
        
    except Exception as e:
        print(f"✗ CSV creation failed: {e}")
        return False

def dms_to_decimal(degrees: float, minutes: float, seconds: float, direction: str) -> float:
    """
    Konvertiert DMS (Degrees Minutes Seconds) zu Dezimal-Koordinaten.
    
    Args:
        degrees (float): Grad
        minutes (float): Minuten
        seconds (float): Sekunden
        direction (str): Richtung (N/S/E/W)
        
    Returns:
        float: Dezimal-Koordinate (6 Dezimalstellen Präzision)
    """
    decimal = degrees + minutes / 60 + seconds / 3600
    
    if direction in ['S', 'W']:
        decimal *= -1
    
    # Reduziere Präzision auf 6 Stellen für kleinere KML-Dateien
    return round(decimal, 6)


def extract_exif_data(file_path: Path) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Extrahiert EXIF-Daten aus JPEG-Datei mittels gdalinfo subprocess.
    
    Args:
        file_path (Path): Pfad zur JPEG-Datei
        
    Returns:
        Tuple: (latitude, longitude, timestamp) oder (None, None, None) bei Fehler
    """
    try:
        # Unterdrücke Ausgaben mit devnull
        with open(os.devnull, 'w') as devnull:
            result = subprocess.run(
                ['gdalinfo', '-json', str(file_path)],
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
            )
        
        if result.returncode != 0:
            return None, None, None
        
        exif_data = json.loads(result.stdout)
        
        lat, lon, timestamp = None, None, None
        
        if 'metadata' in exif_data and '' in exif_data['metadata']:
            exif = exif_data['metadata']['']
            
            # GPS-Daten extrahieren
            if 'EXIF_GPSLatitude' in exif and 'EXIF_GPSLongitude' in exif:
                lat_parts = exif['EXIF_GPSLatitude']
                lon_parts = exif['EXIF_GPSLongitude']
                lat_ref = exif.get('EXIF_GPSLatitudeRef', 'N')
                lon_ref = exif.get('EXIF_GPSLongitudeRef', 'E')
                
                # Parse DMS-Format: "(DD) (MM) (SS.SS)"
                try:
                    lat_vals = [float(x.replace(')', '')) for x in lat_parts.strip('()').split(') (')]
                    lon_vals = [float(x.replace(')', '')) for x in lon_parts.strip('()').split(') (')]
                    
                    lat = dms_to_decimal(lat_vals[0], lat_vals[1], lat_vals[2], lat_ref)
                    lon = dms_to_decimal(lon_vals[0], lon_vals[1], lon_vals[2], lon_ref)
                except (ValueError, IndexError):
                    lat, lon = None, None
            
            # Zeitstempel extrahieren
            if 'EXIF_DateTimeOriginal' in exif:
                timestamp = exif['EXIF_DateTimeOriginal']
        
        return lat, lon, timestamp
        
    except Exception as e:
        logger.warning(f"  ⚠ Fehler beim EXIF-Lesen von {file_path.name}: {e}")
        return None, None, None


def resize_image_gdal(
    input_file: Path,
    output_file: Path,
    max_width: int = THUMBNAIL_CONFIG['max_width'],
    max_height: int = THUMBNAIL_CONFIG['max_height']
) -> bool:
    """
    Erstellt Thumbnail mit gdal_translate subprocess unter Beibehaltung des Aspect Ratios.
    
    Args:
        input_file (Path): Input-Bilddatei
        output_file (Path): Output-Thumbnail
        max_width (int): Maximale Breite
        max_height (int): Maximale Höhe
        
    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    try:
        # Bilddimensionen auslesen mit gdalinfo
        with open(os.devnull, 'w') as devnull:
            gdalinfo_result = subprocess.run(
                ['gdalinfo', '-json', str(input_file)],
                capture_output=True,
                text=True,
                timeout=10
            )
        
        if gdalinfo_result.returncode != 0:
            return False
        
        image_info = json.loads(gdalinfo_result.stdout)
        width = int(image_info['size'][0])
        height = int(image_info['size'][1])
        
        # Berechnung der neuen Dimensionen unter Beibehaltung des Seitenverhältnisses
        aspect_ratio = width / height
        if aspect_ratio > 1:
            new_width = min(max_width, width)
            new_height = int(new_width / aspect_ratio)
        else:
            new_height = min(max_height, height)
            new_width = int(new_height * aspect_ratio)
        
        new_width = min(new_width, max_width)
        new_height = min(new_height, max_height)
        
        # Thumbnail erstellen mit gdal_translate
        with open(os.devnull, 'w') as devnull:
            translate_result = subprocess.run(
                [
                    'gdal_translate',
                    '-of', 'JPEG',
                    '-outsize', str(new_width), str(new_height),
                    str(input_file),
                    str(output_file)
                ],
                stdout=devnull,
                stderr=devnull,
                timeout=30,
                env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
            )
        
        return translate_result.returncode == 0
        
    except Exception as e:
        logger.warning(f"  ⚠ Fehler beim Thumbnail-Erstellen: {e}")
        return False


def process_single_photo(
    photo_file: Path,
    output_dir: Path,
    product_type: ProductType,
    timestamp: str
) -> Optional[Dict]:
    """
    Verarbeitet ein einzelnes Photo: EXIF + Thumbnail.
    
    Args:
        photo_file (Path): Originales Photo
        output_dir (Path): Output-Verzeichnis
        product_type (ProductType): Produkttyp
        timestamp (str): Zeitstempel für Item-Name
        
    Returns:
        Optional[Dict]: Photo-Metadaten oder None bei Fehler
        
    Dict-Keys:
        - original_path: Pfad zum Original-Photo
        - thumbnail_path: Pfad zum Thumbnail
        - item_name: STAC Item-Name
        - original_filename: Original-Dateiname
        - lat: Latitude (oder None)
        - lon: Longitude (oder None)
        - timestamp: EXIF-Timestamp (oder None)
    """
    try:
        # EXIF extrahieren
        lat, lon, exif_timestamp = extract_exif_data(photo_file)
        
        # Thumbnail erstellen
        thumbs_dir = output_dir / "thumbs"
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        
        # Thumbnail hat gleichen Namen wie Original
        thumbnail_path = thumbs_dir / photo_file.name
        
        thumbnail_success = resize_image_gdal(
            photo_file,
            thumbnail_path,
            max_width=THUMBNAIL_CONFIG['max_width'],
            max_height=THUMBNAIL_CONFIG['max_height']
        )
        
        if not thumbnail_success:
            logger.warning(f"  ⚠ Thumbnail-Erstellung fehlgeschlagen: {photo_file.name}")
            thumbnail_path = None
        
        # Item-Name generieren
        item_name = generate_item_name(timestamp, product_type)
        
        return {
            'original_path': photo_file,
            'thumbnail_path': thumbnail_path,
            'item_name': item_name,
            'original_filename': photo_file.name,
            'lat': lat,
            'lon': lon,
            'timestamp': exif_timestamp
        }
        
    except Exception as e:
        logger.error(f"  ✗ Fehler bei Photo-Verarbeitung: {e}")
        return None


def process_individual_photos(
    input_dir: Path,
    output_dir: Path,
    product_config: Dict,
    product_type: ProductType,
    stac_collection: str,
    geocat_id: str,
    hostname: str,
    environment: str,
    upload_enabled: bool = True
) -> Optional[Dict]:
    """
    Verarbeitet alle Photos in einem Verzeichnis.
    
    NEUER ABLAUF FÜR JEDES FOTO:
    1. EXIF-Daten extrahieren (mit gdalinfo)
    2. Original-Foto in temp_dir kopieren und gemäß Asset-Definition umbenennen
    3. Thumbnail erstellen und in temp_dir speichern (mit gdal_translate)
    4. FOTO ZU STAC HOCHLADEN (verwendet proxy_handler)
    5. THUMBNAIL ZU STAC HOCHLADEN (verwendet proxy_handler)
    6. Erst dann photo_info zur photos-Liste hinzufügen
    
    WICHTIG: Verwendet ausschließlich proxy_handler.py für Proxy-Verwaltung!
    WICHTIG: Upload erfolgt DIREKT nach Verarbeitung jedes Fotos!
    
    Args:
        input_dir (Path): Input-Verzeichnis mit JPEGs
        output_dir (Path): Output-Verzeichnis
        product_config (Dict): Produkt-Konfiguration
        product_type (ProductType): Produkttyp
        stac_collection (str): STAC Collection Name
        geocat_id (str): GeoCat ID
        hostname (str): STAC Hostname
        environment (str): Environment (INT/PROD)
        upload_enabled (bool): Upload aktiviert (Standard: True)
        
    Returns:
        Optional[Dict]: Dictionary mit verarbeiteten Photos oder None
        
    Dict-Keys:
        - photos: Liste von Photo-Metadaten
        - temp_dir: Temporäres Verzeichnis mit umbenannten Assets
        - missing_gps_count: Anzahl Photos ohne GPS
        - successful_uploads: Anzahl erfolgreicher Uploads
    """
    try:
        # ====================================================================
        # INITIALISIERUNG
        # ====================================================================
        logger.info(f"Suche JPEG-Dateien in: {input_dir}")
        jpg_files = get_jpg_files(input_dir, recursive=False)
        total = len(jpg_files)
        logger.info(f"  Gefunden: {total} JPEG-Dateien")
        
        # Temporäres Verzeichnis für umbenannte Assets erstellen
        temp_dir = output_dir / "temp_photos"
        temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"  Temp-Verzeichnis: {temp_dir}")
        
        # Importiere STAC-Publisher (verwendet intern proxy_handler)
        if upload_enabled:
            from utilities.stac_publisher import publish_to_stac_wrapper
        
        # ====================================================================
        # FOTOS VERARBEITEN
        # ====================================================================
        logger.info("\n" + "=" * 70)
        logger.info("VERARBEITE PHOTOS MIT DIREKTEM UPLOAD")
        logger.info("=" * 70)
        
        photos = []
        missing_gps = 0
        successful_uploads = 0
        
        for idx, jpg_file in enumerate(jpg_files, 1):
            logger.info(f"\n[{idx}/{total}] {jpg_file.name}")
            logger.info("-" * 70)
            
            try:
                # ============================================================
                # SCHRITT 1: EXIF-DATEN EXTRAHIEREN
                # ============================================================
                logger.info("  1️⃣  Extrahiere EXIF-Daten (gdalinfo)...")
                lat, lon, exif_timestamp = extract_exif_data(jpg_file)
                
                if lat is None or lon is None:
                    logger.warning(f"     ⚠ Keine GPS-Daten gefunden")
                    missing_gps += 1
                else:
                    logger.info(f"     ✓ GPS: {lat:.6f}, {lon:.6f}")
                
                if exif_timestamp:
                    logger.info(f"     ✓ Zeitstempel: {exif_timestamp}")
                
                # ============================================================
                # SCHRITT 2: ITEM-NAME UND ASSET-NAME GENERIEREN
                # ============================================================
                # Zeitstempel für Item-Name: exif tiemstamp + Index
                dt = datetime.strptime(exif_timestamp, "%Y:%m:%d %H:%M:%S")
                timestamp = dt.strftime("%Y-%m-%dt%H%M%S").lower()
                
                
                # Item-Name generieren (z.B. "ram-ebn-2024-12-21t123456")
                item_name = generate_item_name(timestamp, product_type)
                
                # Asset-Name generieren (z.B. "ebn-2024-12-21t123456.jpg")
                # Extrahiere Zeitstempel aus Item-Name (nach "ram-")
                #timestamp_part = item_name.split('ram-')[1] if 'ram-' in item_name else timestamp
                #asset_name = generate_asset_name(timestamp_part, product_type)
                asset_name = item_name
                
                logger.info(f"  2️⃣  Item-Name: {item_name}")
                logger.info(f"     Asset-Name: {asset_name}")
                
                # ============================================================
                # SCHRITT 3: ORIGINAL-FOTO IN TEMP_DIR KOPIEREN UND UMBENENNEN
                # ============================================================
                logger.info(f"  3️⃣  Kopiere und benenne Foto um...")
                
                # Pfad für umbenanntes Foto in temp_dir
                temp_photo_path = temp_dir / (asset_name + jpg_file.suffix)
                
                # Kopiere Original-Foto nach temp_dir mit neuem Namen
                shutil.copy2(jpg_file, temp_photo_path)
                logger.info(f"     ✓ Foto kopiert: {temp_photo_path.name}")
                
                # ============================================================
                # SCHRITT 4: THUMBNAIL ERSTELLEN UND IN TEMP_DIR SPEICHERN
                # ============================================================
                logger.info(f"  4️⃣  Erstelle Thumbnail (gdal_translate)...")
                
                # Thumbnail-Name: immer "thumbnail.jpg" gemäß STAC-Konvention
                temp_thumbnail_path = temp_dir / "thumbnail.jpg"
                
                # Erstelle Thumbnail vom umbenannten Foto
                thumbnail_success = resize_image_gdal(
                    temp_photo_path,
                    temp_thumbnail_path,
                    max_width=THUMBNAIL_CONFIG['max_width'],
                    max_height=THUMBNAIL_CONFIG['max_height']
                )
                
                if thumbnail_success:
                    thumb_size = temp_thumbnail_path.stat().st_size
                    logger.info(f"     ✓ Thumbnail erstellt: {temp_thumbnail_path.name} ({thumb_size} bytes)")
                else:
                    logger.warning(f"     ⚠ Thumbnail-Erstellung fehlgeschlagen")
                    temp_thumbnail_path = None
                
                # ============================================================
                # SCHRITT 5: FOTO ZU STAC HOCHLADEN
                # ============================================================
                # WICHTIG: publish_to_stac_wrapper verwendet intern
                # proxy_handler.get_session() für Proxy-Konfiguration.
                # Es werden KEINE zusätzlichen Proxy-Tests durchgeführt!
                # ============================================================
                photo_upload_success = False
                thumbnail_upload_success = False
                
                if upload_enabled:
                    logger.info(f"  5️⃣  Lade Foto zu STAC hoch...")
                    logger.info(f"     → Upload als: {asset_name}")
                    
                    photo_upload_success = publish_to_stac_wrapper(
                        asset_path=temp_photo_path,
                        item_name=item_name,
                        collection=stac_collection,
                        geocat_id=geocat_id,
                        hostname=hostname,
                        asset_title=product_config['asset_title'],
                        environment=environment
                    )
                    
                    if photo_upload_success:
                        logger.info(f"     ✓ Foto erfolgreich hochgeladen")
                    else:
                        logger.error(f"     ✗ Foto-Upload fehlgeschlagen")
                    
                    # ========================================================
                    # SCHRITT 6: THUMBNAIL ZU STAC HOCHLADEN
                    # ========================================================
                    if photo_upload_success and temp_thumbnail_path and temp_thumbnail_path.exists():
                        logger.info(f"  6️⃣  Lade Thumbnail zu STAC hoch...")
                        logger.info(f"     → Upload als: thumbnail.jpg")
                        
                        thumbnail_upload_success = publish_to_stac_wrapper(
                            asset_path=temp_thumbnail_path,
                            item_name=item_name,
                            collection=stac_collection,
                            geocat_id=geocat_id,
                            hostname=hostname,
                            asset_title="THUMBNAIL",
                            environment=environment
                        )
                        


                        if thumbnail_upload_success:
                            logger.info(f"     ✓ Thumbnail erfolgreich hochgeladen")
                        else:
                            logger.warning(f"     ⚠ Thumbnail-Upload fehlgeschlagen")
                    
                    # Zähle erfolgreiche Uploads
                    if photo_upload_success:
                        successful_uploads += 1
                    
                    # Cleanup: Lösche temporäre Dateien nach erfolgreichem Upload
                    if photo_upload_success:
                        temp_photo_path.unlink(missing_ok=True)
                        if temp_thumbnail_path and temp_thumbnail_path.exists():
                            temp_thumbnail_path.unlink(missing_ok=True)
                
                else:
                    logger.info(f"  ℹ️  Upload deaktiviert - Dateien verbleiben in {temp_dir}")
                
                # ============================================================
                # SCHRITT 7: ERST JETZT ZUR PHOTOS-LISTE HINZUFÜGEN
                # ============================================================
                photo_info = {
                    'original_path': jpg_file,
                    'temp_photo_path': temp_photo_path,
                    'temp_thumbnail_path': temp_thumbnail_path if thumbnail_success else None,
                    'item_name': item_name,
                    'asset_name': asset_name,
                    'original_filename': jpg_file.name,
                    'lat': lat,
                    'lon': lon,
                    'timestamp': exif_timestamp,
                    'photo_upload_success': photo_upload_success,
                    'thumbnail_upload_success': thumbnail_upload_success
                }
                
                photos.append(photo_info)
                
                # ============================================================
                # STATUS-AUSGABE FÜR DIESES FOTO
                # ============================================================
                logger.info("-" * 70)
                if upload_enabled:
                    if photo_upload_success and thumbnail_upload_success:
                        logger.info(f"✅ [{idx}/{total}] VOLLSTÄNDIG ERFOLGREICH")
                    elif photo_upload_success:
                        logger.info(f"⚠️  [{idx}/{total}] TEILWEISE ERFOLGREICH (nur Foto)")
                    else:
                        logger.error(f"❌ [{idx}/{total}] UPLOAD FEHLGESCHLAGEN")
                else:
                    logger.info(f"✅ [{idx}/{total}] VERARBEITUNG ERFOLGREICH (kein Upload)")
                
            except Exception as e:
                logger.error(f"\n❌ FEHLER bei Foto {jpg_file.name}: {e}")
                import traceback
                traceback.print_exc()
                
                # Füge Fehlereintrag hinzu
                photos.append({
                    'original_path': jpg_file,
                    'original_filename': jpg_file.name,
                    'error': str(e),
                    'photo_upload_success': False,
                    'thumbnail_upload_success': False
                })
        
        # ====================================================================
        # ZUSAMMENFASSUNG
        # ====================================================================
        logger.info("\n" + "=" * 70)
        logger.info("📊 VERARBEITUNGSZUSAMMENFASSUNG")
        logger.info("=" * 70)
        logger.info(f"Gesamt verarbeitet:      {len(photos)}/{total}")
        logger.info(f"Ohne GPS-Daten:          {missing_gps}")
        
        if upload_enabled:
            logger.info(f"Erfolgreich hochgeladen: {successful_uploads}/{total}")
            failed_uploads = total - successful_uploads
            if failed_uploads > 0:
                logger.warning(f"Fehlgeschlagen:          {failed_uploads}")
        else:
            logger.info(f"Upload:                  Deaktiviert")
        
        logger.info("=" * 70)
        
        return {
            'photos': photos,
            'temp_dir': temp_dir,
            'missing_gps_count': missing_gps,
            'successful_uploads': successful_uploads if upload_enabled else 0
        }
        
    except Exception as e:
        logger.error(f"✗ Fehler in Photo-Verarbeitung: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None