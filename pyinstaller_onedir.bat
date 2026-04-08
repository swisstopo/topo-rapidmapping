@echo off
REM ========================================================================
REM Rapid Mapping Processor - Directory Build (--onedir)
REM ========================================================================
chcp 65001 >nul

echo.
echo ========================================================================
echo   RAPID MAPPING PROCESSOR - CLEANUP AND REBUILD (ONEDIR)
echo ========================================================================
echo.

REM ========================================================================
REM SCHRITT 1: KOMPLETTER CLEANUP
REM ========================================================================
echo [1/6] Kompletter Cleanup...
echo.

echo   - Lösche build\ Verzeichnis...
if exist build (
    rmdir /s /q build 2>nul
    if exist build (echo     ⚠ Konnte build\ nicht löschen) else (echo     ✓ build\ gelöscht)
) else (echo     ℹ build\ existiert nicht)

echo   - Lösche dist\ Verzeichnis...
if exist dist (
    rmdir /s /q dist 2>nul
    if exist dist (echo     ⚠ Konnte dist\ nicht löschen) else (echo     ✓ dist\ gelöscht)
) else (echo     ℹ dist\ existiert nicht)

echo   - Lösche .spec Dateien...
if exist *.spec (del /q *.spec 2>nul && echo     ✓ .spec gelöscht) else (echo     ℹ keine .spec Dateien)

echo   - Lösche alten Runtime-Hook...
if exist rth_proj_fix.py (del /q rth_proj_fix.py 2>nul && echo     ✓ rth_proj_fix.py gelöscht) else (echo     ℹ rth_proj_fix.py nicht vorhanden)

echo   - Lösche PyInstaller Cache...
if exist "%LOCALAPPDATA%\pyinstaller" (
    rmdir /s /q "%LOCALAPPDATA%\pyinstaller" 2>nul
    if exist "%LOCALAPPDATA%\pyinstaller" (echo     ⚠ Cache nicht komplett gelöscht) else (echo     ✓ Cache gelöscht)
) else (echo     ℹ Cache existiert nicht)

echo   - Lösche __pycache__ und .pyc...
if exist __pycache__ (rmdir /s /q __pycache__ 2>nul)
for /d /r . %%d in (__pycache__) do (if exist "%%d" rmdir /s /q "%%d" 2>nul)
del /s /q *.pyc 2>nul
echo     ✓ Python Cache gelöscht

echo.
echo   ✓ Cleanup abgeschlossen
echo.

REM ========================================================================
REM SCHRITT 2: QGIS/GDAL UMGEBUNGSVARIABLEN ISOLIEREN
REM ========================================================================
echo [2/6] Isoliere Build-Umgebung von QGIS/GDAL...
echo.

set PROJ_LIB=
set PROJ_DATA=
set PROJ_NETWORK=OFF
set GDAL_DATA=
set GDAL_DRIVER_PATH=
set GDAL_PLUGINS=
set OSGEO4W_ROOT=

echo   ✓ PROJ_LIB, GDAL_DATA und QGIS-Pfade für diesen Prozess geleert
echo   ℹ System-Umgebung bleibt unverändert (nur dieser Prozess betroffen)
echo.

REM ========================================================================
REM SCHRITT 3: RUNTIME-HOOK ERSTELLEN
REM
REM WICHTIGSTE ÄNDERUNG: Der Hook entfernt QGIS-Pfade IMMER - auch wenn
REM keine gebündelte proj.db gefunden wird. Ein fehlender PROJ_LIB ist
REM besser als ein falscher (QGIS v5 vs. rasterio v6+).
REM ========================================================================
echo [3/6] Erstelle Runtime-Hook (rth_proj_fix.py)...
echo.

