# Betriebshandbuch: Rapid Mapping Processor

**Zielgruppe:** Büro-Kollegen | **System:** Windows | **Stand:** 2026

---

## Schnellübersicht (für Stresssituationen)

1. OSGeo4W Shell öffnen → `cd C:\legacySW\topo-rapidmapping`
2. `rapidmapping_processor.exe` starten
3. 5 Fragen beantworten
4. Warten bis Programm fertig ist
5. **KML-Karte und Download-Liste: Links stehen am Ende der Log-Datei**

---

## Teil 1: Einmalige Vorbereitung

Diese Schritte nur beim **ersten Mal** ausführen.

### 1.1 Verzeichnis erstellen

Im Windows-Explorer folgenden Ordner erstellen:

```
C:\legacySW\topo-rapidmapping\
```

### 1.2 EXE herunterladen

1. Im Browser öffnen:
   https://github.com/swisstopo/topo-rapidmapping/blob/main/dist/rapidmapping_processor.exe
2. Rechts oben auf **Download** (Pfeil-Symbol) klicken
3. Datei speichern nach: `C:\legacySW\topo-rapidmapping\rapidmapping_processor.exe`

### 1.3 Zugangsdaten einrichten

Ordner erstellen: `C:\legacySW\topo-rapidmapping\secrets\`

Darin Datei `stac_credentials.json` anlegen (echte Daten von IT oder Teamleitung erfragen):

```json
{
    "INT": {
        "username": "dein-int-benutzername",
        "password": "dein-int-passwort",
        "hostname": "sys-data.int.bgdi.ch"
    },
    "PROD": {
        "username": "dein-prod-benutzername",
        "password": "dein-prod-passwort",
        "hostname": "data.geo.admin.ch"
    }
}
```

> **Wichtig:** Diese Datei enthält Passwörter — nie per E-Mail versenden.

### 1.4 Ergebnis-Struktur nach der Vorbereitung

```
C:\legacySW\topo-rapidmapping\
├── rapidmapping_processor.exe
└── secrets\
    └── stac_credentials.json
```

---

## Teil 2: Programm starten

### 2.1 OSGeo4W Shell öffnen

Im Windows-Startmenü suchen: **OSGeo4W Shell**
(kommt mit der QGIS-Installation)

Alternativ direkt starten: `C:\Program Files\QGIS 3.x.x\OSGeo4W.bat`

### 2.2 In das Arbeitsverzeichnis wechseln

```
cd C:\legacySW\topo-rapidmapping
```

### 2.3 Programm starten

```
rapidmapping_processor.exe
```

Das Programm startet und stellt nacheinander Fragen.

---

## Teil 3: Die interaktiven Fragen (Schritt für Schritt)

Das Programm führt durch **5 Fragen**. Mit Enter bestätigen.

---

### Frage 1 — Umgebung (INT oder PROD)

```
Bitte Umgebung auswählen:
   1) INT  - Integrationsumgebung (default)
   2) PROD - Produktionsumgebung
->
```

| Eingabe | Bedeutung |
|---------|-----------|
| `1` oder Enter | **INT** — zum Testen, nicht öffentlich |
| `2` | **PROD** — echte Publikation, öffentlich sichtbar |

> Faustregel: Im Zweifel zuerst mit INT testen, dann PROD.

---

### Frage 2 — Netzwerk / Proxy

```
Netzwerk / Proxy:
  1) Autodetect  (direkt -> System-Proxy -> proxy_config.json)
  2) Kein Proxy  (direkte Verbindung)
  3) Bundesnetz  (System-Proxy)
  4) BVCOL       (...)
->
```

| Situation | Wählen |
|-----------|--------|
| Normal, im Büro | `1` Autodetect |
| VPN aktiv | `1` Autodetect erkennt VPN automatisch |
| Bundesnetz / Proxy zwingend | `3` |
| Spezifischer Proxy | Nummer des Proxy-Namens |

> Bei Unsicherheit immer `1` wählen.

---

### Frage 3 — Input-Verzeichnis

```
Bitte Input-Verzeichnis angeben:
   Beispiel Windows: C:\oed\temp\rm\input
->
```

Pfad zum Ordner eingeben, der die Eingabedaten enthält:

| Produkttyp | Was muss im Ordner liegen |
|------------|--------------------------|
| QDOP RGB / NRG | Genau **1 COG-TIF-Datei** (8-bit RGB) |
| QDOP-DMC4 | Ein oder mehrere **4-Band TIF-Streifen** |
| EBN / EBO | Mehrere **JPEG-Fotos** mit GPS im EXIF |

---

### Frage 4 — Produkttyp

```
Bitte Produkttyp auswählen:
   1) QDOP RGB Mosaic (Orthophoto RGB)
   2) QDOP NRG Mosaic (Orthophoto Nahinfrarot)
   3) EBN - Einzelbilder Nadir (Senkrecht)
   4) EBO - Einzelbilder Oblique (Schrägaufnahmen)
   5) QDOP-DMC4 (4-Kanal DMC4-Streifen -> RGB + NRG)
