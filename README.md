# Swisstopo Rapid Mapping Processor 2.0 RC

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/swisstopo/topo-rapidmapping)

Automatisiertes System für die Publikation von Rapid Mapping Daten auf der FSDI STAC Plattform.

## Übersicht

Dieses Tool vereint die Funktionalität von:
- Orthophoto-Mosaike
- Einzelbilder
- STAC-Publikation

in einem einzigen, benutzerfreundlichen Workflow mit automatischer Proxy-Erkennung und VPN-Support.

### Hauptfeatures

- **Single COG-File Workflow (QDOP)**: Prüft ob Input bereits COG-konform ist (8-bit RGB, 3 Bänder); ist die Datei kein COG, wird sie automatisch konvertiert
- **DMC4-Workflow (QDOP)**: Verarbeitet 4-Kanal DMC4-Bildstreifen automatisch zu RGB + NRG COG
- **Grafische Oberfläche (GUI)**: Formularbasierter STAC-Import als Alternative zur CLI
- **Automatische Proxy-Erkennung**: VPN- und Corporate-Proxy-Support mit SSL-Handling
- **EXIF-Extraktion für (EBN, EBO)**: GPS und Zeitstempel aus Einzelbildern
- **KML-Overview (EBN, EBO)**: Automatische Generierung via STAC-Abfrage nach Upload
- **Multi-Environment**: INT und PROD-Support
- **Batch-Upload**: Einzelbilder werden sequenziell hochgeladen
- **Error Handling**: Robuste Fehlerbehandlung mit detaillierten Logs

## Entwicklungs-Workflow: Integrationsbranch (int)

Änderungen gehen **nicht** direkt nach `main`. Der `int`-Branch dient als gemeinsamer Staging-Bereich:

```
dein-branch  →  int  →  main
  (PR, squash merge)   (PR, merge commit)
```

### Ablauf

1. Branch von `int` erstellen (nicht von `main`) und Änderungen vornehmen.
2. Pull Request gegen `int` öffnen und mit **Squash Merge** mergen.
3. Vor dem Weiterführen nach `main` muss die Testsuite gegen `int` grün sein:
   ```bash
   python -m unittest test_functions -v
   ```
   (aktuell 48 Tests: Konfiguration, Foto-/Mosaik-/GDAL-Verarbeitung, KML/STAC-Abfragen, Secrets-Prompt, Multipart-Upload-Part-Grösse — siehe `test_functions.py`)
4. Sind die Tests grün und stimmt das Ergebnis, Pull Request von `int` → `main` öffnen und mit regulärem **Merge Commit** mergen.

### Warum Squash Merge für branch → int, aber ein Merge Commit für int → main?

Während der Integration sammelt ein Feature-Branch oft viele kleine Commits ("Tippfehler behoben", "nochmal versuchen" usw.). Squash Merge fasst sie zu einem sauberen Commit auf `int` zusammen, sodass dessen Historie pro Feature lesbar bleibt.

Bis `int` nach `main` gemerged wird, enthält er typischerweise mehrere solcher bereits gesquashter Commits aus unabhängigen PRs. Würde man auch *diesen* Merge squashen, würden all diese Commits zu einem einzigen Commit auf `main` verflacht und die PR-Zuordnung in der permanenten Produktions-Historie ginge verloren. Ein regulärer Merge Commit erhält stattdessen jeden einzelnen (bereits gesquashten) PR-Commit auf `main`, protokolliert aber trotzdem den Integrationspunkt.

## Projektstruktur

```
rapidmapping_processor/
├── rapidmapping_processor.py      # Hauptskript (CLI)
├── 0_GUI_rapidmapping_STACimport.py # GUI-Einstiegspunkt (startet gui.app)
├── configuration.py                # Produktdefinitionen & Konfiguration
├── requirements.txt                # Python-Dependencies
├── setup.bat                       # Windows Setup-Script
├── README.md                       # Diese Datei
├── gui/                             # Grafische Oberfläche
│   ├── app.py                     # Hauptfenster / Formular
│   ├── runner.py                  # Führt rapidmapping_processor.py als Subprocess aus
│   ├── config.py                  # GUI-eigene Einstellungen (persistiert)
│   └── theme.py                   # Dark/Light-Theme
├── utilities/                      # Hilfsfunktionen
│   ├── credentials.py             # Credentials-Management (INT/PROD)
│   ├── proxy_handler.py           # Proxy-Erkennung & VPN-Support
│   ├── file_handler.py            # Datei-Operationen
│   ├── gdal_helpers.py            # Gemeinsame GDAL-Hilfsfunktionen
│   ├── mosaic_processor.py        # COG-File Processing
│   ├── photo_processor.py         # Einzelbild-Verarbeitung
│   ├── kml_generator.py           # KML-Overview via STAC-Abfrage
│   └── stac_publisher.py          # STAC-Publikation Wrapper
├── secrets/                        # Credentials (NICHT in Git!)
│   ├── stac_credentials.json      # STAC API-Keys (INT + PROD)
│   └── proxy_config.json          # Proxy-Konfiguration
├── temp/                           # Temporäre Dateien (wird gelöscht)
├── util_publish_stac_fsdi.py      # Bestehender STAC-Publisher
└── main_multipart_upload_via_api.py # Multipart-Upload

```

## Installation

### 1. GDAL-Tools installieren (kommt mit QGIS)

#### Windows (OSGeo4W Shell)
1. Download: https://trac.osgeo.org/osgeo4w/
2. Installiere GDAL-Pakete
3. Führe Script in OSGeo4W Shell aus

**ODER: Nutze QGIS** (empfohlen)
```bash
# QGIS enthält bereits GDAL
# Öffne "OSGeo4W Shell" aus QGIS-Installation
# Beispiel-Pfad: C:\Program Files\QGIS 3.40.7\OSGeo4W.bat
```

#### Linux
```bash
sudo apt update
sudo apt install gdal-bin python3-gdal
```

### .EXE (empfohlen)

#### Windows (OSGeo4W Shell)
1. Kopiere Secrets Folder und dist/rapidmapping_processor.exe ind das gleiche Verezeichnis
2. Führe Script in OSGeo4W Shell aus
```bash
rapidmapping_processor.exe
```

### 3. Python Virtual Environment ( 2. Wahl )

#### Mit QGIS Python:
```bash
# Windows mit QGIS
"C:\Program Files\QGIS 3.40.7\apps\Python312\python.exe" -m venv .venv --system-site-packages
.venv\Scripts\activate

# Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Python-Dependencies installieren

```bash
pip install -r requirements.txt
```

### 4. Automatisches Setup (Windows)

```bash
setup.bat
```

Dieses Script prüft:
- Python-Installation
- GDAL-Verfügbarkeit
- Erstellt Verzeichnisstruktur
- Installiert Dependencies
- Prüft Credentials

## Konfiguration

### STAC Credentials

Erstelle `secrets/stac_credentials.json`:

```json
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
```

**Alternative:** Environment Variables setzen:
```bash
# Windows
set STAC_USERNAME=your_username
set STAC_PASSWORD=your_password

