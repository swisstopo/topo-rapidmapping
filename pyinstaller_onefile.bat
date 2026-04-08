@echo off
REM ========================================================================
REM Rapid Mapping Processor - Single EXE Builder
REM ========================================================================
chcp 65001 >nul

echo.
echo ========================================================================
echo   RAPID MAPPING PROCESSOR - SINGLE EXE BUILD
echo ========================================================================
echo.

REM ========================================================================
REM SCHRITT 1: KOMPLETTER CLEANUP
REM ========================================================================
echo [1/6] Kompletter Cleanup...
echo.

REM PyInstaller Build-Artefakte
echo   - Lösche build\ Verzeichnis...
if exist build (
    rmdir /s /q build 2>nul
    if exist build (
        echo     ⚠ Konnte build\ nicht komplett löschen
    ) else (
        echo     ✓ build\ gelöscht
    )
) else (
    echo     ℹ build\ existiert nicht
)

echo   - Lösche dist\ Verzeichnis...
if exist dist (
    rmdir /s /q dist 2>nul
    if exist dist (
        echo     ⚠ Konnte dist\ nicht komplett löschen
    ) else (
        echo     ✓ dist\ gelöscht
    )
) else (
    echo     ℹ dist\ existiert nicht
)

echo   - Lösche .spec Dateien...
if exist *.spec (
    del /q *.spec 2>nul
    echo     ✓ .spec Dateien gelöscht
) else (
    echo     ℹ Keine .spec Dateien gefunden
)

REM Runtime Hook
echo   - Lösche alten Runtime-Hook...
if exist rth_proj_fix.py (
    del /q rth_proj_fix.py 2>nul
    echo     ✓ rth_proj_fix.py gelöscht
) else (
    echo     ℹ rth_proj_fix.py existiert nicht
)

REM PyInstaller Cache
echo   - Lösche PyInstaller Cache...
if exist "%LOCALAPPDATA%\pyinstaller" (
    rmdir /s /q "%LOCALAPPDATA%\pyinstaller" 2>nul
    if exist "%LOCALAPPDATA%\pyinstaller" (
        echo     ⚠ Konnte Cache nicht komplett löschen
    ) else (
        echo     ✓ PyInstaller Cache gelöscht
    )
) else (
    echo     ℹ PyInstaller Cache existiert nicht
)

REM Python Cache
echo   - Lösche Python __pycache__...
if exist __pycache__ (
    rmdir /s /q __pycache__ 2>nul
    echo     ✓ Haupt-Cache gelöscht
)

for /d /r . %%d in (__pycache__) do (
    if exist "%%d" (
        rmdir /s /q "%%d" 2>nul
    )
)
echo     ✓ Alle __pycache__ Verzeichnisse gelöscht

REM .pyc Dateien
echo   - Lösche .pyc Dateien...
del /s /q *.pyc 2>nul
echo     ✓ .pyc Dateien gelöscht

echo.
echo   ✓ Cleanup abgeschlossen
echo.

REM ========================================================================
REM SCHRITT 2: QGIS/GDAL UMGEBUNGSVARIABLEN ISOLIEREN
REM
REM Problem: QGIS setzt PROJ_LIB / GDAL_DATA als System-Umgebungsvariablen.
REM          rasterio im PyInstaller-Bundle findet dann QGIS proj.db (v5)
REM          statt der venv-eigenen proj.db (v6+) -> PROJ-Versionsfehler.
REM Lösung:  Variablen für diesen Build-Prozess leeren, sodass PyInstaller
REM          die korrekten Pfade aus dem venv bündelt.
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
REM Die EXE erbt zur Laufzeit System-Umgebungsvariablen des Benutzers.
REM Dieser Hook setzt beim EXE-Start PROJ_LIB / GDAL_DATA auf die
REM mitgebündelten Pfade (sys._MEIPASS) und überschreibt damit QGIS-Pfade.
REM ========================================================================
echo [3/6] Erstelle Runtime-Hook (rth_proj_fix.py)...
echo.

(
echo import os
echo import sys
echo.
echo # -----------------------------------------------------------------------
echo # PyInstaller Runtime-Hook: PROJ / GDAL Pfadkorrektur
echo # Wird als ALLERERSTES beim Start der EXE ausgefuehrt.
echo # Ueberschreibt QGIS-Systemvariablen mit den gebundelten Pfaden.
echo # -----------------------------------------------------------------------
echo if getattr^(sys, "frozen", False^):
echo     _base = sys._MEIPASS
echo.
echo     # Suche proj.db in den bekannten PyInstaller-Paketpfaden
echo     _proj_candidates = [
echo         os.path.join^(_base, "pyproj", "proj_dir"^),
echo         os.path.join^(_base, "proj_dir"^),
echo         os.path.join^(_base, "share", "proj"^),
echo     ]
echo     for _candidate in _proj_candidates:
echo         if os.path.isfile^(os.path.join^(_candidate, "proj.db"^)^):
echo             os.environ["PROJ_LIB"]  = _candidate
echo             os.environ["PROJ_DATA"] = _candidate
echo             break
echo.
echo     # Suche gdal-data im Bundle
echo     _gdal_candidates = [
echo         os.path.join^(_base, "gdal-data"^),
echo         os.path.join^(_base, "rasterio", "gdal_data"^),
echo         os.path.join^(_base, "osgeo", "gdal_data"^),
echo     ]
echo     for _candidate in _gdal_candidates:
echo         if os.path.isdir^(_candidate^):
echo             os.environ["GDAL_DATA"] = _candidate
echo             break
echo.
echo     # Netzwerkzugriff fuer PROJ-Datenbank deaktivieren
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

REM Prüfe Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ Python nicht gefunden!
    echo   Bitte Python installieren und zum PATH hinzufügen.
    pause
    exit /b 1
)
python --version
echo   ✓ Python verfügbar