->
```

| Nr. | Produkt | Beschreibung |
|-----|---------|--------------|
| 1 | QDOP RGB | Orthophoto Farbe |
| 2 | QDOP NRG | Orthophoto Nahinfrarot |
| 3 | EBN | Einzelbilder senkrecht (Nadir) |
| 4 | EBO | Einzelbilder schräg (Oblique) |
| 5 | QDOP-DMC4 | DMC4-Streifen, erstellt automatisch RGB + NRG |

---

### Frage 5 — Datum / Zeitstempel

**Bei EBN und EBO** (nur Datum):

```
Bitte Aufnahmedatum angeben:
   Format: YYYY-MM-DD  Beispiel: 2024-07-15
->
```

**Bei QDOP und DMC4** (Datum + Uhrzeit):

```
Bitte Aufnahmezeitpunkt angeben:
   Format: YYYY-MM-DDthhmmss  Beispiel: 2024-07-15t143000
->
```

---

### Bestätigung und Start

Das Programm zeigt eine Zusammenfassung aller Eingaben:

```
======================================================================
ZUSAMMENFASSUNG
======================================================================
  Environment:    INT
  Input-Verz.:    C:\oed\temp\rm\input
  Produkttyp:     ebn
  Zeitstempel:    2024-07-15
  STAC Upload:    Aktiviert
======================================================================
Weiter? [j/Enter = ja, n = nein]:
```

Mit **Enter** oder **j** bestätigen — Verarbeitung startet.

---

## Teil 4: Nach dem Lauf

### 4.1 Log-Datei

Das Programm erstellt automatisch eine Log-Datei:

```
Log_ebn_20260608_134805.txt
```

Format: `Log_PRODUKTTYP_DATUM_UHRZEIT.txt`

Die Log-Datei enthält den vollständigen Ablauf inklusive aller Fehlermeldungen.

### 4.2 Links im Log — das Wichtigste

Am Ende der Log-Datei stehen die fertigen Links für den nächsten Schritt:

**Für EBN / EBO (Einzelbilder):**

```
======================================================================
✅ Nächster Schritt: Einzelbilder Nadir
  Karte:  https://map.geo.admin.ch/#/map?layers=KML|https://sys-data.int.bgdi.ch/.../ram-...-ebn.kml
  Liste:  https://sys-data.int.bgdi.ch/.../ram-...-ebn.txt
======================================================================
```

**Für QDOP / DMC4 (Mosaike):**

```
======================================================================
✅ Nächster Schritt: Quick Digital Orthophoto RGB
  URL: https://map.geo.admin.ch/#/map?layers=COG|https://sys-data.int.bgdi.ch/.../ram-...-mosaic.tif
======================================================================
```

> Den **Karte-Link** im Browser öffnen: Aufnahmen sind sofort auf map.geo.admin.ch sichtbar.
> Diese Links direkt für die Integration auf rapidmapping.ch verwenden.

---

## Teil 5: Daten löschen

Wenn Daten irrtümlich publiziert wurden oder ein Test-Upload entfernt werden soll.

> **Achtung:** Gelöschte Daten können nicht wiederhergestellt werden.

Das Lösch-Script läuft **nicht** als EXE — es braucht eine vollständige Python-Umgebung.
Diese Einrichtung ist einmalig nötig.

### 5.1 Einmalige Einrichtung (nur beim ersten Mal)

**OSGeo4W Shell öffnen** und folgende Schritte der Reihe nach ausführen:

**Repository herunterladen (git clone):**

```
cd C:\legacySW
git clone https://github.com/swisstopo/topo-rapidmapping.git
cd topo-rapidmapping
```

> Falls `git` nicht verfügbar: Repository als ZIP von GitHub herunterladen und nach
> `C:\legacySW\topo-rapidmapping\` entpacken.

**Python Virtual Environment erstellen:**

```
"C:\Program Files\QGIS 3.x.x\apps\Python312\python.exe" -m venv .venv --system-site-packages
```

> Versionsnummer (`3.x.x`) anpassen — im Windows-Explorer unter
> `C:\Program Files\` nachschauen welche QGIS-Version installiert ist.

**Virtual Environment aktivieren:**

```
.venv\Scripts\activate
```

Nach der Aktivierung erscheint `(.venv)` am Anfang der Zeile.

**Abhängigkeiten installieren:**

```
pip install -r requirements.txt
```

**Zugangsdaten bereitstellen:**

Ordner `secrets\` und Datei `stac_credentials.json` einrichten — gleich wie in Teil 1.3 beschrieben.

---

### 5.2 Lösch-Script starten

Bei jedem Aufruf: OSGeo4W Shell öffnen, ins Verzeichnis wechseln, venv aktivieren:

```
cd C:\legacySW\topo-rapidmapping
.venv\Scripts\activate
python utilities/util_stac_delete_ram.py
```

### 5.3 Interaktive Schritte

**Schritt 1 — Umgebung wählen:**

```
Select environment:
  1) INT (sys-data.int.bgdi.ch)
  2) PROD (data.geo.admin.ch)

