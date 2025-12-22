@echo off
REM ========================================================================
REM Rapid Mapping Processor - Windows Setup Script
REM ========================================================================
chcp 65001 >nul

echo.
echo ========================================================================
echo   RAPID MAPPING PROCESSOR - SETUP
echo ========================================================================
echo.

REM Prüfe Python
echo [1/5] Prüfe Python-Installation...
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
echo [2/5] Prüfe GDAL-Installation...
gdalinfo --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ GDAL nicht gefunden!
    echo   Bitte OSGeo4W installieren: https://trac.osgeo.org/osgeo4w/
    echo   Und dieses Script in der OSGeo4W Shell ausführen.
    pause
    exit /b 1
)
gdalinfo --version
echo   ✓ GDAL gefunden
echo.

REM Erstelle Verzeichnisse
echo [3/5] Erstelle Verzeichnisse...
if not exist "secrets" mkdir secrets
if not exist "temp" mkdir temp
if not exist "utilities" mkdir utilities
echo   ✓ Verzeichnisse erstellt
echo.

REM Installiere Python-Pakete
echo [4/5] Installiere Python-Pakete...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo   ✗ Installation fehlgeschlagen!
    pause
    exit /b 1
)
echo   ✓ Pakete installiert
echo.

REM Prüfe Credentials
echo [5/5] Prüfe Credentials...
if exist "secrets\stac_credentials.json" (
    echo   ✓ Credentials gefunden: secrets\stac_credentials.json
) else (
    echo   ⚠ Credentials NICHT gefunden!
    echo.
    echo   Bitte erstellen:
    echo   1. Kopiere secrets\stac_credentials.json.example
    echo   2. Benenne um zu stac_credentials.json
    echo   3. Füge echte Credentials ein
    echo.
    echo   Alternative: Setze Environment Variables:
    echo     set STAC_USERNAME=your_username
    echo     set STAC_PASSWORD=your_password
)
echo.

echo ========================================================================
echo   SETUP ABGESCHLOSSEN
echo ========================================================================
echo.
echo Nächste Schritte:
echo   1. Falls noch nicht geschehen: Credentials konfigurieren
echo   2. Script ausführen: python rapidmapping_processor.py
echo.
echo Bei Problemen: Siehe README.md
echo ========================================================================
echo.

pause