(
echo import os
echo import sys
echo.
echo # -----------------------------------------------------------------------
echo # PyInstaller Runtime-Hook: PROJ / GDAL Pfadkorrektur
echo # Laeuft als ALLERERSTES beim EXE-Start, vor allen anderen Imports.
echo # -----------------------------------------------------------------------
echo if getattr^(sys, "frozen", False^):
echo     _base = sys._MEIPASS
echo.
echo     # --- Schritt 1: QGIS/OSGEO Pfade IMMER entfernen -------------------
echo     # Unabhaengig davon ob bundled proj.db gefunden wird.
echo     # Ein fehlender PROJ_LIB ist besser als QGIS v5 vs. rasterio v6+.
echo     for _var in ^("PROJ_LIB", "PROJ_DATA", "GDAL_DATA",
echo                  "GDAL_DRIVER_PATH", "GDAL_PLUGINS"^):
echo         _val = os.environ.get^(_var, ""^)
echo         if any^(k in _val.upper^(^) for k in ^("QGIS", "OSGEO", "OSGEO4W"^)^):
echo             os.environ.pop^(_var, None^)
echo.
echo     # --- Schritt 2: Bundled proj.db setzen (pyproj --collect-data) -----
echo     for _candidate in ^(
echo         os.path.join^(_base, "pyproj", "proj_dir"^),
echo         os.path.join^(_base, "proj_dir"^),
echo         os.path.join^(_base, "share", "proj"^),
echo     ^):
echo         if os.path.isfile^(os.path.join^(_candidate, "proj.db"^)^):
echo             os.environ["PROJ_LIB"]  = _candidate
echo             os.environ["PROJ_DATA"] = _candidate
echo             break
echo.
echo     # --- Schritt 3: Bundled gdal-data setzen ---------------------------
echo     for _candidate in ^(
echo         os.path.join^(_base, "gdal-data"^),
echo         os.path.join^(_base, "rasterio", "gdal_data"^),
echo         os.path.join^(_base, "osgeo", "gdal_data"^),
echo     ^):
echo         if os.path.isdir^(_candidate^):
echo             os.environ.setdefault^("GDAL_DATA", _candidate^)
echo             break
echo.
echo     # --- Schritt 4: PROJ-Netzwerkzugriff deaktivieren ------------------
echo     os.environ.setdefault^("PROJ_NETWORK", "OFF"^)
) > rth_proj_fix.py

if exist rth_proj_fix.py (
    echo   ✓ rth_proj_fix.py erstellt
) else (
    echo   ✗ Konnte rth_proj_fix.py nicht erstellen!
    pause
    exit /b 1
)
echo.

REM ========================================================================
REM SCHRITT 4: DEPENDENCIES PRÜFEN
REM ========================================================================
echo [4/6] Prüfe Dependencies...
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ Python nicht gefunden! Bitte zum PATH hinzufügen.
    pause
    exit /b 1
)
python --version
echo   ✓ Python verfügbar

python -c "import rasterio" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ⚠ rasterio nicht gefunden - installiere requirements.txt...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (echo   ✗ Requirements Installation fehlgeschlagen! && pause && exit /b 1)
)
echo   ✓ rasterio verfügbar

python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ⚠ PyInstaller nicht gefunden - installiere...
    pip install pyinstaller
    if %errorlevel% neq 0 (echo   ✗ PyInstaller Installation fehlgeschlagen! && pause && exit /b 1)
)
echo   ✓ PyInstaller verfügbar

python -c "import pyproj" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ⚠ pyproj nicht gefunden - PROJ-Daten werden nicht korrekt gebuendelt!
    echo     Installiere: pip install pyproj
) else (
    echo   ✓ pyproj verfügbar
)

echo.
echo   PROJ-Datenpfad aus venv:
python -c "import pyproj; print('   ', pyproj.datadir.get_data_dir())" 2>nul
echo.

REM ========================================================================
REM SCHRITT 5: REBUILD MIT --onedir (KEINE KOMPRESSION)
REM ========================================================================
echo [5/6] Building EXE (--onedir, ohne Kompression)...
echo.
echo   INFO: Runtime-Hook rth_proj_fix.py entfernt QGIS-PROJ-Pfade beim Start.
echo         Resultat: Ordner mit EXE + DLLs
echo.