# Linux
export STAC_USERNAME=your_username
export STAC_PASSWORD=your_password
```

### Netzwerk und Proxy-Konfiguration

Das Tool testet beim Start die Netzwerkverbindung in einer festen Reihenfolge. In den meisten Fällen ist kein manueller Eingriff nötig.

#### Netzwerk-Modus wählen

Beim Start erscheint eine Auswahl:

```
Netzwerk / Proxy:
  1) Autodetect  (direkt -> System-Proxy -> proxy_config.json)
  2) Kein Proxy  (direkte Verbindung, kein Proxy)
  3) Bundesnetz  (System-Proxy aus Windows-Einstellungen)
  4) BVCOL
```

**Option 1 — Autodetect (Standard)**
Testet in dieser Reihenfolge:

1. Direkte Verbindung ohne Proxy. Funktioniert z.B. wenn ein VPN-Client das Routing transparent übernimmt. SSL-Verifikation aktiv.
2. System-Proxy: liest die Proxy-URL aus Windows-Systemeinstellungen (Systemsteuerung > Internetoptionen > Verbindungen > LAN-Einstellungen) und aus den Umgebungsvariablen `HTTP_PROXY` / `HTTPS_PROXY`. SSL-Verifikation wird automatisch ermittelt (VPN-Detection).
3. Proxies aus `secrets/proxy_config.json` — als letzter Fallback. SSL-Verifikation wird automatisch ermittelt.

**Option 2 — Kein Proxy**
Verbindet direkt ohne Proxy. SSL-Verifikation ist immer aktiv (kein Proxy bedeutet keine SSL-Inspection). Schlägt fehl wenn das Netz einen Proxy voraussetzt.

**Option 3 — Bundesnetz**
Verwendet nur den System-Proxy (Windows-Einstellungen / Umgebungsvariablen), ohne vorher eine direkte Verbindung zu versuchen. SSL-Verifikation wird automatisch ermittelt (VPN-Detection). Sinnvoll wenn bekannt ist, dass man im Bundesnetz mit Proxy arbeitet.

**Option 4 und höher — definierter Proxy**
Verwendet einen bestimmten Proxy aus `secrets/proxy_config.json`, identifiziert über den `name`-Eintrag (z.B. `BVCOL`). Alle anderen Verbindungswege werden übersprungen. SSL-Verifikation wird automatisch ermittelt (VPN-Detection).

Via CLI-Parameter lässt sich der Modus direkt setzen (kein Dialog). Wenn alle drei Parameter `--product`, `--input` und `--timestamp` angegeben sind und `--proxy` fehlt, wird automatisch `auto` verwendet:
```bash
--proxy auto      # Autodetect (Standard, auch impliziter Default im CLI-Modus)
--proxy direct    # Kein Proxy (direkte Verbindung)
--proxy system    # Bundesnetz (System-Proxy)
--proxy BVCOL     # definierter Proxy mit Name "BVCOL"
```

**Kerberos-Authentifizierung**
Wenn ein Proxy Windows-Kerberos verlangt (typisch in AD-Umgebungen), erfolgt die Authentifizierung automatisch mit den Anmeldedaten des eingeloggten Windows-Benutzers. Voraussetzung: `pip install pyspnego`.

#### VPN und SSL-Inspektion

Manche VPN- oder Firewall-Lösungen führen eine SSL-Inspektion durch (Man-in-the-Middle auf HTTPS). Das Tool erkennt das automatisch und deaktiviert bei Bedarf die SSL-Zertifikatsprüfung. Die Option `disable_ssl_warnings` in `proxy_config.json` unterdrückt die daraus resultierenden urllib3-Warnungen.

#### proxy_config.json

Optionale Datei unter `secrets/proxy_config.json`. Kopieren aus `proxy_config.examples` und URL anpassen. Nur nötig wenn der System-Proxy nicht in den Windows-Einstellungen konfiguriert ist.

```bash
cp proxy_config.examples secrets/proxy_config.json
```

```json
{
  "proxies": [
    {
      "name": "Mein Proxy",
      "url": "http://mein-proxy.ch:8080",
      "enabled": true
    }
  ],
  "test_url": "https://data.geo.admin.ch/browser/index.html",
  "timeout": 5,
  "disable_ssl_warnings": true
}
```

#### Kerberos / Corporate Proxy

```bash
pip install pyspnego        # empfohlen (modern, aktiv gepflegt, kein pywin32 nötig)
# ODER Legacy-Fallback:
pip install requests-negotiate-sspi
```

Voraussetzung: Windows, am Active-Directory-Domain angemeldet.

## Verwendung

### Grafische Oberfläche (GUI)

```bash
python 0_GUI_rapidmapping_STACimport.py
```

Formularbasierte Alternative zur CLI: Umgebung, Input-Verzeichnis, Produkttyp, Zeitstempel, Upload, Debug und Netzwerk-Modus werden im Formular gewählt und daraus dieselben CLI-Flags gebaut, die `rapidmapping_processor.py` auch von Hand entgegennimmt. Ausführung erfolgt via `gui/runner.py` als Subprocess, mit Live-Log und Abbrechen-Button. Für `qdop-dmc4` sind zusätzlich `--cog-compress`/`--cog-quality` im Formular wählbar (siehe Parameter-Übersicht unten).

### Grundlegende Commands

```bash
# INT-Environment (Standard)
python rapidmapping_processor.py

# PROD-Environment
python rapidmapping_processor.py --prod

# Ohne Upload (nur lokale Verarbeitung)
python rapidmapping_processor.py --upload=False
```

### Interaktiver Workflow

Das Script führt durch folgende Schritte:

1. **Credentials laden** (INT oder PROD)
2. **Input-Verzeichnis** angeben
3. **Produkttyp** auswählen:
   - QDOP RGB Mosaic
   - QDOP NRG Mosaic
   - Einzelbilder Nadir (EBN)
   - Einzelbilder Oblique (EBO)
   - QDOP-DMC4 (4-Kanal DMC4-Streifen → RGB + NRG)
4. **Zeitstempel** (bei Mosaiken) oder nur Datum (bei Einzelbildern)
5. **Bestätigung** und Start

## Produkttypen & Workflows

### 1. QDOP RGB/NRG Mosaike (Orthophotos)

#### Input Requirements
- **Verzeichnis mit genau 1 TIF-Datei**
- **8-bit RGB** (3 Bänder, Datatype "Byte")
- **COG-konform** (Cloud Optimized GeoTIFF) empfohlen, aber nicht zwingend — ist die Datei kein COG, konvertiert das Tool sie automatisch (siehe unten)

#### Workflow
```
1. Single-File-Check
   ├─ Prüfe: Genau 1 Datei?
   ├─ Prüfe: Ist COG? (Tiled + Overviews)
   └─ Prüfe: Ist 8-bit RGB? (3 Bänder, Byte)

