import requests
import urllib.request
from requests_negotiate_sspi import HttpNegotiateAuth

def download_asset(asset_url, filename):
    session = requests.Session()

    # 1. System-Proxies auslesen und Schlüssel normalisieren
    raw_proxies = urllib.request.getproxies()
    proxy_url = (
        raw_proxies.get('https') or
        raw_proxies.get('http') or
        raw_proxies.get('gdal_https') or
        raw_proxies.get('gdal_http')
    )

    if proxy_url:
        session.proxies = {'http': proxy_url, 'https': proxy_url}
        print(f"Nutze Proxy: {proxy_url}")
    else:
        print("Kein System-Proxy gefunden, versuche direkte Verbindung...")

    # 2. Windows-SSPI / Kerberos-Negotiate-Authentifizierung aktivieren
    session.auth = HttpNegotiateAuth()

    # 3. Download
    try:
        response = session.get(asset_url, stream=True, timeout=60)

        if response.status_code == 200:
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print(f"Datei gespeichert: {filename}")
        else:
            print(f"HTTP-Fehler: {response.status_code}")

    except requests.exceptions.ProxyError as e:
        print(f"Proxy-Authentifizierungsfehler: {e}")
    except requests.exceptions.Timeout:
        print("Timeout: Proxy oder Zielserver nicht erreichbar.")
    except Exception as e:
        print(f"Fehler: {e}")

if __name__ == "__main__":
    asset_url = (
        "https://data.geo.admin.ch/ch.swisstopo.swissimage-dop10/"
        "swissimage-dop10_2017_2517-1139/"
        "swissimage-dop10_2017_2517-1139_2_2056.tif"
    )
    filename = "swissimage-dop10_2017_2517-1139_2_2056.tif"
    download_asset(asset_url, filename)