REM Prüfe PyInstaller
python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ⚠ PyInstaller nicht gefunden
    echo   Installiere PyInstaller...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo   ✗ PyInstaller Installation fehlgeschlagen!
        pause
        exit /b 1
    )
)
echo   ✓ PyInstaller verfügbar

REM Prüfe rasterio
python -c "import rasterio" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ⚠ rasterio nicht gefunden
    echo   Installiere requirements.txt...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo   ✗ Requirements Installation fehlgeschlagen!
        pause
        exit /b 1
    )
)
echo   ✓ rasterio verfügbar

REM Prüfe pyproj (wird für PROJ-Daten im Bundle benötigt)
python -c "import pyproj" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ⚠ pyproj nicht gefunden - PROJ-Daten werden nicht korrekt gebündelt!
    echo   Installiere: pip install pyproj
) else (
    echo   ✓ pyproj verfügbar
)

REM Zeige PROJ-Pfad aus venv (zur Kontrolle)
echo.
echo   PROJ-Datenpfad aus venv:
python -c "import pyproj; print('   ', pyproj.datadir.get_data_dir())" 2>nul
echo.

REM ========================================================================
REM SCHRITT 5: BUILD MIT --onefile (EINZELNE EXE)
REM ========================================================================
echo [5/6] Building Single EXE (--onefile)...
echo.
echo   INFO: Verwende --onefile für eine einzelne EXE-Datei
echo         Runtime-Hook: rth_proj_fix.py (PROJ/GDAL Pfadkorrektur)
echo         Resultat: Eine einzige rapidmapping_processor.exe
echo.

pyinstaller --noconfirm --console ^
    --onefile ^
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
    echo   2. PyInstaller neu installieren:
    echo      pip uninstall pyinstaller
    echo      pip install pyinstaller
    echo.
    echo   3. Prüfe Build-Log:
    echo      build\rapidmapping_processor\warn-rapidmapping_processor.txt
    echo.
    if exist rth_proj_fix.py del /q rth_proj_fix.py
    pause
    exit /b 1
)

echo.
echo   ✓ Build erfolgreich abgeschlossen
echo.

REM Runtime-Hook aufräumen
if exist rth_proj_fix.py del /q rth_proj_fix.py

REM ========================================================================
REM SCHRITT 6: PRÜFE OUTPUT UND TESTE
REM ========================================================================
echo [6/6] Prüfe Output und teste EXE...
echo.

if not exist "dist\rapidmapping_processor.exe" (
    echo   ✗ EXE nicht gefunden!
    echo   Erwarteter Pfad: dist\rapidmapping_processor.exe
    pause
    exit /b 1
)

echo   ✓ EXE gefunden: dist\rapidmapping_processor.exe
echo.

REM Zeige Dateigröße
for %%A in (dist\rapidmapping_processor.exe) do (
    set size=%%~zA
    set /a size_mb=%%~zA/1048576
)
echo   Dateigröße: %size_mb% MB
echo.

REM Prüfe ob wirklich nur eine EXE existiert
echo   Inhalt von dist\:
dir /b dist\
echo.

echo   Test: EXE startet (--help)...
dist\rapidmapping_processor.exe --help >nul 2>&1
if %errorlevel% equ 0 (
    echo   ✓ EXE läuft erfolgreich!
) else (
    echo   ⚠ EXE hat Runtime-Probleme
    echo   Versuche manuellen Test: dist\rapidmapping_processor.exe --help
)

echo.

REM ========================================================================
REM FERTIG
REM ========================================================================
echo ========================================================================
echo   ✓ BUILD ABGESCHLOSSEN
echo ========================================================================
echo.
echo EXE Location:
echo   %CD%\dist\rapidmapping_processor.exe
echo.
echo WICHTIG - SINGLE EXE:
echo   Die EXE ist eine eigenständige Datei - keine zusätzlichen Ordner nötig.
echo   Bei Start entpackt PyInstaller temporär in %TEMP%
echo.
echo Nächste Schritte:
echo   1. Erstelle secrets\ Verzeichnis neben der EXE
echo   2. Kopiere stac_credentials.json nach secrets\
echo   3. Optional: proxy_config.json nach secrets\
echo   4. Teste: dist\rapidmapping_processor.exe
echo.
echo Für Distribution:
echo   - Einfach rapidmapping_processor.exe verteilen
echo   - User muss secrets\ Verzeichnis mit Credentials erstellen
echo.
echo HINWEIS - STARTZEIT:
echo   Erster Start kann 5-10 Sekunden dauern (Entpacken nach %TEMP%)
echo   Weitere Starts sind schneller (Cache)
echo.
echo PROJ/GDAL Info:
echo   Der Runtime-Hook rth_proj_fix.py setzt PROJ_LIB beim EXE-Start
echo   auf die gebündelte proj.db und überschreibt damit QGIS-Systemvariablen.
echo   Fehlermeldung "DATABASE.LAYOUT.VERSION.MINOR" sollte nicht mehr erscheinen.
echo.
echo Bei Problemen:
echo   - Prüfe Log: build\rapidmapping_processor\warn-rapidmapping_processor.txt
echo   - Wenn PROJ-Fehler: Prüfe ob pyproj im venv installiert ist
echo   - Wenn DLL-Fehler: Versuche --onedir Modus (anderes Skript)
echo.
echo ========================================================================
echo.

pause