2. Wenn alle Checks OK:
   ├─ Kopiere Datei nach temp/
   └─ Erstelle Thumbnail (thumbnail.jpg, 256px)

3. STAC-Upload
   ├─ Asset: ram-YYYY-MM-DDthhmmsscc-qdop-rgb-mosaic.tif
   └─ Asset: thumbnail.jpg
```

#### Output-Naming
```
Item:  ram-2024-07-15t14300000
Asset: ram-2024-07-15t14300000-qdop-rgb-mosaic.tif
Asset: thumbnail.jpg
```

#### Wenn Input NICHT COG-konform ist

Die Datei wird automatisch nach COG konvertiert (Kompression/Qualität aus `configuration.py`,
`COG_CONFIG`), das Original bleibt dabei unverändert. Erst wenn die Konvertierung selbst
fehlschlägt, bricht der Lauf ab:

```
INFO:   Prüfe ob COG...
INFO:   Datei ist kein COG, starte automatische Konvertierung...
INFO:   Kompression: JPEG, Qualität: 85
INFO:  ✓ COG erstellt: <dateiname>_cog.tif
```

Vor der Konvertierung wird geprüft, ob am Zielort genug freier Speicherplatz vorhanden ist
(Mosaike können im zweistelligen GB-Bereich liegen) — reicht der Speicher nicht, bricht der
Lauf mit klarer Fehlermeldung ab, statt die Konvertierung zu versuchen.

**Externes Mosaic-Erstellungs-Script verfügbar:**
- `rm_publish_quickorthophoto.bat` für ADS100 Flightline-Mosaike
- Erstellt VRT → Warp → COG Pipeline

### 2. Einzelbilder (Nadir/Oblique)

#### Input Requirements
- **Verzeichnis mit JPEG-Dateien**
- **EXIF-Daten erforderlich**: GPS + Zeitstempel

#### Workflow
```
1. Für jedes Foto:
   ├─ EXIF extrahieren (gdalinfo)
   │  ├─ GPS-Koordinaten (Lat/Lon)
   │  └─ Zeitstempel (EXIF_DateTimeOriginal)
   │
   ├─ Foto umbenennen in temp_dir
   │  → ram-YYYY-MM-DDthhmmss-ebn.jpg
   │
   ├─ Thumbnail erstellen (gdal_translate)
   │  → thumbnail.jpg (640x480px, Aspect Ratio erhalten)
   │
   ├─ STAC-Upload (beide Assets)
   │  ├─ ram-YYYY-MM-DDthhmmss-ebn.jpg
   │  └─ thumbnail.jpg
   │
   └─ Cleanup (temp-Dateien löschen)

2. Nach allen Uploads:
   ├─ Generiere Download-Liste
   │  → ram-YYYY-MM-DDt23595900-ebn.txt (alle URLs)
   │
   └─ Generiere KML-Overview (via STAC-Abfrage)
      ├─ Abfrage: Alle Items des Tages
      ├─ Erstelle KML mit Placemarks
      │  └─ Icon, Thumbnail, GPS-Position
      └─ Upload als: ram-YYYY-MM-DDt23595900-ebn.kml
```

#### Output-Naming (pro Foto)
```
Item:  ram-2024-07-15t12052300-ebn
Asset: ram-2024-07-15t12052300-ebn.jpg (Original)
Asset: thumbnail.jpg (640x480px Thumbnail)
```

#### Output-Naming (KML-Overview)
```
Item:  ram-2024-07-15t23595900
Asset: ram-2024-07-15t23595900-ebn.kml
Asset: ram-2024-07-15t23595900-ebn.txt
```

#### GPS-Koordinaten Handling
- **DMS → Dezimal-Konvertierung** (6 Dezimalstellen Präzision)
- **Keine GPS-Daten ermittelbar**: Foto wird **nicht** ohne Position importiert, sondern übersprungen — gleiche Behandlung wie bei fehlendem Zeitstempel (siehe unten). Wird klar protokolliert (Terminal + Log-Datei), inklusive Dateiname, sowohl direkt beim Verarbeiten als auch gesammelt in der Verarbeitungszusammenfassung am Ende des Laufs
- **KML**: Enthält dadurch immer nur Fotos mit GPS-Daten (übersprungene Fotos ohne Position landen nie in STAC)

#### Zeitstempel-Handling
- Zeitstempel wird aus EXIF (`DateTimeOriginal`) oder, falls nicht vorhanden, aus dem Dateinamen ermittelt
- **Kein Timestamp ermittelbar (weder EXIF noch Dateiname)**: Foto wird **nicht** mit dem aktuellen Datum importiert, sondern übersprungen. Wird klar protokolliert (Terminal + Log-Datei), inklusive Dateiname, sowohl direkt beim Verarbeiten als auch gesammelt in der Verarbeitungszusammenfassung am Ende des Laufs

### 3. QDOP-DMC4 (4-Kanal DMC4-Bildstreifen)

#### Input Requirements
- **Verzeichnis mit einem oder mehreren 4-Band TIF-Streifen**
- **Kein CRS zugewiesen** — Daten liegen in EPSG:2056 (LV95), werden automatisch zugewiesen
- **Bandstruktur**: Band 1 = Rot, Band 2 = Grün, Band 3 = Blau, Band 4 = Nahinfrarot

#### Workflow
```
1. Alle .tif-Streifen im Input-Verzeichnis finden

2. Pro Streifen (gdal_translate):
   ├─ CRS EPSG:2056 zuweisen
   ├─ Bänder 1,2,3 extrahieren → RGB-Streifen
   └─ Bänder 4,1,2 extrahieren → NRG-Streifen (Nahinfrarot, Rot, Grün)

3. VRT-Mosaike bauen (gdalbuildvrt)
   ├─ Alle RGB-Streifen → mosaic_rgb.vrt
   └─ Alle NRG-Streifen → mosaic_nrg.vrt

4. COG-Konvertierung (gdal_translate -of COG)
   ├─ mosaic_rgb.vrt → ram-YYYY-MM-DDthhmmsscc-qdop-rgb-mosaic.tif
   └─ mosaic_nrg.vrt → ram-YYYY-MM-DDthhmmsscc-qdop-nrg-mosaic.tif

5. Thumbnail aus RGB-COG erstellen (thumbnail.jpg, 256px)

6. STAC-Upload (alle drei Assets im selben Item)
   ├─ Asset: ram-...-qdop-rgb-mosaic.tif
   ├─ Asset: ram-...-qdop-nrg-mosaic.tif
   └─ Asset: thumbnail.jpg