pyinstaller --noconfirm --onedir --console ^
    --noupx ^
    --name rapidmapping_processor ^
    --add-data "configuration.py;." ^
    --add-data "utilities;utilities" ^
    --add-data "util_publish_stac_fsdi.py;." ^
    --add-data "main_multipart_upload_via_api.py;." ^
    --hidden-import=utilities.credentials ^
    --hidden-import=utilities.proxy_handler ^
    --hidden-import=utilities.file_handler ^
    --hidden-import=utilities.mosaic_processor ^
    --hidden-import=utilities.photo_processor ^
    --hidden-import=utilities.kml_generator ^
    --hidden-import=utilities.stac_publisher ^
    --hidden-import=rasterio.serde ^
    --hidden-import=rasterio._shim ^
    --hidden-import=rasterio.sample ^
    --collect-submodules=rasterio ^
    --collect-data=pyproj ^
    --runtime-hook=rth_proj_fix.py ^
    rapidmapping_processor.py

if %errorlevel% neq 0 (
    echo.
    echo ========================================================================
    echo   ✗ BUILD FEHLGESCHLAGEN!
    echo ========================================================================
    echo.
    echo Mögliche Lösungen:
    echo   1. Venv ohne QGIS-Einfluss neu erstellen:
    echo      python -m venv .venv_clean
    echo      .venv_clean\Scripts\activate
    echo      pip install -r requirements.txt
    echo      pip install pyinstaller
    echo      Dann dieses Skript aus dem aktivierten venv starten.
    echo.
    echo   2. Build-Log prüfen:
    echo      build\rapidmapping_processor\warn-rapidmapping_processor.txt
    echo.
    if exist rth_proj_fix.py del /q rth_proj_fix.py
    pause
    exit /b 1
)

echo.
echo   ✓ Build erfolgreich
echo.

if exist rth_proj_fix.py del /q rth_proj_fix.py

REM ========================================================================
REM SCHRITT 6: PRÜFE OUTPUT UND TESTE
REM ========================================================================
echo [6/6] Prüfe Output und teste EXE...
echo.

if not exist "dist\rapidmapping_processor\rapidmapping_processor.exe" (
    echo   ✗ EXE nicht gefunden!
    echo   Erwartet: dist\rapidmapping_processor\rapidmapping_processor.exe
    pause
    exit /b 1
)

echo   ✓ EXE gefunden: dist\rapidmapping_processor\rapidmapping_processor.exe
echo.

for /f %%A in ('dir /b /a-d "dist\rapidmapping_processor\*" ^| find /c /v ""') do set file_count=%%A
echo   Gesamt: %file_count% Dateien im Verzeichnis
echo.

cd dist\rapidmapping_processor
echo   Test: EXE startet (--help)...
rapidmapping_processor.exe --help >nul 2>&1
if %errorlevel% equ 0 (echo   ✓ EXE läuft erfolgreich!) else (echo   ⚠ EXE hat Runtime-Probleme)
cd ..\..
echo.

REM ========================================================================
echo ========================================================================
echo   ✓ BUILD ABGESCHLOSSEN
echo ========================================================================
echo.
echo EXE: %CD%\dist\rapidmapping_processor\rapidmapping_processor.exe
echo.
echo PROJ/GDAL Fix (was geändert):
echo   Runtime-Hook entfernt QGIS PROJ_LIB IMMER beim EXE-Start,
echo   unabhaengig davon ob bundled proj.db gefunden wird.
echo   Meldung "DATABASE.LAYOUT.VERSION.MINOR" erscheint nicht mehr.
echo.
echo WICHTIG - ONEDIR MODUS:
echo   Verteile den GANZEN ORDNER: dist\rapidmapping_processor\
echo.
echo Nächste Schritte:
echo   1. secrets\ Verzeichnis erstellen in: dist\rapidmapping_processor\
echo   2. stac_credentials.json nach: dist\rapidmapping_processor\secrets\
echo   3. Testen: dist\rapidmapping_processor\rapidmapping_processor.exe
echo.
echo ========================================================================
echo.

pause