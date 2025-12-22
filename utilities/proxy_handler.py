"""
Proxy Detection und Konfiguration mit JSON-basierter Konfiguration.

Lädt Proxy-Einstellungen aus secrets/proxy_config.json und testet
automatisch alle konfigurierten Proxies.

WICHTIG: Diese Datei ist die EINZIGE Stelle für Proxy-Verwaltung!
Alle anderen Module verwenden nur die Funktionen aus diesem Modul.
"""

import json
import logging
import requests
import urllib3
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# GLOBALE PROXY-KONFIGURATION
# ============================================================================
# Diese Variable speichert die Proxy-Einstellungen nach der Initialisierung
# und wird von allen Modulen wiederverwendet
PROXY_CONFIG = {
    'enabled': False,
    'proxies': None,
    'session': None,
    'verify_ssl': True,
    'active_proxy': None,
    'initialized': False  # Markiert ob bereits initialisiert
}

# Default Settings (Fallback wenn keine Config-Datei vorhanden)
DEFAULT_PROXY_CONFIG = {
    'proxies': [
        {
            'name': 'Corporate Proxy',
            'url': 'http://proxy-bvcol.admin.ch:8080',
            'enabled': True
        }
    ],
    'test_url': 'https://data.geo.admin.ch/browser/index.html',
    'timeout': 5,
    'disable_ssl_warnings': True
}

PROXY_CONFIG_PATH = Path("secrets") / "proxy_config.json"


