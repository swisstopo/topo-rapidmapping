# Rapid Mapping Processor

Automatisiertes System für die Publikation von Rapid Mapping Daten auf der FSDI STAC Plattform.

## 🎯 Übersicht

Dieses Tool vereint die Funktionalität von:
- `rm_publish_quickorthophoto.bat` (Orthophoto-Mosaike)
- `rm_publish_einzelbilder.py` (Einzelbilder)
- `util_publish_stac_fsdi.py` (STAC-Publikation)

in einem einzigen, benutzerfreundlichen Workflow.

## 📁 Projektstruktur

```bash
rapidmapping_processor/
├── rapidmapping_processor.py      # Hauptskript (CLI)
├── configuration.py                # Produktdefinitionen & Konfiguration
├── requirements.txt                # Python-Dependencies
├── README.md                       # Diese Datei
├── utilities/                      # Hilfsfunktionen
│   ├── __init__.py
│   ├── credentials.py             # Credentials-Management
│   ├── proxy_handler.py           # Proxy-Erkennung
│   ├── file_handler.py            # Datei-Operationen
│   ├── mosaic_processor.py        # Orthophoto-Verarbeitung
│   ├── photo_processor.py         # Einzelbild-Verarbeitung
│   └── stac_publisher.py          # STAC-Publikation
├── secrets/                        # Credentials (NICHT in Git!)
│   └── stac_credentials.json      # STAC API-Keys
├── temp/                           # Temporäre Dateien (wird gelöscht)
└── util_publish_stac_fsdi.py      # Bestehender STAC-Publisher
    main_multipart_upload_via_api.py # Multipart-Upload
```

## 🚀 Installation

### 1. GDAL-Tools installieren ( kommt mit QGIS)

#### Windows (OSGeo4W Shell)
1. Download: https://trac.osgeo.org/osgeo4w/
2. Installiere GDAL-Pakete
3. Führe Script in OSGeo4W Shell aus

### 2. venv Python-Dependencies

```bash
"C:\Program Files\QGIS 3.40.7\apps\Python312\python.exe" -m venv .venv --system-site-packages
.venv\Scripts\activate    

pip install -r requirements.txt
```



#### Linux
```bash
sudo apt update
sudo apt install gdal-bin python3-gdal
```

### 3. Credentials konfigurieren

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
Erstelle `secrets/proxy_config.json`:

```json
{
  "proxies": [
    {
      "name": "Swiss Federal Admin Proxy",
      "url": "http://proxy-bvcol.admin.ch:8080",
      "enabled": true
    },
    {
      "name": "Alternative Proxy",
      "url": "http://your-proxy:8080",
      "enabled": false
    }
  ],
  "test_url": "https://data.geo.admin.ch/browser/index.html",
  "timeout": 5
}
```


**Alternative:** Environment Variables setzen:
```bash
export STAC_USERNAME=your_username
export STAC_PASSWORD=your_password
```

## 💻 Verwendung

INT-Environment (Standard)

```bash
python rapidmapping_processor.py
```
PROD-Environment

```bash
python rapidmapping_processor.py --prod
```
Ohne Upload (nur lokale Verarbeitung)
```bash
python rapidmapping_processor.py --upload=False
```

### Grundlegender Workflow

1. QDOP RGB/NRG Mosaike
Input: Verzeichnis mit TIF-Dateien
Workflow:

```bash
1. Single-File-Check
   ├─ Wenn 1 Datei + COG + 8-bit RGB → Direkt-Upload ⚡
   └─ Sonst: Mosaic-Workflow
2. Mosaic-Workflow (bei Multiple Files)
   ├─ VRT-Mosaic erstellen (GDAL BuildVRT)
   ├─ Warping mit GSD (GDAL Warp)
   └─ COG-Konvertierung (GDAL Translate)
3. STAC-Upload
   └─ Item: ram-YYYY-MM-DDthhmmss-qdop-rgb-mosaic
```
Output:

```bash
ram-2024-07-15t143000-qdop-rgb-mosaic.tif
```

