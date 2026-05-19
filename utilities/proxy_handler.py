"""
Automatische Proxy-Erkennung und -Konfiguration.

Dieses Modul ist die zentrale Stelle für die Netzwerk-/Proxy-Verwaltung.
Alle anderen Module rufen nur die öffentlichen Funktionen aus diesem Modul auf.

Reihenfolge beim Start (detect_proxy_requirement):
  1. Direkte Verbindung — kein Proxy nötig (z.B. im Büronetz mit VPN-Client)
  2. System-Proxy (Windows-Registrierung / Umgebungsvariablen)
     → sofortiger Kerberos/SSPI-Versuch (Corporate-Proxies verlangen oft Negotiate)
     → Fallback: Verbindung ohne Auth (falls kein Kerberos benötigt)
  3. Proxies aus secrets/proxy_config.json (manuell konfiguriert)

Kerberos/SSPI (Corporate-Umgebungen):
  Viele Corporate-Proxies verlangen Windows-Negotiate-Authentifizierung.
  Das Modul erledigt das automatisch — der Benutzer muss nichts konfigurieren,
  solange er am Windows-Domain angemeldet ist und
  'requests-negotiate-sspi' installiert ist:
      pip install requests-negotiate-sspi

VPN-Erkennung:
  Erkennt automatisch ob ein VPN mit SSL-Inspection aktiv ist
  und deaktiviert in diesem Fall die SSL-Verifikation.
"""

import json
import logging
import urllib.request
import requests
import urllib3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    'initialized': False,
    'is_vpn': False,
    'auth_method': None,   # 'kerberos/negotiate-sspi' | 'kerberos/kerberos-proxy-auth' | None
}

# Thread-Lock: verhindert parallele Proxy-Initialisierung durch Worker-Threads
import threading as _threading
_PROXY_INIT_LOCK = _threading.Lock()