def load_proxy_config() -> Dict:
    """
    Lädt Proxy-Konfiguration aus JSON-Datei.
    
    Returns:
        Dict: Proxy-Konfiguration oder Default-Config
    """
    if not PROXY_CONFIG_PATH.exists():
        logger.info(f"  ℹ Keine Proxy-Config gefunden: {PROXY_CONFIG_PATH}")
        logger.info(f"  ℹ Verwende Default-Konfiguration")
        return DEFAULT_PROXY_CONFIG
    
    try:
        with open(PROXY_CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        logger.info(f"  ✓ Proxy-Config geladen: {PROXY_CONFIG_PATH}")
        return config
        
    except Exception as e:
        logger.warning(f"  ⚠ Fehler beim Laden der Proxy-Config: {e}")
        logger.info(f"  ℹ Verwende Default-Konfiguration")
        return DEFAULT_PROXY_CONFIG


def get_enabled_proxies(config: Dict) -> List[Dict]:
    """
    Filtert aktivierte Proxies aus Konfiguration.
    
    Args:
        config (Dict): Proxy-Konfiguration
        
    Returns:
        List[Dict]: Liste der aktivierten Proxies
    """
    proxies = config.get('proxies', [])
    enabled = [p for p in proxies if p.get('enabled', True)]
    return enabled


def test_connection(
    test_url: str,
    proxies: Optional[Dict] = None,
    verify_ssl: bool = True,
    timeout: int = 5
) -> bool:
    """
    Testet eine Verbindung (direkt oder über Proxy).
    
    Args:
        test_url (str): Test-URL
        proxies (Optional[Dict]): Proxy-Dictionary oder None für direkte Verbindung
        verify_ssl (bool): SSL-Verifikation aktivieren
        timeout (int): Timeout in Sekunden
        
    Returns:
        bool: True wenn Verbindung erfolgreich
    """
    try:
        response = requests.get(
            test_url,
            proxies=proxies,
            verify=verify_ssl,
            timeout=timeout
        )
        return response.status_code == 200
    except Exception:
        return False


def detect_proxy_requirement() -> Dict:
    """
    Erkennt automatisch ob ein Proxy benötigt wird.
    
    Testet in folgender Reihenfolge:
    1. Direkte Verbindung
    2. Alle konfigurierten Proxies (in Reihenfolge)
    
    Returns:
        Dict: Proxy-Konfiguration mit Keys:
              - enabled (bool): Proxy aktiviert
              - proxies (dict): Proxy-Dictionary für requests
              - session (requests.Session): Konfigurierte Session
              - verify_ssl (bool): SSL-Verifikation aktiv
              - active_proxy (str): Name des aktiven Proxies
              - initialized (bool): True (markiert als initialisiert)
              
    Raises:
        ConnectionError: Wenn keine Verbindung möglich ist
    """
    logger.info("Internet-Konnektivität wird getestet...")
    
    # Lade Proxy-Konfiguration
    config = load_proxy_config()
    test_url = config.get('test_url', DEFAULT_PROXY_CONFIG['test_url'])
    timeout = config.get('timeout', DEFAULT_PROXY_CONFIG['timeout'])
    disable_ssl_warnings = config.get('disable_ssl_warnings', True)
    
    if disable_ssl_warnings:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Test 1: Direkte Verbindung
    logger.info(f"  [1/N] Teste direkte Verbindung zu {test_url}...")
    if test_connection(test_url, proxies=None, verify_ssl=True, timeout=timeout):
        logger.info("  ✓ Direkte Internet-Verbindung verfügbar (kein Proxy benötigt)")
        session = requests.Session()
        session.verify = True
        return {
            'enabled': False,
            'proxies': None,
            'session': session,
            'verify_ssl': True,
            'active_proxy': None,
            'initialized': True
        }
    else:
        logger.info("  ✗ Direkte Verbindung fehlgeschlagen")
    
    # Test 2: Alle konfigurierten Proxies
    enabled_proxies = get_enabled_proxies(config)
    
    if not enabled_proxies:
        logger.error("  ✗ Keine Proxies konfiguriert oder aktiviert")
        raise ConnectionError(
            "Keine Internet-Verbindung möglich.\n"
            f"Direkte Verbindung zu {test_url} fehlgeschlagen.\n"
            f"Keine Proxies in {PROXY_CONFIG_PATH} aktiviert.\n"
            "Bitte Netzwerk-Einstellungen oder Proxy-Config prüfen."
        )
    
    for idx, proxy_info in enumerate(enabled_proxies, 2):
        proxy_name = proxy_info.get('name', 'Unbekannt')
        proxy_url = proxy_info.get('url')
        
        if not proxy_url:
            logger.warning(f"  ⚠ Proxy '{proxy_name}': Keine URL konfiguriert")
            continue
        
        logger.info(f"  [{idx}/{len(enabled_proxies)+1}] Teste Proxy '{proxy_name}': {proxy_url}")
        
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
        
        # Test mit SSL-Verifikation deaktiviert (typisch für Corporate Proxies)
        if test_connection(test_url, proxies=proxies, verify_ssl=False, timeout=timeout):
            logger.warning(f"  ⚠ Verbindung über Proxy '{proxy_name}' erfolgreich (SSL-Verifikation deaktiviert)")
            
            session = requests.Session()
            session.proxies.update(proxies)
            session.verify = False  # CRITICAL: Set verify to False for corporate proxies
            
            return {
                'enabled': True,
                'proxies': proxies,
                'session': session,
                'verify_ssl': False,  # CRITICAL: Flag to indicate SSL is disabled
                'active_proxy': proxy_name,
                'initialized': True
            }
        else:
            logger.info(f"  ✗ Proxy '{proxy_name}' fehlgeschlagen")
    
    # Alle Tests fehlgeschlagen
    logger.error("  ✗ Keine Internet-Verbindung möglich")
    raise ConnectionError(
        "Keine Internet-Verbindung möglich.\n"
        f"Versucht: Direkte Verbindung + {len(enabled_proxies)} Proxy(s)\n"
        f"Test-URL: {test_url}\n"
        f"Proxy-Config: {PROXY_CONFIG_PATH}\n"
        "Bitte Netzwerk-Einstellungen prüfen."
    )


def initialize_proxy():
    """
    Initialisiert Proxy-Konfiguration und speichert in PROXY_CONFIG.
    
    Diese Funktion:
    1. Prüft ob bereits initialisiert (falls ja, überspringt Tests)
    2. Führt Proxy-Tests durch
    3. Speichert Ergebnisse in globaler PROXY_CONFIG
    
    Sollte beim Programmstart aufgerufen werden.
    
    Raises:
        ConnectionError: Wenn keine Internet-Verbindung möglich ist
    """
    global PROXY_CONFIG
    
    # ========================================================================
    # PRÜFE OB BEREITS INITIALISIERT
    # ========================================================================
    if PROXY_CONFIG.get('initialized', False):
        logger.info("ℹ️  Proxy bereits initialisiert, verwende gespeicherte Einstellungen")
        logger.info("=" * 70)
        if PROXY_CONFIG['enabled']:
            logger.info("Proxy-Konfiguration:")
            logger.info(f"  Aktiver Proxy: {PROXY_CONFIG['active_proxy']}")
            logger.info(f"  Proxy-URL: {PROXY_CONFIG['proxies']['http']}")
            logger.info(f"  SSL-Verifikation: {'Deaktiviert' if not PROXY_CONFIG['verify_ssl'] else 'Aktiviert'}")
        else:
            logger.info("Keine Proxy-Konfiguration erforderlich")
        logger.info("=" * 70)
        return
    
    # ========================================================================
    # FÜHRE PROXY-TESTS DURCH (nur beim ersten Aufruf)
    # ========================================================================
    config = detect_proxy_requirement()
    PROXY_CONFIG.update(config)
    
    logger.info("=" * 70)
    if PROXY_CONFIG['enabled']:
        logger.info("Proxy-Konfiguration:")
        logger.info(f"  Aktiver Proxy: {PROXY_CONFIG['active_proxy']}")
        logger.info(f"  Proxy-URL: {PROXY_CONFIG['proxies']['http']}")
        logger.info(f"  SSL-Verifikation: {'Deaktiviert' if not PROXY_CONFIG['verify_ssl'] else 'Aktiviert'}")
    else:
        logger.info("Keine Proxy-Konfiguration erforderlich")
    logger.info("=" * 70)


def get_session() -> requests.Session:
    """
    Gibt die konfigurierte requests Session zurück.
    
    Falls Proxy noch nicht initialisiert wurde, wird initialize_proxy() aufgerufen.
    
    Returns:
        requests.Session: Konfigurierte Session (mit oder ohne Proxy)
    """
    global PROXY_CONFIG
    
    # Falls noch nicht initialisiert, initialisiere jetzt
    if not PROXY_CONFIG.get('initialized', False):
        logger.warning("⚠️  Proxy noch nicht initialisiert - initialisiere jetzt...")
        initialize_proxy()
    
    if PROXY_CONFIG['session'] is None:
        raise RuntimeError(
            "Session konnte nicht erstellt werden. Bitte Netzwerk-Verbindung prüfen."
        )
    
    return PROXY_CONFIG['session']


def get_proxy_config() -> Dict:
    """
    Gibt die aktuelle Proxy-Konfiguration zurück.
    
    Falls Proxy noch nicht initialisiert wurde, wird initialize_proxy() aufgerufen.
    
    Returns:
        Dict: Proxy-Konfiguration mit Keys:
              - enabled (bool): Proxy aktiviert
              - proxies (dict): Proxy-Dictionary für requests
              - session (requests.Session): Konfigurierte Session
              - verify_ssl (bool): SSL-Verifikation aktiv
              - active_proxy (str): Name des aktiven Proxies
              - initialized (bool): Initialisierungs-Status
    """
    global PROXY_CONFIG
    
    # Falls noch nicht initialisiert, initialisiere jetzt
    if not PROXY_CONFIG.get('initialized', False):
        logger.warning("⚠️  Proxy noch nicht initialisiert - initialisiere jetzt...")
        initialize_proxy()
    
    return PROXY_CONFIG.copy()


def is_proxy_enabled() -> bool:
    """
    Prüft ob Proxy aktiviert ist.
    
    Falls Proxy noch nicht initialisiert wurde, wird initialize_proxy() aufgerufen.
    
    Returns:
        bool: True wenn Proxy aktiviert, False sonst
    """
    global PROXY_CONFIG
    
    # Falls noch nicht initialisiert, initialisiere jetzt
    if not PROXY_CONFIG.get('initialized', False):
        logger.warning("⚠️  Proxy noch nicht initialisiert - initialisiere jetzt...")
        initialize_proxy()
    
    return PROXY_CONFIG['enabled']


def get_proxies_dict() -> Optional[Dict]:
    """
    Gibt das Proxies-Dictionary für requests.get/post zurück.
    
    Nützlich für direkte requests-Aufrufe außerhalb einer Session.
    
    Returns:
        Optional[Dict]: Proxies-Dictionary oder None wenn kein Proxy
    """
    config = get_proxy_config()
    return config.get('proxies')


def get_verify_ssl() -> bool:
    """
    Gibt zurück ob SSL-Verifikation aktiviert ist.
    
    Returns:
        bool: True wenn SSL-Verifikation aktiv, False sonst
    """
    config = get_proxy_config()
    return config.get('verify_ssl', True)