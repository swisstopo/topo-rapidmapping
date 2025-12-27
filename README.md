# Swisstopo Rapid Mapping Processor 2.0

Automatisiertes System für die Publikation von Rapid Mapping Daten auf der FSDI STAC Plattform.

## 🎯 Übersicht

Dieses Tool vereint die Funktionalität von:
- Orthophoto-Mosaike
- Einzelbilder
- STAC-Publikation

in einem einzigen, benutzerfreundlichen Workflow mit automatischer Proxy-Erkennung und VPN-Support.

### ⚡ Hauptfeatures

- ✅ **Single COG-File Workflow**: Prüft ob Input bereits COG-konform ist (8-bit RGB, 3 Bänder)
- ✅ **Automatische Proxy-Erkennung**: VPN- und Corporate-Proxy-Support mit SSL-Handling
- ✅ **EXIF-Extraktion**: GPS und Zeitstempel aus Einzelbildern
- ✅ **KML-Overview**: Automatische Generierung via STAC-Abfrage nach Upload
- ✅ **Multi-Environment**: INT und PROD-Support
- ✅ **Batch-Upload**: Einzelbilder werden sequenziell hochgeladen
- ✅ **Error Handling**: Robuste Fehlerbehandlung mit detaillierten Logs

## 📁 Projektstruktur

```
rapidmapping_processor/
├── rapidmapping_processor.py      # Hauptskript (CLI)
├── configuration.py                # Produktdefinitionen & Konfiguration
├── requirements.txt                # Python-Dependencies
├── setup.bat                       # Windows Setup-Script
├── README.md                       # Diese Datei
├── utilities/                      # Hilfsfunktionen
│   ├── credentials.py             # Credentials-Management (INT/PROD)
│   ├── proxy_handler.py           # Proxy-Erkennung & VPN-Support
│   ├── file_handler.py            # Datei-Operationen
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

## 🚀 Installation

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

### 2. Python Virtual Environment (empfohlen)

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
- ✓ Python-Installation
- ✓ GDAL-Verfügbarkeit
- ✓ Erstellt Verzeichnisstruktur
- ✓ Installiert Dependencies
- ✓ Prüft Credentials

## 🔐 Konfiguration

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

### Proxy-Konfiguration

Erstelle `secrets/proxy_config.json`:

```json
{
  "proxies": [
    {
      "name": "Mein Proxy",
      "url": "http://mein-proxy.ch:8080",
      "enabled": true
    },
    {
      "name": "Alternative Proxy",
      "url": "http://your-proxy:8080",
      "enabled": false
    }
  ],
  "test_url": "https://data.geo.admin.ch/browser/index.html",
  "timeout": 5,
  "disable_ssl_warnings": true
}
```

**Features:**
- ✅ **Automatische Proxy-Erkennung**: Testet direkte Verbindung zuerst
- ✅ **VPN-Detection**: Erkennt VPN mit SSL-Inspection und deaktiviert SSL-Verifikation automatisch
- ✅ **Multi-Proxy-Support**: Testet alle aktivierten Proxies in Reihenfolge
- ✅ **Fallback**: Bei fehlender Config wird Default-Proxy versucht

## 💻 Verwendung

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
4. **Zeitstempel** (bei Mosaiken) oder nur Datum (bei Einzelbildern)
5. **Bestätigung** und Start

## 📦 Produkttypen & Workflows

### 1. QDOP RGB/NRG Mosaike (Orthophotos)

#### Input Requirements
- **Verzeichnis mit genau 1 TIF-Datei**
- **COG-konform** (Cloud Optimized GeoTIFF)
- **8-bit RGB** (3 Bänder, Datatype "Byte")

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
   ├─ Asset: ram-YYYY-MM-DDthhmmss-qdop-rgb-mosaic.tif
   └─ Asset: thumbnail.jpg
```

#### Output-Naming
```
Item:  ram-2024-07-15t143000-qdop-rgb-mosaic
Asset: ram-2024-07-15t143000-qdop-rgb-mosaic.tif
Asset: thumbnail.jpg
```

#### Wenn Input NICHT COG-konform ist

Script gibt Fehler aus mit Anleitung zur COG-Konvertierung:

```bash
✗ Datei ist KEIN Cloud Optimized GeoTIFF (COG)!
  Bitte konvertiere zu COG mit:
    gemäss https://github.com/geostandards-ch/cog-best-practices#lossy-visual-image-with-transparency
```

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
   │  → YYYY-MM-DD-ebn.txt (alle URLs)
   │
   └─ Generiere KML-Overview (via STAC-Abfrage)
      ├─ Abfrage: Alle Items des Tages
      ├─ Erstelle KML mit Placemarks
      │  └─ Icon, Thumbnail, GPS-Position
      └─ Upload als: ram-YYYY-MM-DDt235959-ebn-overview.kml
