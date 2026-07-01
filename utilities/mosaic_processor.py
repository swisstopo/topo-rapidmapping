"""
Orthophoto Mosaic Processing - Single File Check Only.

Prüft ob im angegebenen Verzeichnis ein COG-Tiff mit 8-bit RGB (3 Bänder) vorhanden ist.
Falls ja: Kopiere Datei und erstelle Thumbnail.
Falls nein: Fehler - User muss COG-Tiff vorbereiten.
"""

import os
import subprocess
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

from configuration import COG_CONFIG, THUMBNAIL_CONFIG
from utilities.file_handler import (
    get_tif_files,
    get_file_size_mb
)

logger = logging.getLogger(__name__)


def check_is_cog(file_path: Path) -> bool:
    """
    Prüft ob eine Datei ein Cloud Optimized GeoTIFF (COG) ist.
    Verwendet gdalinfo via subprocess.
    
    Args:
        file_path (Path): Pfad zur TIF-Datei
        
    Returns:
        bool: True wenn COG, False sonst
    """
    try:
        result = subprocess.run(
            ['gdalinfo', '-json', str(file_path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return False
        
        info = json.loads(result.stdout)
        metadata = info.get('metadata', {}).get('IMAGE_STRUCTURE', {})
        
        # Prüfe Tile-Layout
        is_tiled = 'LAYOUT' in metadata or metadata.get('INTERLEAVE') == 'PIXEL'
        
        # Prüfe Overviews (Pyramiden)
        bands = info.get('bands', [])
        has_overviews = False
        if bands:
            has_overviews = bands[0].get('overviews', []) != []
        
        # COG sollte beides haben
        return is_tiled and has_overviews
        
    except Exception as e:
        logger.warning(f" ! COG-Check Fehler: {e}")
        return False


def check_is_8bit_rgb(file_path: Path) -> bool:
    """
    Prüft ob eine Datei 8-bit RGB (3 Bänder) ist.
    Verwendet gdalinfo via subprocess.
    
    Args:
        file_path (Path): Pfad zur Raster-Datei
        
    Returns:
        bool: True wenn 8-bit RGB, False sonst
    """
    try:
        result = subprocess.run(
            ['gdalinfo', '-json', str(file_path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return False
        
        info = json.loads(result.stdout)
        
        # Prüfe Anzahl Bänder
        bands = info.get('bands', [])
        if len(bands) != 3:
            logger.info(f"  ✗ Hat {len(bands)} Bänder (erwartet: 3)")
            return False
        
        # Prüfe Datatype aller Bänder (sollte 'Byte' = 8-bit sein)
        for band in bands:
            dtype = band.get('type')
            if dtype != 'Byte':
                logger.info(f"  ✗ Band-Typ ist '{dtype}' (erwartet: 'Byte' für 8-bit)")
                return False
        
        return True
        
    except Exception as e:
        logger.warning(f" ! 8-bit RGB Check Fehler: {e}")
        return False


def create_thumbnail_from_cog(
    input_file: Path,
    output_file: Path,
    max_size: int = 256
) -> bool:
    """
    Creates a thumbnail while maintaining aspect ratio using only subprocess calls.
    Ensures neither width nor height exceeds max_size.
    """
    try:
        logger.info(f" Analysing dimensions for: {input_file.name}")

        # 1. Get image dimensions using gdalinfo -json
        info_proc = subprocess.run(
            ['gdalinfo', '-json', str(input_file)],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
        )
        
        info_data = json.loads(info_proc.stdout)
        width, height = info_data['size']

        # 2. Logic: Fit the longest side to max_size, auto-scale the other
        if width >= height:
            # Landscape or Square: Set width to max_size, height auto
            outsize_params = [str(max_size), '0']
        else:
            # Portrait: Set height to max_size, width auto
            outsize_params = ['0', str(max_size)]

        logger.info(f"  → Thumbnail: {output_file.name} ({outsize_params[0] or 'auto'}x{outsize_params[1] or 'auto'} px)")

        # 3. Run gdal_translate with progress output if supported by this build
        _help = subprocess.run(
            ['gdal_translate', '--help'], capture_output=True, text=True
        )
        _progress_flag = ['-progress'] if '-progress' in _help.stdout + _help.stderr else []

        result = subprocess.run(
            [
                'gdal_translate',
                '--config', 'NUM_THREADS', 'ALL_CPUS',
                '--config', 'GDAL_CACHEMAX', '512',
                '-of', 'JPEG',
                '-outsize', outsize_params[0], outsize_params[1],
            ] + _progress_flag + [
                str(input_file),
                str(output_file)
            ],
            stderr=subprocess.PIPE,
            timeout=60,
            env={**os.environ, 'GDAL_PAM_ENABLED': 'NO'}
        )

        if result.returncode == 0 and output_file.exists():
            logger.info(f"  ✓ Thumbnail erstellt: {output_file}")
            return True

        if result.stderr:
            logger.error(f"  ✗ GDAL Process Error: {result.stderr.decode(errors='replace').strip()}")
        return False

    except Exception as e:
        logger.error(f"  ✗ Thumbnail-Fehler: {e}")
        return False


def process_single_cog_file(
    input_dir: Path,
    output_dir: Path,
    filename: str
) -> Optional[Path]:
    """
    Prüft ob im Input-Verzeichnis genau 1 COG-Tiff mit 8-bit RGB existiert.
    Falls ja: Kopiere Datei und erstelle Thumbnail.
    
    Args:
        input_dir (Path): Verzeichnis mit Input-TIFFs
        output_dir (Path): Output-Verzeichnis
        filename (str): Output-Dateiname (ohne Extension)
        
    Returns:
        Optional[Path]: Pfad zur kopierten COG-Datei oder None bei Fehler
    """
    try:
        # Input-Dateien finden
        logger.info(f"Suche TIFF-Dateien in: {input_dir}")
        input_files = get_tif_files(input_dir, recursive=False)
        logger.info(f" Gefunden: {len(input_files)} TIFF-Datei(en)")
        
        # Prüfe: Genau 1 Datei?
        if len(input_files) == 0:
            logger.error("✗ Keine TIFF-Dateien gefunden!")
            return None
        
        if len(input_files) > 1:
            logger.error(f"✗ Mehrere TIFF-Dateien gefunden ({len(input_files)})!")
            logger.error(" Dieser Workflow erwartet genau 1 COG-Tiff Datei.")
            logger.error(" Bitte Mosaik-Erstellung extern durchführen und nur COG bereitstellen.")
            return None
        
        single_file = input_files[0]
        logger.info(f"\n✓ Genau 1 Datei gefunden: {single_file.name}")
        
        # Prüfe: Ist COG?
        logger.info(" Prüfe ob COG...")
        if not check_is_cog(single_file):
            logger.error("  ✗ Datei ist KEIN Cloud Optimized GeoTIFF (COG)!")
            logger.error(" Bitte konvertiere zu COG mit:")
            logger.error(f"    gdal_translate -of COG -co COMPRESS=JPEG -co QUALITY=75 {single_file.name} output.tif")
            return None
        logger.info("  ✓ Ist COG")
        
        # Prüfe: Ist 8-bit RGB (3 Bänder)?
        logger.info(" Prüfe ob 8-bit RGB (3 Bänder)...")
        if not check_is_8bit_rgb(single_file):
            logger.error("  ✗ Datei ist NICHT 8-bit RGB mit 3 Bändern!")
            logger.error(" Erforderlich: 3 Bänder, Datatype 'Byte' (8-bit)")
            return None
        logger.info("  ✓ Ist 8-bit RGB (3 Bänder)")
        
        # Alles OK - Kopiere Datei
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{filename}.tif"
        
        logger.info(f"\n✓ Datei ist COG-konform - kopiere...")
        logger.info(f" Von: {single_file}")
        logger.info(f" Nach: {output_file}")
        
        shutil.copy2(single_file, output_file)
        
        size_mb = get_file_size_mb(output_file)
        logger.info(f"  ✓ Datei kopiert ({size_mb:.1f} MB)")
        
        # Erstelle Thumbnail (thumbnail.jpg)
        thumbnail_file = output_dir / "thumbnail.jpg"
        if create_thumbnail_from_cog(output_file, thumbnail_file, max_size=256):
            logger.info("  ✓ Thumbnail erstellt: thumbnail.jpg")
        else:
            logger.warning(" ! Thumbnail-Erstellung fehlgeschlagen (nicht kritisch)")
        
        logger.info("\n✓ Single-File-Processing erfolgreich abgeschlossen")
        return output_file
        
    except Exception as e:
        logger.error(f"✗ Fehler im Single-File-Processing: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None