# Default Settings (Fallback wenn keine Config-Datei vorhanden)
DEFAULT_PROXY_CONFIG = {
    'proxies': [
        {
            'name': 'Default',
            'url': 'http://My.proxy.ch:8080',
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


def detect_vpn_connection(proxies: Optional[Dict] = None, test_urls: List[str] = None) -> bool:
    """
    Versucht zu erkennen ob eine VPN-Verbindung aktiv ist.
    
    Heuristik: Wenn Verbindung mit Proxy funktioniert, aber SSL-Verifikation
    deaktiviert werden muss, ist wahrscheinlich VPN mit SSL-Inspection aktiv.
    
    Args:
        proxies (Optional[Dict]): Proxy-Dictionary
        test_urls (List[str]): URLs zum Testen (default: data.geo.admin.ch + sys-data.int.bgdi.ch)
        
    Returns:
        bool: True wenn VPN vermutet wird
    """
    if test_urls is None:
        test_urls = [
            'https://data.geo.admin.ch/browser/index.html',
            'https://sys-data.int.bgdi.ch/api/stac/v0.9/'
        ]
    
    if proxies:
        # Teste mehrere URLs - wenn IRGENDEINE SSL-Probleme hat, ist es VPN
        for test_url in test_urls:
            # Test 1: Mit Proxy und SSL-Verifikation
            works_with_ssl = test_connection(test_url, proxies=proxies, verify_ssl=True, timeout=3)
            
            # Test 2: Mit Proxy ohne SSL-Verifikation
            works_without_ssl = test_connection(test_url, proxies=proxies, verify_ssl=False, timeout=3)
            
            # Wenn nur ohne SSL funktioniert -> VPN mit SSL-Inspection
            if works_without_ssl and not works_with_ssl:
                logger.info(f"  ℹ VPN-Verbindung mit SSL-Inspection erkannt (getestet mit {test_url})")
                return True
    
    return False


def _get_system_proxy_urls() -> List[str]:
    """
    Read proxy URLs from all available sources:
      1. urllib.request.getproxies()  — OS registry + standard env vars
      2. Direct env var scan          — catches GDAL/QGIS and non-standard names
    Returns a deduplicated list ordered https-first.
    """
    import os

    raw = urllib.request.getproxies()

    # Scan environment variables directly for proxy-related keys.
    # Covers: HTTP_PROXY, HTTPS_PROXY, GDAL_HTTP_PROXY, ALL_PROXY, etc.
    _proxy_env_keys = (
        'https_proxy', 'http_proxy', 'all_proxy',
        'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY',
        'GDAL_HTTP_PROXY', 'GDAL_HTTPS_PROXY',
        'gdal_http_proxy', 'gdal_https_proxy',
    )
    env_proxies: dict = {}
    for key in _proxy_env_keys:
        val = os.environ.get(key)
        if val:
            env_proxies[key] = val

    seen: set = set()
    result: List[str] = []

    # Priority: urllib result first (https before http), then env scan
    for key in ('https', 'http', 'gdal_https', 'gdal_http'):
        url = raw.get(key)
        if url and url not in seen:
            seen.add(url)
            result.append(url)

    for url in env_proxies.values():
        if url and url not in seen:
            seen.add(url)
            result.append(url)

    return result


def _make_kerberos_session(
    proxies_dict: Optional[Dict],
    verify_ssl: bool,
) -> Tuple[Optional[requests.Session], Optional[str]]:
    """
    Try to build a requests Session with Kerberos/SSPI proxy authentication.

    Tries in order:
      1. requests-negotiate-sspi  — Windows SSPI; works on domain-joined machines
                                    with no extra configuration.
      2. kerberos-proxy-auth      — cross-platform alternative.

    Returns (session, method_name) or (None, None) if no library is installed.
    Install hint is logged once so the user knows how to fix it.
    """
    # Option 1: Windows SSPI (preferred)
    try:
        from requests_negotiate_sspi import HttpNegotiateAuth
        session = requests.Session()
        if proxies_dict:
            session.proxies.update(proxies_dict)
        session.verify = verify_ssl
        session.auth = HttpNegotiateAuth()
        return session, "negotiate-sspi"
    except ImportError:
        pass

    # Option 2: cross-platform kerberos
    try:
        import kerberos_proxy_auth  # noqa: F401
        kerberos_proxy_auth.install()   # patches requests globally
        session = requests.Session()
        if proxies_dict:
            session.proxies.update(proxies_dict)
        session.verify = verify_ssl
        return session, "kerberos-proxy-auth"
    except ImportError:
        pass

    logger.warning(
        "  ⚠ Kerberos-Bibliothek nicht installiert.\n"
        "    Für Windows (Domäne):  pip install requests-negotiate-sspi\n"
        "    Plattformübergreifend: pip install kerberos-proxy-auth"
    )
    return None, None


def _install_kerberos_tunnel_patch():
    """
    Stellt sicher dass HTTPS-Verbindungen durch einen Kerberos-Proxy funktionieren.

    Hintergrund:
      HTTPS durch einen HTTP-Proxy erfordert einen CONNECT-Tunnel.
      Ältere urllib3-Versionen (die in PyInstaller-EXEs gebündelt werden)
      brechen sofort mit OSError ab wenn der Proxy 407 zurückschickt — bevor
      eine Kerberos-Authentifizierung stattfinden kann.

    Lösung:
      Der Kerberos-Token wird VOR dem ersten CONNECT-Versuch generiert und
      direkt in den CONNECT-Request injiziert. So antwortet der Proxy nie mit
      407, der Socket bleibt gültig und urllib3 kann SSL normal abwickeln.

    Thread-safe: Token-Objekte werden pro Aufruf lokal erstellt.
    Idempotent: wird nur einmal installiert (bewacht durch _kerberos_patched).
    """
    import http.client
    import base64 as _b64

    if getattr(http.client.HTTPConnection, '_kerberos_patched', False):
        return  # Already installed

    _orig_tunnel = http.client.HTTPConnection._tunnel

    def _negotiate_token(proxy_host: str) -> str:
        """
        Generate a Kerberos/SSPI Negotiate token for the given proxy host.
        Returns the base64-encoded token string, or '' on failure.

        Tries two backends in order:
          1. pywin32.sspi             — fastest; requires full pywin32 package
          2. requests_negotiate_sspi  — works with pywin32-ctypes (used in
                                        virtualenvs and PyInstaller exes that
                                        don't ship the full pywin32 package)
        """
        # ── Option 1: pywin32.sspi ────────────────────────────────────────────
        try:
            import sspi as _sspi
            auth = _sspi.ClientAuth('Negotiate', targetspn=f'HTTP/{proxy_host}')
            _, out_buf = auth.authorize(None)
            return _b64.b64encode(out_buf[0].Buffer).decode()
        except ImportError:
            pass  # pywin32 not available — try next option
        except Exception as _e:
            logger.debug(f'  SSPI pywin32 token error: {type(_e).__name__}: {_e}')

        # ── Option 2: requests_negotiate_sspi (works with pywin32-ctypes) ────
        # HttpNegotiateAuth generates the initial Negotiate token when called
        # with a PreparedRequest — even without a prior 407 challenge.
        try:
            import requests as _req
            from requests_negotiate_sspi import HttpNegotiateAuth
            prep = _req.Request('GET', f'http://{proxy_host}/').prepare()
            prep = HttpNegotiateAuth()(prep)
            header = prep.headers.get('Authorization', '')
            if header.startswith('Negotiate '):
                return header.split(' ', 1)[1]
        except Exception as _e:
            logger.debug(f'  SSPI requests_negotiate_sspi token error: {type(_e).__name__}: {_e}')

        logger.debug('  SSPI: all token backends failed — falling back to unauthenticated CONNECT')
        return ''  # no token available — caller falls back to unauthenticated

    def _sspi_tunnel(self):
        token = _negotiate_token(self.host)

        if not token:
            # No Kerberos token available; try unauthenticated (may hit 407)
            return _orig_tunnel(self)

        # Pre-inject the Negotiate token into the CONNECT request headers.
        # This avoids any 407/reconnect cycle and keeps self.sock intact for
        # the SSL wrap that urllib3 performs immediately after _tunnel() returns.
        saved_auth = self._tunnel_headers.pop('Proxy-Authorization', None)
        self._tunnel_headers['Proxy-Authorization'] = f'Negotiate {token}'
        try:
            return _orig_tunnel(self)
        finally:
            self._tunnel_headers.pop('Proxy-Authorization', None)
            if saved_auth is not None:
                self._tunnel_headers['Proxy-Authorization'] = saved_auth

    http.client.HTTPConnection._tunnel = _sspi_tunnel
    http.client.HTTPConnection._kerberos_patched = True
    logger.info(
        '  ℹ SSPI-Tunnel-Patch aktiv: CONNECT 407 → Kerberos Negotiate '
        '(urllib3-Kompatibilität für ältere GDAL/QGIS-Umgebungen)'
    )


def _probe_proxy(proxy_url: str, test_url: str, timeout: int) -> dict:
    """
    Test a proxy URL without authentication.

    Returns dict with:
      'status': 'ok'             — connection works
               'needs_kerberos'  — proxy returned 407 (auth required)
               'fail'            — unreachable or other error
      'verify_ssl': bool  (only present when status == 'ok')
    """
    proxies = {"http": proxy_url, "https": proxy_url}
    for verify in (True, False):
        try:
            r = requests.get(test_url, proxies=proxies, verify=verify, timeout=timeout)
            if r.status_code == 200:
                return {'status': 'ok', 'verify_ssl': verify}
        except requests.exceptions.ProxyError as e:
            if '407' in str(e):
                return {'status': 'needs_kerberos'}
        except Exception:
            pass
    return {'status': 'fail'}


def _probe_proxy_kerberos(proxy_url: str, test_url: str, timeout: int) -> dict:
    """
    Test a proxy URL with Kerberos/SSPI authentication.

    Returns dict with:
      'status': 'ok'     — authentication succeeded
               'no_lib'  — no Kerberos library installed
               'fail'    — library present but authentication failed
      'verify_ssl': bool, 'session': Session, 'method': str
      (only present when status == 'ok')
    """
    proxies = {"http": proxy_url, "https": proxy_url}
    for verify in (True, False):
        session, method = _make_kerberos_session(proxies, verify)
        if session is None:
            return {'status': 'no_lib'}
        try:
            r = session.get(test_url, timeout=timeout)
            if r.status_code == 200:
                return {'status': 'ok', 'verify_ssl': verify,
                        'session': session, 'method': method}
        except Exception:
            pass
    return {'status': 'fail'}


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
              - is_vpn (bool): True wenn VPN erkannt wurde
              
    Raises:
        ConnectionError: Wenn keine Verbindung möglich ist
    """
    logger.info("Internet-Konnektivität wird getestet...")

    config = load_proxy_config()
    test_url = config.get('test_url', DEFAULT_PROXY_CONFIG['test_url'])
    timeout  = config.get('timeout',  DEFAULT_PROXY_CONFIG['timeout'])

    if config.get('disable_ssl_warnings', True):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ── Helper: build a plain result dict ────────────────────────────────────
    def _ok(name: Optional[str], proxies_dict, verify: bool,
            session: requests.Session, is_vpn: bool = False,
            auth_method: Optional[str] = None) -> dict:
        return {
            'enabled':      proxies_dict is not None,
            'proxies':      proxies_dict,
            'session':      session,
            'verify_ssl':   verify,
            'active_proxy': name,
            'initialized':  True,
            'is_vpn':       is_vpn,
            'auth_method':  auth_method,
        }

    # ── Step 1: Direct connection ─────────────────────────────────────────────
    logger.info(f"  [1] Direkte Verbindung → {test_url} ...")
    if test_connection(test_url, proxies=None, verify_ssl=True, timeout=timeout):
        logger.info("  ✓ Direkte Verbindung OK (kein Proxy)")
        s = requests.Session()
        s.verify = True
        return _ok(None, None, True, s)
    logger.info("  ✗ Direkte Verbindung fehlgeschlagen")

    # ── Step 2: System proxy (OS / Windows registry / env vars) ──────────────
    # Strategy: always try Kerberos/SSPI first when a system proxy is found.
    # Corporate proxies often require Negotiate auth without sending a 407 first
    # (they just drop the connection). Kerberos auth on a non-auth proxy is harmless.
    system_proxies = _get_system_proxy_urls()
    if system_proxies:
        logger.info(f"  [2] System-Proxy gefunden: {system_proxies}")
        for proxy_url in system_proxies:
            proxies_dict = {"http": proxy_url, "https": proxy_url}

            # 2a: Try with Kerberos/SSPI upfront (works even if not required)
            session, method = _make_kerberos_session(proxies_dict, verify_ssl=False)
            if session is not None:
                logger.info(f"  ℹ System-Proxy: versuche Kerberos/{method} mit {proxy_url} ...")
                try:
                    r = session.get(test_url, timeout=timeout)
                    if r.status_code == 200:
                        logger.info(f"  ✓ System-Proxy OK (Kerberos/{method}): {proxy_url}")
                        _install_kerberos_tunnel_patch()
                        return _ok(f"system:{proxy_url} (kerberos/{method})",
                                   proxies_dict, False, session,
                                   auth_method=f"kerberos/{method}")
                except Exception:
                    pass
                logger.info(f"  ✗ Kerberos/{method} für System-Proxy fehlgeschlagen")

            # 2b: Fallback — plain probe (no auth)
            probe = _probe_proxy(proxy_url, test_url, timeout)
            if probe['status'] == 'ok':
                verify = probe['verify_ssl']
                s = requests.Session()
                s.proxies.update(proxies_dict)
                s.verify = verify
                logger.info(
                    f"  ✓ System-Proxy OK (ohne Auth): {proxy_url}"
                    + (" (VPN/SSL-Inspection erkannt)" if not verify else "")
                )
                return _ok(f"system:{proxy_url}", proxies_dict, verify, s, not verify)

            if probe['status'] == 'needs_kerberos':
                # 407 received but Kerberos already failed above → library issue
                logger.warning(
                    f"  ⚠ System-Proxy {proxy_url}: 407 und Kerberos fehlgeschlagen.\n"
                    "    pip install requests-negotiate-sspi  (Windows/AD empfohlen)"
                )
            else:
                logger.info(f"  ✗ System-Proxy {proxy_url} nicht erreichbar")
    else:
        logger.info("  [2] Keine System-Proxies in OS-Einstellungen gefunden")

    # ── Step 3: Configured proxies (secrets/proxy_config.json) ───────────────
    enabled_proxies = get_enabled_proxies(config)
    if not enabled_proxies:
        raise ConnectionError(
            "Keine Internet-Verbindung möglich.\n"
            f"Direkte Verbindung zu {test_url} fehlgeschlagen.\n"
            "Keine System-Proxies erkannt.\n"
            f"Keine Proxies in {PROXY_CONFIG_PATH} aktiviert.\n"
            "Bitte Netzwerk-Einstellungen oder Proxy-Config prüfen."
        )

    for idx, proxy_info in enumerate(enabled_proxies, 1):
        proxy_name = proxy_info.get('name', 'Unbekannt')
        proxy_url  = proxy_info.get('url')
        if not proxy_url:
            logger.warning(f"  ⚠ Proxy '{proxy_name}': Keine URL konfiguriert")
            continue

        logger.info(f"  [3.{idx}] Konfigurierter Proxy '{proxy_name}': {proxy_url}")
        probe = _probe_proxy(proxy_url, test_url, timeout)

        if probe['status'] == 'ok':
            verify = probe['verify_ssl']
            is_vpn = detect_vpn_connection(
                {"http": proxy_url, "https": proxy_url},
                test_urls=[test_url, 'https://sys-data.int.bgdi.ch/api/stac/v0.9/']
            )
            use_ssl = verify and not is_vpn
            s = requests.Session()
            s.proxies.update({"http": proxy_url, "https": proxy_url})
            s.verify = use_ssl
            logger.info(
                f"  ✓ Proxy '{proxy_name}' OK"
                + (" (VPN erkannt, SSL deaktiviert)" if is_vpn else
                   " (SSL aktiv)" if use_ssl else " (SSL deaktiviert)")
            )
            return _ok(proxy_name, {"http": proxy_url, "https": proxy_url},
                       use_ssl, s, is_vpn)

        if probe['status'] == 'needs_kerberos':
            logger.info(
                f"  ℹ Proxy '{proxy_name}' verlangt Kerberos-Auth (407) — versuche SSPI ..."
            )
            kprobe = _probe_proxy_kerberos(proxy_url, test_url, timeout)
            if kprobe['status'] == 'ok':
                logger.info(
                    f"  ✓ Proxy '{proxy_name}' OK (Kerberos/{kprobe['method']})"
                )
                _install_kerberos_tunnel_patch()
                return _ok(
                    f"{proxy_name} (kerberos/{kprobe['method']})",
                    {"http": proxy_url, "https": proxy_url},
                    kprobe['verify_ssl'],
                    kprobe['session'],
                    auth_method=f"kerberos/{kprobe['method']}"
                )
            if kprobe['status'] == 'no_lib':
                logger.warning(
                    f"  ⚠ Proxy '{proxy_name}' benötigt Kerberos, aber Bibliothek fehlt.\n"
                    "    pip install requests-negotiate-sspi   (Windows/AD empfohlen)\n"
                    "    pip install kerberos-proxy-auth        (plattformübergreifend)"
                )
            else:
                logger.info(
                    f"  ✗ Kerberos-Auth für Proxy '{proxy_name}' fehlgeschlagen"
                )
        else:
            logger.info(f"  ✗ Proxy '{proxy_name}' nicht erreichbar")

    logger.error("  ✗ Keine Internet-Verbindung möglich")
    raise ConnectionError(
        "Keine Internet-Verbindung möglich.\n"
        f"Versucht: Direkt + System-Proxy + {len(enabled_proxies)} konfigurierte(r) Proxy(s)\n"
        f"Test-URL: {test_url}\n"
        f"Proxy-Config: {PROXY_CONFIG_PATH}\n"
        "Bitte Netzwerk-Einstellungen prüfen.\n"
        "Bei 407-Fehler: pip install requests-negotiate-sspi"
    )


def initialize_proxy():
    """
    Initialisiert Proxy-Konfiguration. Thread-sicher: parallele Aufrufe
    warten bis der erste fertig ist und verwenden dann das Ergebnis.
    """
    global PROXY_CONFIG

    # Schnell-Check ohne Lock (häufiger Fall: bereits initialisiert)
    if PROXY_CONFIG.get('initialized', False):
        return

    with _PROXY_INIT_LOCK:
        # Nochmals prüfen — anderer Thread war evtl. schneller
        if PROXY_CONFIG.get('initialized', False):
            return

        config = detect_proxy_requirement()
        PROXY_CONFIG.update(config)

        if PROXY_CONFIG['enabled']:
            logger.info(
                f"Proxy aktiv: {PROXY_CONFIG['active_proxy']} "
                f"(SSL: {'deaktiviert' if not PROXY_CONFIG['verify_ssl'] else 'aktiv'})"
            )
            if PROXY_CONFIG.get('is_vpn'):
                logger.info("VPN erkannt — SSL-Handling angepasst")
        else:
            logger.info("Direkte Verbindung (kein Proxy)")

def get_session() -> requests.Session:
    """
    Gibt die konfigurierte requests Session zurück.

    Returns:
        requests.Session: Konfigurierte Session (mit oder ohne Proxy)
    """
    global PROXY_CONFIG

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
              - is_vpn (bool): VPN erkannt
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


def is_vpn_detected() -> bool:
    """
    Prüft ob eine VPN-Verbindung erkannt wurde.
    
    Returns:
        bool: True wenn VPN erkannt
    """
    config = get_proxy_config()
    return config.get('is_vpn', False)


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