Enter choice (1 or 2):
```

`1` für INT, `2` für PROD eingeben.

---

**Schritt 2 — Lösch-Modus wählen:**

```
Select what to delete:
  1) All RAM items (spezialbefliegungen_ram-*)
  2) RAM items from specific date (e.g., 2024-07-15)

Enter choice (1 or 2):
```

| Wahl | Wann verwenden |
|------|---------------|
| `1` | Alle RAM-Items löschen (Vorsicht!) |
| `2` | Nur Items eines bestimmten Tages löschen (empfohlen) |

Bei Wahl `2` das Datum eingeben:

```
Enter date (YYYY-MM-DD, e.g., 2024-07-15): 2024-07-15
```

---

**Schritt 3 — Liste prüfen:**

Das Programm zeigt alle Items, die gelöscht werden:

```
ITEMS TO BE DELETED
======================================================================
  1. ram-2024-07-15t12052300-ebn
  2. ram-2024-07-15t13102100-ebn
  3. ram-2024-07-15t23595900

Total items to delete: 3
```

Liste sorgfältig prüfen, bevor weiter.

---

**Schritt 4 — Doppelte Bestätigung:**

Erste Bestätigung:

```
Type "yes" to continue:
```

`yes` eintippen (genau so, keine Abkürzung).

Zweite Bestätigung:

```
Type "I agree" to proceed with deletion:
```

`I agree` eintippen (genau so).

---

**Schritt 5 — Löschung läuft:**

Das Programm löscht zuerst alle Assets, dann das Item. Am Ende erscheint eine Zusammenfassung:

```
DELETION SUMMARY
======================================================================
✓ Successfully deleted assets: 6
✗ Failed asset deletions:      0
✓ Successfully deleted items:  3
✗ Failed item deletions:       0
```

Wenn Fehler auftreten: Log-Ausgabe an die zuständige Person weitergeben.

---

## Teil 6: Häufige Probleme

### Credentials fehlen

```
✗ Keine Credentials gefunden
```

Datei `secrets\stac_credentials.json` prüfen (siehe Teil 1.3).

---

### Keine Internet-Verbindung

```
✗ Keine Internet-Verbindung möglich
```

Proxy-Wahl ändern: Option `3` (Bundesnetz) probieren.

---

### GPS-Daten fehlen (bei EBN/EBO)

```
Keine GPS-Daten gefunden
```

Kamera-Einstellungen prüfen: GPS muss beim Fotografieren aktiv gewesen sein.

---

### COG-Check fehlgeschlagen (bei QDOP)

```
✗ Datei ist KEIN Cloud Optimized GeoTIFF (COG)!
```

Datei muss zuerst konvertiert werden — Geodaten-Kollegen anfragen.
Anleitung: https://github.com/geostandards-ch/cog-best-practices

---

## Teil 7: Kommandozeile (für Fortgeschrittene)

Alle Eingaben können direkt als Parameter übergeben werden — kein Dialog.
Vollständige Dokumentation und Beispiele auf GitHub:

**https://github.com/swisstopo/topo-rapidmapping**

Häufige Beispiele:

```bash
# INT starten (Standard, mit Dialog)
rapidmapping_processor.exe

# PROD direkt starten (kein Umgebungs-Dialog)
rapidmapping_processor.exe --prod

# EBN vollständig ohne Dialog
rapidmapping_processor.exe --product ebn --input C:\daten\rm --timestamp 2025-09-03

# EBO auf PROD
rapidmapping_processor.exe --prod --product ebo --input C:\daten\rm --timestamp 2025-09-03

# Lokale Verarbeitung ohne Upload (Test)
rapidmapping_processor.exe --upload=False
```

---

## Anhang: Verzeichnis-Übersicht

```
C:\legacySW\topo-rapidmapping\
├── rapidmapping_processor.exe        <- Das Programm
├── secrets\
│   ├── stac_credentials.json         <- Zugangsdaten INT + PROD (Passwörter!)
│   └── proxy_config.json             <- Proxy-Konfiguration (optional)
├── utilities\
│   └── util_stac_delete_ram.py       <- Lösch-Script (nur Python)
└── Log_ebn_20260608_134805.txt       <- Automatisch erstellt nach jedem Lauf
```

---

*Bei Problemen: Log-Datei an die zuständige Person weitergeben.*
*Technische Dokumentation: https://github.com/swisstopo/topo-rapidmapping*