```

#### Output-Naming
```
Item:  ram-2024-07-15t14300000
Asset: ram-2024-07-15t14300000-qdop-rgb-mosaic.tif
Asset: ram-2024-07-15t14300000-qdop-nrg-mosaic.tif
Asset: thumbnail.jpg
```

## KML-Overview Generation

Nach Upload aller Einzelbilder wird automatisch ein KML-Overview erstellt:

### Funktionsweise
1. **STAC-Abfrage**: Suche alle Items des Tages mit Produkt-Suffix
2. **Filter**: Nur Fotos (keine Overview-KMLs)
3. **KML-Erstellung**:
   - Placemarks mit GPS-Position
   - Icon (konfigurierbar per Produkttyp)
   - Thumbnail-Preview
   - Link zum Fullres-Download
4. **Upload**: Als eigenes STAC-Item mit Zeitstempel 23:59:59

### KML-Beispiel (vereinfacht)
```xml
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>2024-07-15 Einzelbilder Nadir</name>
    <Style id="image_style">
      <IconStyle>
        <scale>0.75</scale>
        <Icon><href>https://map.geo.admin.ch/.../camera@1x.png</href></Icon>
      </IconStyle>
    </Style>
    <Placemark>
      <description><![CDATA[
        <a href="https://data.geo.admin.ch/.../photo.jpg">Download</a>
        <br><img src="https://data.geo.admin.ch/.../thumbnail.jpg">
      ]]></description>
      <Point><coordinates>7.654321,46.123456,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>
```

## Namenskonventionen

### Format
```
STAC Item:  ram-YYYY-MM-DDthhmmsscc
Asset:      ram-YYYY-MM-DDthhmmsscc-{product}-{type}.ext

Komponenten:
- ram:          Rapid Mapping Prefix
- YYYY-MM-DD:   Datum
- t:            Separator
- hhmmsscc:     Zeit (UTC) mit 2-stelligen Hundertelsekunden (default: 00)
- {product}:    qdop-rgb | qdop-nrg | ebn | ebo
- {type}:       mosaic | photo (optional)
- .ext:         .tif | .jpg | .kml | .txt
```

### Beispiele
```
Mosaike (QDOP-RGB, QDOP-NRG, QDOP-DMC4):
- Item:  ram-2024-07-15t14300000
- Assets:ram-2024-07-15t14300000-qdop-rgb-mosaic.tif
         ram-2024-07-15t14300000-qdop-nrg-mosaic.tif
         thumbnail.jpg

Einzelbilder:
- ram-2024-07-15t12052300-ebn-photo.jpg
- ram-2024-07-15t13451200-ebo-photo.jpg

Overview (KML + Downloadliste) — Zeitstempel 23:59:59.00:
- ram-2024-07-15t23595900-ebn.kml
- ram-2024-07-15t23595900-ebn.txt
- ram-2024-07-15t23595900-ebo.kml
- ram-2024-07-15t23595900-ebo.txt

Thumbnails:
- thumbnail.jpg (immer gleicher Name pro Item)
```

### STAC Item IDs
```
Format: ram-YYYY-MM-DDthhmmsscc  (kein Produktsuffix im Item-Namen)

Beispiele:
- ram-2024-07-15t14300000          (QDOP RGB/NRG/DMC4-Mosaic)
- ram-2024-07-15t12052300          (Einzelbild EBN oder EBO)
- ram-2024-07-15t23595900          (KML-Overview-Item EBN oder EBO)
```

## Konfigurationsdateien

### configuration.py

```python
# STAC-Einstellungen
STAC_COLLECTION = "ch.swisstopo.spezialbefliegungen"
GEOCAT_ID = "1d0fc41e-9526-41ef-bdcf-94ed7626abbd"
STAC_HOSTNAME = "sys-data.int.bgdi.ch"  # INT
STAC_HOSTNAME_PROD = "data.geo.admin.ch"  # PROD

# COG-Einstellungen
COG_CONFIG = {
    'compress': 'JPEG',
    'quality': 85,
    'blocksize': 256
}
COG_COMPRESS_OPTIONS = ['JPEG', 'LZW', 'DEFLATE', 'ZSTD', 'WEBP', 'NONE']  # wählbar in GUI/CLI

# Thumbnail-Einstellungen
THUMBNAIL_CONFIG = {
    'max_width': 640,
    'max_height': 480,
    'format': 'JPEG'
}

# Produkttypen
class ProductType(Enum):
    QDOP_RGB  = "qdop-rgb"
    QDOP_NRG  = "qdop-nrg"
    QDOP_DMC4 = "qdop-dmc4"  # DMC4 4-Kanal Streifen → erzeugt RGB + NRG
    EBN       = "ebn"         # Einzelbilder Nadir
    EBO       = "ebo"         # Einzelbilder Oblique
```

## Troubleshooting

### GDAL nicht gefunden
```
✗ GDAL-Tools nicht verfügbar
```
**Lösung:** 
- GDAL installieren (siehe Installation)
- OSGeo4W Shell verwenden
- PATH prüfen: `gdalinfo --version`

### Keine Internet-Verbindung
```
✗ Keine Internet-Verbindung möglich
```
**Lösung:**
- Proxy-URL in `secrets/proxy_config.json` prüfen
- Proxy-URL testen: `curl -x http://mein-proxy:8080 https://data.geo.admin.ch`
- Bei VPN: Script erkennt automatisch SSL-Inspection und passt Settings an

### 407 Proxy Authentication Required (Corporate-Proxy)
```
ProxyError: Tunnel connection failed: 407 Proxy authentication required
```
**Ursache:** Der Proxy verlangt Windows-Kerberos-Authentifizierung (Negotiate/SSPI).

**Lösung:**
```bash
pip install pyspnego        # empfohlen (modern, aktiv gepflegt, kein pywin32 nötig)
# ODER Legacy-Fallback:
pip install requests-negotiate-sspi
```
Voraussetzungen: Windows, am Active-Directory-Domain angemeldet.
Das Tool erkennt danach automatisch dass Kerberos benötigt wird — keine weitere Konfiguration.

### Credentials fehlen
```
✗ Keine Credentials gefunden
```
**Lösung:** 
- `secrets/stac_credentials.json` erstellen (siehe Konfiguration)
- ODER Environment Variables setzen
- Format prüfen (JSON muss gültig sein)

### 'secrets'-Ordner nicht gefunden (falsches Arbeitsverzeichnis)

Wird im interaktiven Modus (kein vollständiger `--product`/`--input`/`--timestamp`-Aufruf)
kein `secrets/`-Ordner im aktuellen Verzeichnis gefunden und sind auch keine
`STAC_USERNAME`/`STAC_PASSWORD`-Environment-Variablen gesetzt, fragt das Tool interaktiv
nach dem korrekten Pfad zum `secrets`-Ordner und wechselt automatisch dorthin — kein
manuelles Neustarten aus dem richtigen Verzeichnis nötig:

```
-> Pfad zum secrets-Ordner (Enter = abbrechen): C:\oed\temp\rm\secrets
```

Bei vollständigem CLI-Aufruf (Automation/Skripte) erscheint diese Nachfrage bewusst nicht
— dort bricht das Tool wie gewohnt mit einer klaren Fehlermeldung ab (siehe oben).

