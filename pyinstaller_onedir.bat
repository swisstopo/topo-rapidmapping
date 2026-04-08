@echo off
REM ========================================================================
REM Rapid Mapping Processor - Complete Cleanup and Rebuild Script
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
echo [1/5] Kompletter Cleanup...
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
REM SCHRITT 5: REBUILD MIT --onedir (KEINE KOMPRESSION)
REM ========================================================================
echo [5/6] Building EXE (--onedir, ohne Kompression)...
echo.
echo   INFO: Verwende --onedir statt --onefile
echo         Runtime-Hook: rth_proj_fix.py (PROJ/GDAL Pfadkorrektur)
echo         Dies vermeidet Dekomprimierungs-Probleme mit DLLs
echo         Resultat: Ordner mit EXE + DLLs statt einzelner EXE
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
REM SCHRITT 6: PRÜFE OUTPUT
REM ========================================================================
echo [6/6] Prüfe Output...
echo.

if not exist "dist\rapidmapping_processor\rapidmapping_processor.exe" (
    echo   ✗ EXE nicht gefunden!
    echo   Erwarteter Pfad: dist\rapidmapping_processor\rapidmapping_processor.exe
    pause
    exit /b 1
)

echo   ✓ EXE gefunden: dist\rapidmapping_processor\rapidmapping_processor.exe
echo.

REM Zeige Verzeichnis-Inhalt
echo   Verzeichnis-Inhalt (Auswahl):
dir /b dist\rapidmapping_processor | findstr /r "rapidmapping.*\.exe$ .*\.dll$" | more
echo   ... und weitere Dateien
echo.

REM Zähle Dateien
for /f %%A in ('dir /b /a-d "dist\rapidmapping_processor\*" ^| find /c /v ""') do set file_count=%%A
echo   Gesamt: %file_count% Dateien im Verzeichnis
echo.

REM ========================================================================
REM SCHRITT 6 (FORTSETZUNG): TESTE EXE
REM ========================================================================
echo   Test: EXE startet (--help)...
echo.

cd dist\rapidmapping_processor

REM Test 1: Einfacher Start-Test
echo   Test 1: EXE startet...
rapidmapping_processor.exe --help >nul 2>&1
if %errorlevel% equ 0 (
    echo   ✓ EXE läuft erfolgreich!
) else (
    echo   ⚠ EXE hat Runtime-Probleme
    echo   Versuche manuellen Test: dist\rapidmapping_processor\rapidmapping_processor.exe --help
)

cd ..\..
echo.

REM ========================================================================
REM FERTIG
REM ========================================================================
echo ========================================================================
echo   ✓ BUILD ABGESCHLOSSEN
echo ========================================================================
echo.
echo EXE Location:
echo   %CD%\dist\rapidmapping_processor\rapidmapping_processor.exe
echo.
echo WICHTIG - ONEDIR MODUS:
echo   Die EXE ist jetzt in einem Ordner mit allen Dependencies.
echo   Verteile den GANZEN ORDNER: dist\rapidmapping_processor\
echo.
echo Nächste Schritte:
echo   1. Erstelle secrets\ Verzeichnis in: dist\rapidmapping_processor\
echo   2. Kopiere stac_credentials.json nach: dist\rapidmapping_processor\secrets\
echo   3. Teste: dist\rapidmapping_processor\rapidmapping_processor.exe
echo.
echo Für Distribution:
echo   1. ZIP erstellen: rapidmapping_processor.zip (kompletter Ordner)
echo   2. User extrahiert ZIP
echo   3. User startet rapidmapping_processor\rapidmapping_processor.exe
echo.
echo Bei Problemen:
echo   - Prüfe Log: build\rapidmapping_processor\warn-rapidmapping_processor.txt
echo   - Alle DLLs sind jetzt sichtbar im Verzeichnis
echo.
echo ========================================================================
echo.

pause
```

## 📦 Was ändert sich mit `--onedir`?

### Vorher (`--onefile`):
```
dist/
└── rapidmapping_processor.exe  (80-100 MB, komprimiert)
```

### Nachher (`--onedir`):
```
dist/
└── rapidmapping_processor/
    ├── rapidmapping_processor.exe  (~500 KB)
    ├── python312.dll
    ├── libssl-3-x64.dll
    ├── libcrypto-3-x64.dll
    ├── hdf5-xxx.dll
    ├── ... (viele weitere DLLs)
    ├── base_library.zip
    └── ... (~150-200 Dateien, ~100-150 MB gesamt)