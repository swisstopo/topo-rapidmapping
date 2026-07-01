"""
Datei- und Verzeichnis-Operationen.

Funktionen für Validierung, Suche und Verwaltung von Dateien.
"""

import os
import shutil
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Unterstützte Bildformate
SUPPORTED_IMAGE_EXTENSIONS = {'.tif', '.tiff', '.jpg', '.jpeg'}


def validate_directory(directory: str) -> Path:
    """
    Validiert ob ein Verzeichnis existiert.
    
    Args:
        directory (str): Pfad zum Verzeichnis
        
    Returns:
        Path: Validierter Pfad als Path-Objekt
        
    Raises:
        ValueError: Wenn Eingabe leer ist
        FileNotFoundError: Wenn Verzeichnis nicht existiert
    """
    if not directory or not directory.strip():
        raise ValueError("Verzeichnis-Pfad darf nicht leer sein")
    
    path = Path(directory.strip())
    
    if not path.exists():
        raise FileNotFoundError(
            f"Verzeichnis existiert nicht: {path}\n"
            f"Bitte korrekten Pfad angeben."
        )
    
    if not path.is_dir():
        raise ValueError(f"Pfad ist kein Verzeichnis: {path}")
    
    return path


def get_image_files(
    directory: Path,
    extensions: set = None,
    recursive: bool = False
) -> List[Path]:
    """
    Findet alle Bilddateien in einem Verzeichnis.
    
    Args:
        directory (Path): Verzeichnis zum Durchsuchen
        extensions (set, optional): Zu suchende Datei-Extensions.
                                   Default: SUPPORTED_IMAGE_EXTENSIONS
        recursive (bool): Rekursiv in Unterverzeichnissen suchen
        
    Returns:
        List[Path]: Liste der gefundenen Bilddateien
        
    Raises:
        ValueError: Wenn keine Bilddateien gefunden wurden
    """
    if extensions is None:
        extensions = SUPPORTED_IMAGE_EXTENSIONS
    
    # Normalisiere Extensions zu lowercase
    extensions = {ext.lower() for ext in extensions}
    
    pattern = '**/*' if recursive else '*'
    
    # Sammle alle Dateien und filtere nach Extension
    files = []
    for file_path in directory.glob(pattern):
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            files.append(file_path)
    
    # Sortiere nach Namen
    files = sorted(files)
    
    if not files:
        raise ValueError(
            f"Keine Bilddateien gefunden in: {directory}\n"
            f"Unterstützte Formate: {', '.join(extensions)}\n"
            f"Rekursive Suche: {'Ja' if recursive else 'Nein'}"
        )
    
    logger.info(f"✓ {len(files)} Bilddatei(en) gefunden in {directory}")
    return files


def get_tif_files(directory: Path, recursive: bool = False) -> List[Path]:
    """
    Findet alle TIFF-Dateien in einem Verzeichnis.
    
    Args:
        directory (Path): Verzeichnis zum Durchsuchen
        recursive (bool): Rekursiv suchen
        
    Returns:
        List[Path]: Liste der TIFF-Dateien
    """
    return get_image_files(
        directory,
        extensions={'.tif', '.tiff'},
        recursive=recursive
    )


def get_jpg_files(directory: Path, recursive: bool = False) -> List[Path]:
    """
    Findet alle JPEG-Dateien in einem Verzeichnis.
    
    Args:
        directory (Path): Verzeichnis zum Durchsuchen
        recursive (bool): Rekursiv suchen
        
    Returns:
        List[Path]: Liste der JPEG-Dateien
    """
    return get_image_files(
        directory,
        extensions={'.jpg', '.jpeg'},
        recursive=recursive
    )


def create_file_list(files: List[Path], output_file: Path) -> Path:
    """
    Erstellt eine Textdatei mit Liste von Dateipfaden.
    
    Args:
        files (List[Path]): Liste der Dateipfade
        output_file (Path): Ausgabe-Datei
        
    Returns:
        Path: Pfad zur erstellten Datei
        
    Raises:
        IOError: Bei Schreibfehlern
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for file in files:
                f.write(f"{file}\n")
        
        logger.info(f"✓ File-Liste erstellt: {output_file} ({len(files)} Einträge)")
        return output_file
        
    except Exception as e:
        raise IOError(f"Fehler beim Erstellen der File-Liste: {e}")


def cleanup_temp_directory(temp_dir: Path, keep_on_error: bool = True):
    """
    Löscht temporäres Verzeichnis nach erfolgreicher Verarbeitung.
    
    Args:
        temp_dir (Path): Zu löschendes Verzeichnis
        keep_on_error (bool): Bei Fehlern Verzeichnis behalten für Debugging
    """
    try:
        if temp_dir.exists() and temp_dir.is_dir():
            shutil.rmtree(temp_dir)
            logger.info(f"✓ Temporäres Verzeichnis gelöscht: {temp_dir}")
    except Exception as e:
        if keep_on_error:
            logger.warning(
                f"! Konnte Temp-Verzeichnis nicht löschen: {e}\n"
                f" Verzeichnis bleibt für Debugging erhalten: {temp_dir}"
            )
        else:
            logger.error(f"✗ Fehler beim Löschen von Temp-Verzeichnis: {e}")


def ensure_directory_exists(directory: Path) -> Path:
    """
    Stellt sicher dass ein Verzeichnis existiert, erstellt es falls nötig.
    
    Args:
        directory (Path): Verzeichnis
        
    Returns:
        Path: Verzeichnis-Pfad
    """
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_file_size_mb(file_path: Path) -> float:
    """
    Gibt Dateigröße in Megabytes zurück.
    
    Args:
        file_path (Path): Dateipfad
        
    Returns:
        float: Dateigröße in MB
    """
    size_bytes = file_path.stat().st_size
    return size_bytes / (1024 * 1024)


def validate_file_exists(file_path: Path) -> Path:
    """
    Validiert dass eine Datei existiert.
    
    Args:
        file_path (Path): Dateipfad
        
    Returns:
        Path: Validierter Pfad
        
    Raises:
        FileNotFoundError: Wenn Datei nicht existiert
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")
    
    if not file_path.is_file():
        raise ValueError(f"Pfad ist keine Datei: {file_path}")
    
    return file_path