```

#### Output-Naming (pro Foto)
```
Item:  ram-2024-07-15t120523-ebn
Asset: ram-2024-07-15t120523-ebn.jpg (Original)
Asset: thumbnail.jpg (640x480px Thumbnail)
```

#### Output-Naming (KML-Overview)
```
Item:  ram-2024-07-15t235959-ebn-overview
Asset: ram-2024-07-15t235959-ebn-overview.kml
```

#### GPS-Koordinaten Handling
- **DMS → Dezimal-Konvertierung** (6 Dezimalstellen Präzision)
- **Warnung bei fehlenden GPS-Daten**: Foto wird übersprungen
- **KML**: Nur Fotos mit GPS-Daten werden eingebunden

## 🗺️ KML-Overview Generation

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

## 📋 Namenskonventionen

### Format
```
ram-YYYY-MM-DDthhmmss-{product}-{type}.ext

Komponenten:
- ram:          Rapid Mapping Prefix
- YYYY-MM-DD:   Datum
- t:            Separator
- hhmmss:       Zeit (UTC)
- {product}:    qdop-rgb | qdop-nrg | ebn | ebo
- {type}:       mosaic | photo | overview (optional)
- .ext:         .tif | .jpg | .kml
```

### Beispiele
```
Mosaike:
- ram-2024-07-15t143000-qdop-rgb-mosaic.tif
- ram-2024-07-15t143000-qdop-nrg-mosaic.tif

Einzelbilder:
- ram-2024-07-15t120523-ebn.jpg
- ram-2024-07-15t134512-ebo.jpg

Overview:
- ram-2024-07-15t235959-ebn-overview.kml
- ram-2024-07-15t235959-ebo-overview.kml

Thumbnails:
- thumbnail.jpg (immer gleicher Name pro Item)
```

### STAC Item IDs
```
Format: ram-YYYY-MM-DDthhmmss-{product}

Beispiele:
- ram-2024-07-15t143000-qdop-rgb-mosaic
- ram-2024-07-15t120523-ebn
- ram-2024-07-15t235959-ebn-overview
```

## 🔧 Konfigurationsdateien

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
    'quality': 75,
    'blocksize': 256
}

# Thumbnail-Einstellungen
THUMBNAIL_CONFIG = {
    'max_width': 640,
    'max_height': 480,
    'format': 'JPEG'
}

# Produkttypen
class ProductType(Enum):
    QDOP_RGB = "qdop-rgb"
    QDOP_NRG = "qdop-nrg"
    EBN = "ebn"  # Einzelbilder Nadir
    EBO = "ebo"  # Einzelbilder Oblique
```

## 🛠️ Troubleshooting

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
- Proxy-Einstellungen prüfen in `secrets/proxy_config.json`
- Proxy-URL testen: `curl -x http://mein-proxy:8080 https://data.geo.admin.ch`
- Bei VPN: Script erkennt automatisch SSL-Inspection und passt Settings an

### Credentials fehlen
```
✗ Keine Credentials gefunden
```
**Lösung:** 
- `secrets/stac_credentials.json` erstellen (siehe Konfiguration)
- ODER Environment Variables setzen
- Format prüfen (JSON muss gültig sein)

### GPS-Daten fehlen
```
⚠ Keine GPS-Daten gefunden
```
**Lösung:** 
- EXIF-Tags in JPEGs prüfen
- `gdalinfo photo.jpg` ausführen
- GPS-Schreibrechte in Kamera prüfen

### COG-Check fehlgeschlagen
```
✗ Datei ist KEIN Cloud Optimized GeoTIFF (COG)!
```
**Lösung:**
```bash
# Konvertiere zu COG
gdal_translate -of COG \
  -co COMPRESS=JPEG \
  -co QUALITY=75 \
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

## 📊 Logging

Das Script gibt detailliertes Feedback:

```
INFO:  ✓ Erfolgreiche Operation
WARNING: ⚠ Warnung (nicht kritisch)
ERROR: ✗ Fehler (kritisch)
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

## 📄 Workflow-Diagramm

### Orthophoto-Mosaike
```
Input Directory (1 TIF-Datei)
    │
    ├─ Single-File-Check
    │  ├─ Ist COG? (Tiled + Overviews)
    │  └─ Ist 8-bit RGB? (3 Bänder, Byte)
    │
    ├─ Copy zu temp_dir
    │  └─ ram-YYYY-MM-DDthhmmss-qdop-rgb-mosaic.tif
    │
    ├─ Erstelle Thumbnail
    │  └─ thumbnail.jpg (256px)
    │
    └─ STAC-Upload
       ├─ Asset: .tif
       └─ Asset: thumbnail.jpg
```