### GPS-Daten fehlen
```
✗ Keine GPS-Daten ermittelbar — Bild wird NICHT in STAC importiert
```
**Auswirkung:** Das Foto wird übersprungen (nicht importiert), nicht nur mit einer Warnung
versehen — steht mit Dateiname auch in der Verarbeitungszusammenfassung am Ende des Laufs.

**Lösung:** 
- EXIF-Tags in JPEGs prüfen
- `gdalinfo photo.jpg` ausführen
- GPS-Schreibrechte in Kamera prüfen

### COG-Konvertierung fehlgeschlagen
```
✗ COG-Konvertierung fehlgeschlagen
```
**Ursache:** Ist die Input-Datei kein COG, konvertiert das Tool sie automatisch (siehe
[Wenn Input NICHT COG-konform ist](#wenn-input-nicht-cog-konform-ist)). Diese Meldung
erscheint nur, wenn die automatische Konvertierung selbst scheitert (z.B. defekte/korrupte
Input-Datei) oder zu wenig freier Speicherplatz für die konvertierte Kopie vorhanden ist.

**Lösung:**
- Input-Datei mit `gdalinfo input.tif` auf Integrität prüfen
- Freien Speicherplatz am Zielort (`temp/` bzw. `output/`) prüfen
- Alternativ manuell konvertieren und das Ergebnis als Input verwenden:
```bash
gdal_translate -of COG \
  -co COMPRESS=JPEG \
  -co QUALITY=85 \
  -co BLOCKSIZE=256 \
  input.tif output_cog.tif
```

### VPN-Verbindung mit SSL-Problemen
```
⚠ VPN-Verbindung erkannt - SSL-Handling wird angepasst
```
**Erklärung:** Script erkennt automatisch VPN mit SSL-Inspection und deaktiviert SSL-Verifikation.

**Manueller Override** (falls Probleme):
```json
// In secrets/proxy_config.json
{
  "disable_ssl_warnings": true,
  // ...
}
```

## Logging

Das Script gibt detailliertes Feedback:

```
INFO:  ✓ Erfolgreiche Operation
WARNING: ⚠ Warnung (nicht kritisch)
ERROR: ✗ Fehler (kritisch)
```

### Log-Dateien

Jeder Lauf schreibt zusätzlich zur Konsolenausgabe eine Log-Datei nach `logs/`
(wird bei Bedarf automatisch angelegt). Namenskonvention:

```
logs/<stac-datum>_<produkttyp>_<importDatum>.log

Beispiel: logs/2025-09-03_ebn_20260908-143512.log
```

### Log-Level anpassen

In `rapidmapping_processor.py`:
```python
# Zeile 51-54
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG | INFO | WARNING | ERROR
    format='%(levelname)s: %(message)s'
)
```

### Temp-Verzeichnis bei Fehlern

Bei Fehlern bleibt `temp/` erhalten für Debugging:
```
temp/
├── ram-2024-07-15t120523-ebn.jpg  # Umbenanntes Foto
├── thumbnail.jpg                   # Thumbnail
└── ...                             # Weitere temporäre Dateien
```

## Workflow-Diagramm

### Orthophoto-Mosaike (QDOP-RGB / QDOP-NRG)
```
Input Directory (1 COG-TIF-Datei, 8-bit RGB)
    │
    ├─ Single-File-Check
    │  ├─ Ist COG? (Tiled + Overviews)
    │  └─ Ist 8-bit RGB? (3 Bänder, Byte)
    │
    ├─ Copy zu temp_dir
    │  └─ ram-YYYY-MM-DDthhmmsscc-qdop-rgb-mosaic.tif
    │
    ├─ Erstelle Thumbnail
    │  └─ thumbnail.jpg (256px)
    │
    └─ STAC-Upload → Item: ram-YYYY-MM-DDthhmmsscc
       ├─ Asset: .tif
       └─ Asset: thumbnail.jpg
```

### DMC4-Bildstreifen (QDOP-DMC4)
```
Input Directory (n × 4-Band TIF-Streifen, kein CRS)
    │
    ├─ Pro Streifen: CRS EPSG:2056 zuweisen + Bänder extrahieren
    │  ├─ Bänder 1,2,3 → RGB-Streifen
    │  └─ Bänder 4,1,2 → NRG-Streifen
    │
    ├─ gdalbuildvrt → mosaic_rgb.vrt + mosaic_nrg.vrt
    │
    ├─ gdal_translate -of COG
    │  ├─ ram-YYYY-MM-DDthhmmsscc-qdop-rgb-mosaic.tif
    │  └─ ram-YYYY-MM-DDthhmmsscc-qdop-nrg-mosaic.tif
    │
    ├─ Thumbnail aus RGB-COG → thumbnail.jpg (256px)
    │
    └─ STAC-Upload → Item: ram-YYYY-MM-DDthhmmsscc
       ├─ Asset: -qdop-rgb-mosaic.tif
       ├─ Asset: -qdop-nrg-mosaic.tif
       └─ Asset: thumbnail.jpg
```

### Einzelbilder (EBN / EBO)
```
Input Directory (Multiple JPEGs mit EXIF+GPS)
    │
    └─ Für jedes Foto:
       │
       ├─ EXIF extrahieren (GPS + Zeit)
       │
       ├─ Copy + Rename zu temp_dir
       │  └─ ram-YYYY-MM-DDthhmmsscc-ebn-photo.jpg
       │
       ├─ Erstelle Thumbnail
       │  └─ thumbnail.jpg (640x480px)
       │
       ├─ STAC-Upload → Item: ram-YYYY-MM-DDthhmmsscc
       │  ├─ Asset: .jpg
       │  └─ Asset: thumbnail.jpg
       │
       └─ Cleanup temp-Dateien

Nach allen Uploads:
    │
    ├─ Generiere Download-Liste
    │  └─ ram-YYYY-MM-DDt23595900-ebn.txt
    │
    └─ Generiere KML-Overview
       ├─ STAC-Abfrage: Alle Items des Tages
       ├─ Erstelle KML mit Placemarks
       └─ STAC-Upload → Item: ram-YYYY-MM-DDt23595900
          ├─ Asset: ram-YYYY-MM-DDt23595900-ebn.kml
          └─ Asset: ram-YYYY-MM-DDt23595900-ebn.txt
```

## Integration mit bestehenden Scripts

Das System nutzt die bestehenden Module:
- `util_publish_stac_fsdi.py`: STAC-Publikation
- `main_multipart_upload_via_api.py`: Multipart-Upload

Diese Module werden **NICHT modifiziert** und müssen im gleichen Verzeichnis liegen.

## Sicherheit

### Credentials
- **NIE in Git committen!**
- `secrets/` in `.gitignore` hinzufügen
- Environment Variables verwenden für CI/CD

### .gitignore Beispiel
```bash
# Credentials & Secrets
secrets/
*.json

# Temporary Files
temp/
*.pyc
__pycache__/
.venv/

# Logs
*.log
```

## Übergabe an CMS (rapidmapping.ch)

Nach erfolgreichem Upload gibt das Script URLs aus für die Integration auf rapidmapping.ch:

### Orthophotos (QDOP-RGB / QDOP-NRG / QDOP-DMC4)
```
Nächster Schritt für Quick Digital Orthophoto RGB:
  RGB: https://map.geo.admin.ch/#/map?layers=COG|https://data.geo.admin.ch/ch.swisstopo.spezialbefliegungen/ram-2024-07-15t14300000/ram-2024-07-15t14300000-qdop-rgb-mosaic.tif
  NRG: https://map.geo.admin.ch/#/map?layers=COG|https://data.geo.admin.ch/ch.swisstopo.spezialbefliegungen/ram-2024-07-15t14300000/ram-2024-07-15t14300000-qdop-nrg-mosaic.tif
Kartenausschnitt: als iFrame in rapidmapping.ch integrieren
```

### Einzelbilder (EBN / EBO)
```
Nächster Schritt für Einzelbilder Nadir:
  Karte:  https://map.geo.admin.ch/#/map?layers=KML|https://data.geo.admin.ch/ch.swisstopo.spezialbefliegungen/ram-2024-07-15t23595900/ram-2024-07-15t23595900-ebn.kml
  Liste:  https://data.geo.admin.ch/ch.swisstopo.spezialbefliegungen/ram-2024-07-15t23595900/ram-2024-07-15t23595900-ebn.txt
Kartenausschnitt: als iFrame in rapidmapping.ch integrieren
```

## Utilities

Wir stellen mehrere Hilfs-Scripts zur Verfügung, die bei verschiedenen Aufgaben unterstützen. Diese befinden sich im Verzeichnis [utilities](utilities/).

### rm_publish_quickorthophoto.sh/bat

#### Beschreibung
Ein Bash/DOS-Script zur Automatisierung der Publikation von Quick-Orthophoto-Produkten. Verarbeitet Exporte von ADS100-Flightlines (GeoTIFF-Dateien) und erstellt ein nahtloses Mosaic, das anschließend in ein Cloud Optimized GeoTIFF (COG) mit RGB-Bändern konvertiert wird. Basiert auf https://github.com/geostandards-ch/cog-best-practices

#### Features
- **Interaktive Eingabeaufforderungen** für Input/Output-Verzeichnisse, Dateiname und GSD (Ground Sample Distance)
- **Verwendet GDAL-Tools** (gdalbuildvrt, gdalwarp, gdal_translate) für effiziente Verarbeitung
- **Verarbeitet große Datensätze** mit Multi-Threading und optimierten Einstellungen

#### Verwendung

### Interaktiv (geführter Modus)

```bash
python rapidmapping_processor.py              # INT-Umgebung
python rapidmapping_processor.py --prod       # PROD-Umgebung
python rapidmapping_processor.py --upload=False  # Lokal speichern (kein Upload, WORK IN PROGRESS)
python rapidmapping_processor.py --debug      # Debug-Modus (sequentiell, volles Logging)
```

### Vollständig via CLI-Parameter

Alle Parameter können direkt übergeben werden
Kein interaktiver Dialog  --product, --input und --timestamp alle gesetzt sind

```bash
# EBN (Einzelbilder Nadir) — Datumsangabe
python rapidmapping_processor.py --product ebn --input C:\data\rm --timestamp 2025-09-03

# EBO (Einzelbilder Oblique)
python rapidmapping_processor.py --product ebo --input /data/rm --timestamp 2025-09-03

# QDOP RGB Mosaic — Zeitstempel mit Hundertelsekunden
python rapidmapping_processor.py --product qdop-rgb --input /data/rm --timestamp 2024-07-15t14300000

# QDOP NRG Mosaic — Produktion
python rapidmapping_processor.py --product qdop-nrg --input /data --timestamp 2024-07-15t143000 --prod

# Lokale Ausgabe ohne Upload (in ./output/)
python rapidmapping_processor.py --product ebn --input /data --timestamp 2025-09-03 --upload=False

# Debug + lokal 
python rapidmapping_processor.py --product ebn --input /data --timestamp 2025-09-03 --upload=False --debug

# QDOP-DMC4 (4-Kanal Bildstreifen → erzeugt RGB + NRG)
python rapidmapping_processor.py --product qdop-dmc4 --input /data/dmc4 --timestamp 2024-07-15t143000

# QDOP-DMC4 mit abweichender COG-Kompression
python rapidmapping_processor.py --product qdop-dmc4 --input /data/dmc4 --timestamp 2024-07-15t143000 --cog-compress LZW
python rapidmapping_processor.py --product qdop-dmc4 --input /data/dmc4 --timestamp 2024-07-15t143000 --cog-compress JPEG --cog-quality 85

# Netzwerk-Modus explizit setzen
python rapidmapping_processor.py --proxy direct --product ebn --input /data --timestamp 2025-09-03
python rapidmapping_processor.py --proxy system --product ebn --input /data --timestamp 2025-09-03
python rapidmapping_processor.py --proxy BVCOL  --product ebn --input /data --timestamp 2025-09-03
```

### Parameter-Übersicht

| Parameter | Werte | Beschreibung |
|-----------|-------|--------------|
| `--product` | `ebn`, `ebo`, `qdop-rgb`, `qdop-nrg`, `qdop-dmc4` | Produkttyp |
| `--input` | Pfad | Quellverzeichnis mit Eingabedaten |
| `--timestamp` | `YYYY-MM-DD` oder `YYYY-MM-DDthhmmss[cc]` | Datum/Zeitstempel |
| `--proxy` | `auto`, `direct`, `system`, Proxy-Name | Netzwerk-Modus. Wenn weggelassen: `auto` im CLI-Modus, interaktive Auswahl im Dialog-Modus |
| `--upload` | `True` / `False` | Upload zu STAC (False → ./output/) |
| `--prod` | Flag | Produktionsumgebung (default: INT) |
| `--debug` | Flag | Sequentiell + volles Logging |
| `--cog-compress` | `JPEG`, `LZW`, `DEFLATE`, `ZSTD`, `WEBP`, `NONE` | COG-Kompressionsverfahren, nur für `qdop-dmc4` (default: `JPEG`) |
| `--cog-quality` | `1`-`100` | JPEG-Qualität für COG, nur bei `--cog-compress JPEG` (default: `85`) |

### Debug-Modus direkt im Code setzen

Für Entwicklung ohne CLI-Argumente kann `DEBUG_MODE_DEFAULT` direkt in `rapidmapping_processor.py` gesetzt werden:

```python
# Zeile ~250 in rapidmapping_processor.py
DEBUG_MODE_DEFAULT = True   # Debug ein
DEBUG_MODE_DEFAULT = False  # Debug aus (Produktion)
```

## STAC Item- und Asset-Namenskonvention

### Zeitstempel mit Hundertelsekunden (alle Produkte)

Alle Items und Assets enthalten immer einen 2-stelligen Hundertelsekunden-Suffix (`cc`, default `00`):

```
ram-YYYY-MM-DDthhmmsscc
```

Beispiele:
- `ram-2025-09-03t12523700`  (kein Burst, cc=00)
- `ram-2025-09-03t08002801`  (Burst-Frame 1, cc=01)
- `ram-2025-09-03t08002802`  (Burst-Frame 2, cc=02)

### QDOP RGB/NRG Mosaike — gemeinsames Item

Beide Mosaikvarianten (RGB und NRG) desselben Aufnahmezeitpunkts werden als Assets **im selben STAC Item** gespeichert:

```
Item:   ram-2024-07-15t14300000
Assets: ram-2024-07-15t14300000-qdop-rgb-mosaic.tif
        ram-2024-07-15t14300000-qdop-nrg-mosaic.tif
        thumbnail.jpg
```

### EBN / EBO Einzelbilder

```
Item:   ram-2025-09-03t12523700
Assets: ram-2025-09-03t12523700-ebn-photo.jpg
        thumbnail.jpg
```
### rm_process_pug_images.py

#### Beschreibung
Dieses Script verarbeitet PUG-Bilder ([Beispiel](https://data.geo.admin.ch/ch.swisstopo.rapidmapping/data/2024-008-TICINO/i240630_121859-0.jpg)) durch Extraktion von EXIF-Daten, Anwendung von Masken und Erstellung einer KML-Datei mit Bild-Vorschauen und Standortdaten.

#### Features
- Extrahiert Text aus vordefinierten Begrenzungsrahmen mit EasyOCR
- Wendet Masken auf Bilder an und speichert die maskierten Bilder
- Extrahiert und modifiziert EXIF-Daten (Datum, Zeit, GPS-Koordinaten)
- Generiert eine KML-Datei mit Bild-Vorschauen und Koordinaten
- Protokolliert Fehler für Bilder, die nicht georeferenziert werden können

#### Verwendung

##### Python
Dieses Script benötigt zusätzliche Python-Module. Getestet mit Python 3.10.12 und 3.11.9.
```sh
pip install -r requirements.txt
python rm_process_pug_images.py
```

**Ablauf:**
1. Führen Sie das Script aus
2. Geben Sie den Pfad zum Input-Verzeichnis ein (enthält PNG-Bilder)
3. Geben Sie den Pfad zum Output-Verzeichnis ein (für verarbeitete Bilder und KML-Datei)
4. Falls `pgu_mask.png` nicht im aktuellen Verzeichnis gefunden wird, geben Sie den Pfad dazu an
5. Das Script verarbeitet jedes Bild, wendet Masken an, extrahiert EXIF-Daten und erstellt eine KML-Datei mit Bild-Vorschauen und Koordinaten
6. Eine Fehler-Datei (`not_processed.txt`) wird für Dateien erstellt, die nicht georeferenziert werden konnten

##### Ausführbare Binärdateien / EXE
Download von [v0.0.1-alpha](https://github.com/swisstopo/topo-rapidmapping/releases/tag/v0.0.1-alpha)

**Benötigte Dateien:**
- `pgu_mask.png`
- Ordner `models` inkl. Inhalt
- `rm_process_pug_images.exe`

**Ablauf:**
1. Führen Sie `rm_process_pug_images.exe` aus
2. Folgen Sie den interaktiven Eingabeaufforderungen (siehe Python-Ablauf oben)

---

### util_stac_delete_ram.py

#### Beschreibung
Hilfs-Script zum Löschen von Rapid-Mapping-Items aus der STAC-Plattform.

#### Features
- Löschen einzelner Items oder ganzer Datensätze
- Sicherheitsabfrage vor Löschung
- Unterstützung für INT und PROD-Umgebungen

#### Verwendung
```bash
python util_stac_delete_ram.py
```

**Interaktiver Ablauf:**
1. Wählen Sie Umgebung (INT/PROD)
2. Geben Sie Item-Name oder Datum ein
3. Bestätigen Sie die Löschung

**Vorsicht:** Gelöschte Items können nicht wiederhergestellt werden!

## Generate Executable binaries / EXE  ( for now: WINDOWS only)

The WINDOWS version was created with pyinstaller. [quite a thing](https://stackoverflow.com/questions/56472933/pyinstaller-executable-fails).
Solution steps

1. Install pip packages
   ```sh
   pip install pyinstaller
    ```

**One EXE Use the provided .bat creator (recommended)**
1. Run script
   ```sh
   ./pyinstaller_onefile.bat
    ```
2. Create your secrets folder in the same dir
  - `proxy_config.json`
  - `stac_credentials.json`

**One DIR Use the provided .bat creator**
Use this approach if the generated EXE  throws some errors...
1. Run script
   ```sh
   ./pyinstaller_onedir.bat
    ```
2. Create your secrets folder in the same dir
  - `proxy_config.json`
  - `stac_credentials.json`

3. The generated EXE must be *signed* by the IT department (ask Urs B.).
  
**Do it  manually**
If the above fails 

1. run pyinstaller 
   ```sh
   pyinstaller --noconfirm --onedir --console --noupx --name rapidmapping_processor --add-data "configuration.py;." --add-data "utilities;utilities" --add-data "util_publish_stac_fsdi.py;." --add-data "main_multipart_upload_via_api.py;." --hidden-import=utilities.credentials --hidden-import=utilities.proxy_handler --hidden-import=utilities.file_handler --hidden-import=utilities.mosaic_processor --hidden-import=utilities.photo_processor --hidden-import=utilities.kml_generator --hidden-import=utilities.stac_publisher --hidden-import=requests_negotiate_sspi --hidden-import=sspi --hidden-import=sspicon --hidden-import=win32timezone --hidden-import=rasterio.serde --hidden-import=rasterio._shim --hidden-import=rasterio.sample --collect-submodules=rasterio rapidmapping_processor.py
   ```
  

2. Create your secrets folder in the same dir
  - `proxy_config.json`
  - `stac_credentials.json`

3. The generated EXE must be *signed* by the IT department (ask Urs B.). 

## Support

Bei Problemen:
1. Log-Output prüfen
2. `temp/` Verzeichnis inspizieren (wird bei Fehler nicht gelöscht)
3. GDAL-Installation testen: `gdalinfo --version`
4. Proxy-Verbindung testen (siehe Troubleshooting)

## Performance-Tipps

### Upload-Geschwindigkeit
- **Multipart-Upload**: Für jedes Asset verwendet, Part-Grösse passt sich der Dateigrösse an (siehe unten) — kein hartes Limit mehr bei sehr grossen Mosaiken
- **Batch-Processing**: Einzelbilder werden sequenziell verarbeitet
- **Thumbnail-Größe**: 640x480px für schnelleren Upload

### Multipart-Upload bei sehr grossen Assets

Die STAC-API begrenzt Multipart-Uploads auf maximal 100 Parts. Mit der fixen Standard-
Part-Grösse von 250 MB deckelt das ein einzelnes Asset bei ca. 24.4 GB. Ab dieser Grösse
wird die Part-Grösse automatisch erhöht (Ziel: ~90 Parts, mit Sicherheitsmarge unter dem
Limit), sodass auch grössere DMC4-/QDOP-Mosaike zuverlässig hochgeladen werden können —
für alle kleineren Assets ändert sich nichts, die Part-Grösse bleibt bei 250 MB.

### Proxy/VPN
- **VPN-Detection**: Automatisch SSL-Handling anpassen
- **Proxy-Tests**: Cached nach erstem Durchlauf
- **Timeout**: Anpassbar in `proxy_config.json`

## Weiterführende Dokumentation

- **GDAL COG Best Practices**: https://github.com/geostandards-ch/cog-best-practices
- **STAC Specification**: https://stacspec.org/
- **FSDI STAC Browser**: https://data.geo.admin.ch/browser/
- **OSGeo4W**: https://trac.osgeo.org/osgeo4w/

## Lizenz

MIT

## Version History

### v2.4 (2025-09)
- **GUI**: Formularbasierte Oberfläche (`0_GUI_rapidmapping_STACimport.py`) als Alternative zur CLI, baut dieselben CLI-Flags und läuft weiterhin über `rapidmapping_processor.py`/`.exe` als Subprocess
- **QDOP-DMC4 COG-Optionen**: Neue Parameter `--cog-compress` / `--cog-quality` zur Steuerung der COG-Kompression (default: JPEG/85, vorher fix JPEG/75)
- **Automatische COG-Konvertierung (QDOP RGB/NRG)**: Ist die Input-Datei kein COG, wird sie automatisch konvertiert (`utilities/mosaic_processor.convert_to_cog`, via `rasterio.shutil.copy`, keine neue Abhängigkeit, funktioniert in der EXE) statt den Lauf abzubrechen. Original bleibt unverändert, Kompression/Qualität aus `COG_CONFIG`, RGB und NRG werden gleich behandelt (beide JPEG-komprimiert). Vor der Konvertierung wird der freie Speicherplatz geprüft; die temporäre `*_cog.tif` wird nach erfolgreicher Publikation mit dem restlichen `temp/`-Verzeichnis gelöscht
- **Fix: EXIF-Timestamp-Fallback (EBN/EBO)**: `parse_exif_timestamp()` gibt `None` zurück statt auf das aktuelle Datum zurückzufallen, wenn weder EXIF noch Dateiname einen Timestamp liefern. Das Foto wird übersprungen (nicht mehr fälschlicherweise mit dem heutigen Datum in STAC importiert) und mit Dateiname klar protokolliert (Terminal + Log), sowohl direkt beim Verarbeiten als auch gesammelt in der Verarbeitungszusammenfassung
- **Fehlende GPS-Daten (EBN/EBO) wie fehlender Timestamp behandelt**: Fotos ohne ermittelbare GPS-Koordinaten werden jetzt ebenfalls übersprungen statt ohne Position importiert zu werden, gleich protokolliert (Terminal + Log, Dateiname in der Verarbeitungszusammenfassung) wie beim fehlenden Timestamp
- **Fix: `asset_create_title`**: wirft bei nicht erkennbarem Dateimuster eine klare `ValueError` statt eines `AttributeError`
- **Log-Dateien**: werden jetzt in `logs/` statt im Hauptverzeichnis abgelegt, neue Namenskonvention `<stac-datum>_<produkttyp>_<importDatum>.log` (vorher `Log_<produkttyp>_<importDatum>.txt` im Hauptverzeichnis)
- **Fix: KML/CSV-STAC-Abfrage (`kml_generator.query_stac_items_by_date`)**: Paginierung folgte bei einem GET-'next'-Link fälschlicherweise trotzdem mit POST weiter (konnte die Seite verpassen und die Paginierung vorzeitig abbrechen). Zusätzlich wird jedes Ergebnis jetzt clientseitig gegen das angefragte Datum geprüft — sollte der serverseitige `datetime`-Filter nicht greifen, landen dadurch keine Items anderer Tage mehr im KML/CSV, statt effektiv den ganzen Katalog zu verarbeiten. Ein ungewöhnlich hohes Seitenaufkommen für einen einzelnen Tag wird jetzt protokolliert
- **Interaktive Nachfrage bei fehlendem `secrets`-Ordner**: Im interaktiven Modus fragt das Tool jetzt nach dem korrekten Pfad und wechselt automatisch dorthin, statt erst später mit einer unklaren Fehlermeldung abzubrechen — hilfreich, wenn die App mal nicht im selben Verzeichnis wie `secrets/` gestartet wurde
- **Dynamische Multipart-Upload-Part-Grösse**: `util_publish_stac_fsdi.py` berechnet die Part-Grösse jetzt aus der Asset-Grösse (Ziel ~90 Parts), statt die feste 250-MB-Grösse zu verwenden — verhindert, dass sehr grosse Assets (> ca. 24.4 GB) am 100-Parts-Limit der STAC-API scheitern. Für normal grosse Assets bleibt die Part-Grösse unverändert bei 250 MB
- **Fix: UnicodeEncodeError im Multipart-Upload-Fortschrittsbalken**: `main_multipart_upload_via_api.py` reconfiguriert stdout/stderr jetzt auf UTF-8, statt bei fehlender echter Konsole (z.B. GUI-Subprocess) an den Fortschrittsbalken-Zeichen (█ ░ ✓) abzustürzen — der Upload selbst war davon zwar nicht betroffen, aber der Absturz verschleierte den tatsächlichen Erfolg

### v2.3 (2025-05)
- **Kerberos-Proxy EXE-Fix**: 407-Fehler in der generierten EXE behoben (win32timezone + SSPI-Tunnel-Patch)
- **GDAL Performance**: Alle GDAL-Operationen nutzen jetzt `NUM_THREADS ALL_CPUS` und `GDAL_CACHEMAX 512`
- **Proxy-Doku**: Verbesserte Dokumentation und `proxy_config.examples`

### v2.2 (2025-05)
- **QDOP-DMC4**: Neuer Produkttyp für 4-Kanal DMC4-Bildstreifen (→ RGB + NRG COG)
- **Overview-Naming**: Kein `-overview`-Suffix mehr im STAC Item-Namen; Produktkürzel (`ebn`/`ebo`) im Asset-Dateinamen
- **EBO-Overview-Icon**: Korrektes Kamera-Icon für EBO KML-Overview-Items
- Alle Item-Namen und Assets enthalten immer 2-stelligen Hundertelsekunden-Suffix (`cc`, default `00`)

### v2.0 (2025-01)
- Single COG-File Workflow (kein Mosaic mehr im Script)
- Subprocess-basiertes GDAL (keine Python-Bindings erforderlich)
- VPN-Support mit automatischer SSL-Erkennung
- KML-Overview via STAC-Abfrage nach Upload
- Batch-Upload für Einzelbilder
- Robustes Error Handling
- Multi-Environment Support (INT/PROD)

### v1.0 (Legacy)
- Mosaic-Erstellung im Script
- Basic STAC-Upload
- Einzelbild-Verarbeitung
