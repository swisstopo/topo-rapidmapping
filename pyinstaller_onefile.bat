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
REM SCHRITT 2: DEPENDENCIES PRÜFEN
REM ========================================================================
echo [2/5] Prüfe Dependencies...
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

echo.

REM ========================================================================
REM SCHRITT 3: BUILD MIT --onefile (EINZELNE EXE)
REM ========================================================================
echo [3/5] Building Single EXE (--onefile)...
echo.
echo   INFO: Verwende --onefile für eine einzelne EXE-Datei
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
    rapidmapping_processor.py

if %errorlevel% neq 0 (
    echo.
    echo ========================================================================
    echo   ✗ BUILD FEHLGESCHLAGEN!
    echo ========================================================================
    echo.
    echo Mögliche Lösungen:
    echo   1. PyInstaller neu installieren:
    echo      pip uninstall pyinstaller
    echo      pip install pyinstaller
    echo.
    echo   2. Fresh Virtual Environment erstellen:
    echo      python -m venv .venv_clean
    echo      .venv_clean\Scripts\activate
    echo      pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo   ✓ Build erfolgreich abgeschlossen
echo.

REM ========================================================================
REM SCHRITT 4: PRÜFE OUTPUT
REM ========================================================================
echo [4/5] Prüfe Output...
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

REM ========================================================================
REM SCHRITT 5: TESTE EXE
REM ========================================================================
echo [5/5] Teste EXE...
echo.

echo   Test: EXE startet...
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
echo   3. Teste: dist\rapidmapping_processor.exe
echo.
echo Für Distribution:
echo   - Einfach rapidmapping_processor.exe verteilen
echo   - User muss secrets\ Verzeichnis mit Credentials erstellen
echo.
echo HINWEIS - STARTZEIT:
echo   Erste Start kann 5-10 Sekunden dauern (Entpacken)
echo   Weitere Starts sind schneller (Cache)
echo.
echo Bei Problemen:
echo   - Prüfe Log: build\rapidmapping_processor\warn-rapidmapping_processor.txt
echo   - Wenn DLL-Fehler: Versuche --onedir Modus (anderes Skript)
echo.
echo ========================================================================
echo.

pause