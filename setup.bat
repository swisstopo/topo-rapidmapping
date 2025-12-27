@echo off
REM ========================================================================
REM Rapid Mapping Processor 2.0 - Windows Setup Script
REM ========================================================================
chcp 65001 >nul

echo.
echo ========================================================================
echo   SWISSTOPO RAPID MAPPING PROCESSOR 2.0 - SETUP
echo ========================================================================
echo.

REM Prüfe Python
echo [1/6] Prüfe Python-Installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ Python nicht gefunden!
    echo   Bitte Python 3.12+ installieren: https://www.python.org/
    pause
    exit /b 1
)
python --version
echo   ✓ Python gefunden
echo.

REM Prüfe GDAL
echo [2/6] Prüfe GDAL-Installation...
gdalinfo --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ GDAL nicht gefunden!
    echo.
    echo   GDAL wird benötigt für Raster-Operationen.
    echo.
    echo   INSTALLATION:
    echo   1. Option: OSGeo4W installieren: https://trac.osgeo.org/osgeo4w/
    echo   2. Option: QGIS nutzen (enthält GDAL)
    echo.
    echo   Nach Installation dieses Script in OSGeo4W Shell ausführen.
    echo.
    pause
    exit /b 1
)
gdalinfo --version
echo   ✓ GDAL gefunden
echo.

REM Erstelle Verzeichnisstruktur
echo [3/6] Erstelle Verzeichnisstruktur...
if not exist "secrets" mkdir secrets
if not exist "utilities" mkdir utilities
if not exist "temp" mkdir temp
echo   ✓ Verzeichnisse erstellt
echo.

REM Installiere Python-Pakete
echo [4/6] Installiere Python-Pakete...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo   ✗ Installation fehlgeschlagen!
    echo.
    echo   Mögliche Probleme:
    echo   - requirements.txt nicht gefunden
    echo   - Keine Internet-Verbindung
    echo   - Proxy-Einstellungen erforderlich
    echo.
    pause
    exit /b 1
)
echo   ✓ Pakete installiert
echo.

REM Prüfe STAC Credentials
echo [5/6] Prüfe STAC Credentials...
if exist "secrets\stac_credentials.json" (
    echo   ✓ STAC Credentials gefunden: secrets\stac_credentials.json
) else (
    echo   ⚠ STAC Credentials NICHT gefunden!
    echo.
    echo   Bitte erstellen: secrets\stac_credentials.json
    echo.
    echo   Format:
    echo   {
    echo     "INT": {
    echo       "username": "your_int_username",
    echo       "password": "your_int_password",
    echo       "hostname": "sys-data.int.bgdi.ch"
    echo     },
    echo     "PROD": {
    echo       "username": "your_prod_username",
    echo       "password": "your_prod_password",
    echo       "hostname": "data.geo.admin.ch"
    echo     }
    echo   }
    echo.
    echo   Alternative: Environment Variables setzen:
    echo     set STAC_USERNAME=your_username
    echo     set STAC_PASSWORD=your_password
)
echo.

REM Prüfe Proxy Config
echo [6/6] Prüfe Proxy-Konfiguration...
if exist "secrets\proxy_config.json" (
    echo   ✓ Proxy-Config gefunden: secrets\proxy_config.json
) else (
    echo   ⚠ Proxy-Config NICHT gefunden!
    echo.
    echo   Bitte erstellen: secrets\proxy_config.json
    echo.
    echo   Format:
    echo   {
    echo     "proxies": [
    echo       {
    echo         "name": "Corporate Proxy",
    echo         "url": "http://proxy.example.com:8080",
    echo         "enabled": true
    echo       }
    echo     ],
    echo     "test_url": "https://data.geo.admin.ch/browser/index.html",
    echo     "timeout": 5,
    echo     "disable_ssl_warnings": true
    echo   }
    echo.
    echo   Hinweis: Bei direkter Internet-Verbindung wird dies automatisch erkannt.
)
echo.

echo ========================================================================
echo   SETUP ABGESCHLOSSEN
echo ========================================================================
echo.
echo Nächste Schritte:
echo   1. Falls noch nicht geschehen: Credentials konfigurieren
echo      - secrets\stac_credentials.json (STAC API)
echo      - secrets\proxy_config.json (Proxy, optional)
echo.
echo   2. Script ausführen:
echo      python rapidmapping_processor.py              # INT-Environment
echo      python rapidmapping_processor.py --prod       # PROD-Environment
echo      python rapidmapping_processor.py --upload=False  # Nur lokal
echo.
echo   3. Bei Problemen:
echo      - Siehe README.md für Details
echo      - Log-Output prüfen
echo      - temp\ Verzeichnis inspizieren
echo.
echo ========================================================================
echo.

pause