2. Einzelbilder (EBN/EBO)
Input: Verzeichnis mit JPEG-Dateien
```bash
1. Photo-Verarbeitung
   ├─ EXIF extrahieren (GPS + Timestamp)
   └─ Thumbnail erstellen
   
2. Einzelner Upload pro Photo
   ├─ Temporär umbenennen:
   │  ├─ Photo: ram-YYYY-MM-DDthhmmss-ebn.jpg
   │  └─ Thumbnail: thumbnail.jpg
   ├─ STAC-Upload
   └─ Rückbenennen zu Original
   
3. KML-Overview generieren
   ├─ Sammle alle Photos des Tages
   ├─ Erstelle KML mit Placemarks
   └─ Upload als: ram-YYYY-MM-DDt235959-ebn-overview.kml
```
Output pro Photo:
```bash
Item: ram-2024-07-15t120000-ebn
Assets:

    ram-2024-07-15t120000-ebn.jpg (Original)
    thumbnail.jpg (Thumbnail)
```

Output Overview:
```bash
Item: ram-2024-07-15t235959-ebn-overview
Asset: ram-2024-07-15t235959-ebn-overview.km
```
### Interaktive Eingaben

Das Script führt durch folgende Schritte:

1. **Proxy-Erkennung** (automatisch)
2. **Input-Verzeichnis** angeben
3. **Produkttyp** auswählen:
   - QDOP RGB Mosaic
   - QDOP NRG Mosaic
   - Einzelbilder Nadir (EBN)
   - Einzelbilder Oblique (EBO)
4. **Zeitstempel** (bei Mosaiken) oder EXIF-Extraktion (bei Einzelbildern)
5. **GSD** (bei Mosaiken)
6. Bestätigung und Start

## 📦 Produkttypen

### 1. QDOP RGB/NRG Mosaike

**Input:** Verzeichnis mit TIF-Dateien (ADS100 Flightlines)

**Output:**
- COG-TIFF Mosaic: `ram-YYYY-MM-DDthhmmss-qdop-rgb-mosaic.tif`
- STAC Item: `YYYY-MM-DDthhmmss`

**Workflow:**
1. VRT-Mosaic erstellen
2. Warping mit gewünschtem GSD
3. COG-Konvertierung
4. STAC-Upload

### 2. Einzelbilder (Nadir/Oblique)

**Input:** Verzeichnis mit JPEG-Dateien

**Output:**
- Thumbnails: `thumbs/*.jpg` (640x480px)
- KML-Datei: `ram-YYYY-MM-DDt235959-ebn.kml`
- URL-Liste: `ram-YYYY-MM-DDt235959-ebn.txt`

**Workflow:**
1. EXIF-Extraktion (GPS + Zeitstempel)
2. Thumbnail-Erstellung
3. KML-Generierung mit Placemarks
4. STAC-Upload (KML + Photos)

## 🔧 Konfiguration

### Produktkonfiguration (`configuration.py`)

```python
# STAC-Einstellungen
STAC_COLLECTION = "ch.swisstopo.spezialbefliegungen"
STAC_HOSTNAME = "sys-data.int.bgdi.ch"  # INT
# STAC_HOSTNAME = "data.geo.admin.ch"   # PROD

# COG-Einstellungen
COG_CONFIG = {
    'compress': 'JPEG',
    'quality': 75,
    'blocksize': 256
}

# Thumbnail-Einstellungen
THUMBNAIL_CONFIG = {
    'max_width': 640,
    'max_height': 480
}
```

### Proxy-Konfiguration

Automatische Erkennung mit Fallback:
1. Direkte Verbindung testen
2. Bei Fehler: Swiss Federal Proxy verwenden (`proxy-bvcol.admin.ch:8080`)

## 📋 Namenskonventionen

### Dateinamen
```
ram-YYYY-MM-DDthhmmss-{product}-{type}.ext

Beispiele:
- ram-2024-07-15t143000-qdop-rgb-mosaic.tif
- ram-2024-07-15t143000-ebn.kml
```

### STAC Items
```
YYYY-MM-DDthhmmss (lowercase)

Beispiel: 2024-07-15t143000
```

## 🔐 Sicherheit

