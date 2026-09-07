"""
Credentials Management für STAC API mit INT/PROD-Unterstützung.

Unterstützt mehrere Quellen mit Priorität:
1. Environment Variables (STAC_USERNAME, STAC_PASSWORD)
2. JSON Config File (secrets/stac_credentials.json) mit INT/PROD
"""

import json
import os
import sys
import logging
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def _get_app_base_dir() -> Path:
    """
    Basisverzeichnis der Anwendung — unabhängig vom Arbeitsverzeichnis (cwd)
    des aufrufenden Prozesses. Siehe utilities/proxy_handler.py für Details.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


DEFAULT_CREDENTIALS_PATH = _get_app_base_dir() / "secrets" / "stac_credentials.json"


def load_credentials_from_file(filepath: Path, environment: str = "INT") -> Tuple[str, str, str]:
    """
    Lädt Credentials aus JSON-Datei für spezifisches Environment.
    
    Args:
        filepath (Path): Pfad zur Credentials-Datei
        environment (str): "INT" oder "PROD"
        
    Returns:
        Tuple[str, str, str]: (username, password, hostname)
        
    Raises:
        FileNotFoundError: Wenn Datei nicht existiert
        ValueError: Wenn Datei ungültig ist oder Credentials fehlen
        
    Expected JSON format:
        {
            "INT": {
                "username": "int_username",
                "password": "int_password",
                "hostname": "sys-data.int.bgdi.ch"
            },
            "PROD": {
                "username": "prod_username",
                "password": "prod_password",
                "hostname": "data.geo.admin.ch"
            }
        }
    """
    if not filepath.exists():
        raise FileNotFoundError(
            f"Credentials-Datei nicht gefunden: {filepath}\n"
            f"Bitte erstellen Sie die Datei mit folgendem Format:\n"
            f'{{\n'
            f'  "INT": {{\n'
            f'    "username": "your_int_username",\n'
            f'    "password": "your_int_password",\n'
            f'    "hostname": "sys-data.int.bgdi.ch"\n'
            f'  }},\n'
            f'  "PROD": {{\n'
            f'    "username": "your_prod_username",\n'
            f'    "password": "your_prod_password",\n'
            f'    "hostname": "data.geo.admin.ch"\n'
            f'  }}\n'
            f'}}'
        )
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Prüfe ob Environment existiert
        if environment not in config:
            raise ValueError(
                f"Environment '{environment}' nicht in Credentials-Datei gefunden.\n"
                f"Verfügbare Environments: {list(config.keys())}"
            )
        
        env_config = config[environment]
        
        username = env_config.get('username')
        password = env_config.get('password')
        hostname = env_config.get('hostname')
        
        if not username or not password:
            raise ValueError(
                f"Username oder Password fehlt für Environment '{environment}'"
            )
        
        if not hostname:
            raise ValueError(
                f"Hostname fehlt für Environment '{environment}'"
            )
        
        return username, password, hostname
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Ungültige JSON-Datei: {e}")
    except Exception as e:
        raise ValueError(f"Fehler beim Lesen der Credentials: {e}")


def load_credentials_from_env() -> Tuple[str, str]:
    """
    Lädt Credentials aus Environment Variables.
    
    Hostname wird nicht aus Env geladen - nur Username/Password.
    
    Returns:
        Tuple[str, str]: (username, password)
        
    Raises:
        ValueError: Wenn Environment Variables nicht gesetzt sind
    """
    username = os.environ.get('STAC_USERNAME')
    password = os.environ.get('STAC_PASSWORD')
    
    if not username or not password:
        raise ValueError(
            "STAC_USERNAME und/oder STAC_PASSWORD Environment Variables nicht gesetzt"
        )
    
    return username, password


def load_stac_credentials(
    credentials_path: Path = None,
    environment: str = "INT"
) -> Tuple[str, str, str]:
    """
    Lädt STAC Credentials mit Priorität: Environment > Config File.
    
    Args:
        credentials_path (Path, optional): Pfad zur Credentials-Datei.
                                          Default: secrets/stac_credentials.json
        environment (str): "INT" oder "PROD" (default: "INT")
        
    Returns:
        Tuple[str, str, str]: (username, password, hostname)
        
    Raises:
        ValueError: Wenn keine Credentials gefunden werden können
    """
    config_path = credentials_path or DEFAULT_CREDENTIALS_PATH
    
    # Priorität 1: Environment Variables (nur Username/Password)
    # Hostname kommt immer aus Config-Datei
    try:
        username, password = load_credentials_from_env()
        # Hostname aus Config-Datei holen
        _, _, hostname = load_credentials_from_file(config_path, environment)
        logger.info(f"✓ Credentials aus Environment Variables geladen (Environment: {environment})")
        return username, password, hostname
    except ValueError:
        pass  # Fallback zu Config File
    
    # Priorität 2: Config File
    try:
        username, password, hostname = load_credentials_from_file(config_path, environment)
        logger.info(f"✓ Credentials aus Config-Datei geladen: {config_path} (Environment: {environment})")
        return username, password, hostname
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"✗ Fehler beim Laden der Credentials: {str(e)}")
        raise ValueError(
            f"Keine Credentials für Environment '{environment}' gefunden.\n"
            "Bitte bereitstellen via:\n"
            "  1. Environment Variables: STAC_USERNAME, STAC_PASSWORD\n"
            f"  2. Config-Datei: {config_path}\n\n"
            "Beispiel Config-Datei (secrets/stac_credentials.json):\n"
            '{\n'
            '  "INT": {\n'
            '    "username": "your_int_username",\n'
            '    "password": "your_int_password",\n'
            '    "hostname": "sys-data.int.bgdi.ch"\n'
            '  },\n'
            '  "PROD": {\n'
            '    "username": "your_prod_username",\n'
            '    "password": "your_prod_password",\n'
            '    "hostname": "data.geo.admin.ch"\n'
            '  }\n'
            '}'
        )