### Einzelbilder
```
Input Directory (Multiple JPEGs)
    │
    └─ Für jedes Foto:
       │
       ├─ EXIF extrahieren (GPS + Zeit)
       │
       ├─ Copy + Rename zu temp_dir
       │  └─ ram-YYYY-MM-DDthhmmss-ebn.jpg
       │
       ├─ Erstelle Thumbnail
       │  └─ thumbnail.jpg (640x480px)
       │
       ├─ STAC-Upload
       │  ├─ Asset: .jpg
       │  └─ Asset: thumbnail.jpg
       │
       └─ Cleanup temp-Dateien

Nach allen Uploads:
    │
    ├─ Generiere Download-Liste
    │  └─ YYYY-MM-DD-ebn.txt
    │
    └─ Generiere KML-Overview
       ├─ STAC-Abfrage: Alle Items des Tages
       ├─ Erstelle KML mit Placemarks
       └─ STAC-Upload: ram-YYYY-MM-DDt235959-ebn-overview.kml
```

## 🤝 Integration mit bestehenden Scripts

Das System nutzt die bestehenden Module:
- `util_publish_stac_fsdi.py`: STAC-Publikation
- `main_multipart_upload_via_api.py`: Multipart-Upload

Diese Module werden **NICHT modifiziert** und müssen im gleichen Verzeichnis liegen.

## 🔒 Sicherheit

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

## 🚦 Übergabe an CMS (rapidmapping.ch)

Nach erfolgreichem Upload gibt das Script URLs aus für die Integration auf rapidmapping.ch:

### Orthophotos
```
Nächster Schritt für Quick Digital Orthophoto RGB:
1) URL öffnen: https://map.geo.admin.ch/#/map?layers=COG|https://data.geo.admin.ch/ch.swisstopo.spezialbefliegungen/ram-2024-07-15t143000-qdop-rgb-mosaic/ram-2024-07-15t143000-qdop-rgb-mosaic.tif
2) Kartenausschnitt: als iFrame in rapidmapping.ch integrieren
```

### Einzelbilder
```
Nächster Schritt für Einzelbilder Nadir:
1) URL öffnen: https://map.geo.admin.ch/#/map?layers=KML|https://data.geo.admin.ch/ch.swisstopo.spezialbefliegungen/ram-2024-07-15t235959-ebn-overview/ram-2024-07-15t235959-ebn-overview.kml
2) Kartenausschnitt: als iFrame in rapidmapping.ch integrieren
3) Downloadliste: 2024-07-15-ebn.txt
```

## 📞 Support

Bei Problemen:
1. Log-Output prüfen
2. `temp/` Verzeichnis inspizieren (wird bei Fehler nicht gelöscht)
3. GDAL-Installation testen: `gdalinfo --version`
4. Proxy-Verbindung testen (siehe Troubleshooting)

## ⚡ Performance-Tipps

### Upload-Geschwindigkeit
- **Multipart-Upload**: Automatisch für große Dateien (>100MB)
- **Batch-Processing**: Einzelbilder werden sequenziell verarbeitet
- **Thumbnail-Größe**: 640x480px für schnelleren Upload

### Proxy/VPN
- **VPN-Detection**: Automatisch SSL-Handling anpassen
- **Proxy-Tests**: Cached nach erstem Durchlauf
- **Timeout**: Anpassbar in `proxy_config.json`

## 📚 Weiterführende Dokumentation

- **GDAL COG Best Practices**: https://github.com/geostandards-ch/cog-best-practices
- **STAC Specification**: https://stacspec.org/
- **FSDI STAC Browser**: https://data.geo.admin.ch/browser/
- **OSGeo4W**: https://trac.osgeo.org/osgeo4w/

## 📄 Lizenz

Swisstopo Internal Use Only

## ✨ Version History

### v2.0 (2025-01)
- ✅ Single COG-File Workflow (kein Mosaic mehr im Script)
- ✅ Subprocess-basiertes GDAL (keine Python-Bindings erforderlich)
- ✅ VPN-Support mit automatischer SSL-Erkennung
- ✅ KML-Overview via STAC-Abfrage nach Upload
- ✅ Batch-Upload für Einzelbilder
- ✅ Robustes Error Handling
- ✅ Multi-Environment Support (INT/PROD)

### v1.0 (Legacy)
- ✓ Mosaic-Erstellung im Script
- ✓ Basic STAC-Upload
- ✓ Einzelbild-Verarbeitung