- **Credentials**: NIE in Git committen! 
- **secrets/**: Im `.gitignore` hinzufügen
- **Environment Variables**: Sicherer als Config-Files

```bash
# .gitignore
secrets/
temp/
*.pyc
__pycache__/
```

## 🐛 Troubleshooting

### GDAL nicht gefunden
```
✗ GDAL-Tools nicht verfügbar
```
**Lösung:** GDAL installieren und in PATH hinzufügen

### Keine Internet-Verbindung
```
✗ Keine Internet-Verbindung möglich
```
**Lösung:** Proxy-Einstellungen prüfen oder manuell in `proxy_handler.py` setzen

### Credentials fehlen
```
✗ Keine Credentials gefunden
```
**Lösung:** `secrets/stac_credentials.json` erstellen oder Environment Variables setzen

### GPS-Daten fehlen
```
⚠ Keine GPS-Daten gefunden
```
**Lösung:** Überprüfen ob EXIF-Tags in JPEGs vorhanden sind

## 📝 Logging

Das Script gibt detailliertes Feedback:

```
INFO: ✓ Erfolgreiche Operation
WARNING: ⚠ Warnung (nicht kritisch)
ERROR: ✗ Fehler (kritisch)
```

### Log-Level anpassen

In `rapidmapping_processor.py`:
```python
logging.basicConfig(level=logging.DEBUG)  # Mehr Details
logging.basicConfig(level=logging.INFO)   # Standard
logging.basicConfig(level=logging.WARNING) # Nur Warnungen
```

## 🔄 Workflow-Diagramm

```
Input Directory
    │
    ├─[Mosaike]─> get_tif_files() ─> create_cog_mosaic()
    │                                       │
    │                                       ├─ VRT
    │                                       ├─ Warp
    │                                       └─ COG
    │                                           │
    │                                           └─> publish_to_stac()
    │
    └─[Photos]──> get_jpg_files() ─> process_individual_photos()
                                            │
                                            ├─ Extract EXIF
                                            ├─ Create Thumbnails
                                            ├─ Generate KML
                                            └─ Generate URL-List
                                                │
                                                └─> publish_to_stac()
```

## 🤝 Integration mit bestehenden Scripts

Das System nutzt die bestehenden Module:
- `util_publish_stac_fsdi.py`: STAC-Publikation
- `main_multipart_upload_via_api.py`: Multipart-Upload

Diese Module werden **NICHT modifiziert** und müssen im gleichen Verzeichnis liegen.

## 📞 Support

Bei Problemen:
1. Log-Output prüfen
2. `temp/` Verzeichnis inspizieren (wird bei Fehler nicht gelöscht)
3. Issue im Repository erstellen

## 📄 Lizenz

Swisstopo Internal Use Only

## ✨ Features

- ✅ Automatische Proxy-Erkennung
- ✅ Flexible Credentials (File/Env)
- ✅ Interaktive CLI
- ✅ Detailliertes Logging
- ✅ Error Handling & Recovery
- ✅ Temp-Cleanup bei Erfolg
- ✅ Progress-Feedback
- ✅ Batch-Upload Support


## Projektstruktur

rapidmapping_processor/
├── rapidmapping_processor.py          # Hauptskript v2.0
├── configuration.py                    # Produktdefinitionen
├── requirements.txt                    # GDAL Python-Bindings!
├── README_v2.md                        # Diese Datei
├── utilities/
│   ├── __init__.py
│   ├── credentials.py                 # INT/PROD-Support
│   ├── proxy_handler.py               # JSON-Config
│   ├── file_handler.py
│   ├── gdal_utils.py                  # ⭐ NEU: GDAL-Bindings
│   ├── stac_query.py                  # ⭐ NEU: STAC-Abfragen
│   ├── mosaic_processor.py            # Mit GDAL-Bindings
│   ├── photo_processor.py             # Mit GDAL-Bindings
│   └── stac_publisher.py              # Environment-Support
├── secrets/
│   ├── stac_credentials.json          # INT + PROD
│   └── proxy_config.json              # Mehrere Proxies
├── temp/                               # Temporäre Dateien
└── util_publish_stac_fsdi.py          # Bestehend
    main_multipart_upload_via_api.py