# Betriebshandbuch: Rapid Mapping Processor

**Zielgruppe:** Büro-Kollegen | **System:** Windows | **Stand:** 2026

---

## Schnellübersicht (für Stresssituationen)

**Weg A — GUI (empfohlen):**

1. OSGeo4W Shell öffnen → `cd C:\legacySW\topo-rapidmapping`
2. `.venv\Scripts\activate`
3. `python 0_GUI_rapidmapping_STACimport.py`
4. Formular ausfüllen, **Verarbeitung starten** klicken, Zusammenfassung bestätigen
5. Warten bis Fortschrittsbalken fertig ist
6. **KML-Karte und Download-Liste: Links stehen am Ende der Log-Datei** (jetzt im Ordner `_logs\`)

**Weg B — nur .exe, kein Python nötig (Terminal-Dialog):**

1. OSGeo4W Shell öffnen → `cd C:\legacySW\topo-rapidmapping`
2. `rapidmapping_processor.exe` starten
3. 5 Fragen beantworten
4. Warten bis Programm fertig ist
5. Links am Ende der Log-Datei (`_logs\`)

---

## Teil 1: Einmalige Vorbereitung

Diese Schritte nur beim **ersten Mal** ausführen. Zwei Wege stehen zur Wahl —
je nachdem ob die grafische Oberfläche (GUI) genutzt werden soll.

### Weg A — GUI (empfohlen)

Braucht eine einmalig eingerichtete Python-Umgebung (dauert ca. 10 Minuten).

**1.A.1 Verzeichnis erstellen und Programm-Dateien besorgen**

```
C:\legacySW\topo-rapidmapping\
```

**OSGeo4W Shell öffnen** und der Reihe nach ausführen:

```
cd C:\legacySW
git clone https://github.com/swisstopo/topo-rapidmapping.git
cd topo-rapidmapping
```

> Falls `git` nicht verfügbar: Repository als ZIP von GitHub herunterladen und nach
> `C:\legacySW\topo-rapidmapping\` entpacken.

**1.A.2 Python Virtual Environment erstellen**

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

**1.A.3 Zugangsdaten einrichten**

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

**1.A.4 Ergebnis-Struktur nach der Vorbereitung**

```
C:\legacySW\topo-rapidmapping\
├── 0_GUI_rapidmapping_STACimport.py
├── rapidmapping_processor.py
├── .venv\
├── gui\
├── utilities\
└── secrets\
    └── stac_credentials.json
```

Ab jetzt genügt bei jedem weiteren Start: OSGeo4W Shell öffnen, `cd` ins
Verzeichnis, `.venv\Scripts\activate`, dann `python 0_GUI_rapidmapping_STACimport.py`
— siehe Teil 2.

---

### Weg B — nur die .exe (kein Python nötig)

Schneller eingerichtet, aber Terminal-Dialog statt grafischer Oberfläche
(siehe Teil 3).

**1.B.1 Verzeichnis erstellen**

```
C:\legacySW\topo-rapidmapping\
```

**1.B.2 EXE herunterladen**

1. Im Browser öffnen:
   https://github.com/swisstopo/topo-rapidmapping/blob/main/dist/rapidmapping_processor.exe
2. Rechts oben auf **Download** (Pfeil-Symbol) klicken
3. Datei speichern nach: `C:\legacySW\topo-rapidmapping\rapidmapping_processor.exe`

**1.B.3 Zugangsdaten einrichten**

Gleich wie in 1.A.3 beschrieben: Ordner `secrets\` mit `stac_credentials.json`.

**1.B.4 Ergebnis-Struktur nach der Vorbereitung**

```
C:\legacySW\topo-rapidmapping\
├── rapidmapping_processor.exe
└── secrets\
    └── stac_credentials.json
```

> **Tipp:** Wird die `.exe` zusätzlich in denselben Ordner wie Weg A gelegt,
> nutzt die GUI sie automatisch anstelle von `python rapidmapping_processor.py`
> — beide Wege lassen sich also kombinieren.

---

## Teil 2: GUI verwenden (empfohlen)

### 2.1 GUI starten

```
cd C:\legacySW\topo-rapidmapping
.venv\Scripts\activate
python 0_GUI_rapidmapping_STACimport.py
```

Es öffnet sich ein Fenster **"Rapid Mapping — STAC Import Tool"**.

### 2.2 Formular ausfüllen

| Feld | Beschreibung |
|------|--------------|
| **Umgebung** | `INT (Test)` oder `PROD (produktiv)`. Faustregel: im Zweifel zuerst INT testen, dann PROD. |
| **Input-Verzeichnis** | Über **Durchsuchen…** wählen oder Pfad eintippen. Rot umrandet, solange der Pfad nicht existiert. |
| **Produkttyp** | Dropdown: EBN, EBO, QDOP RGB, QDOP NRG, QDOP-DMC4. |
| **COG-Kompression / Qualität** | Erscheint nur bei Produkttyp **QDOP-DMC4** (einziger Workflow, der selbst einen COG erzeugt). COMPRESS-Verfahren wählbar (Standard JPEG); Qualität nur bei COMPRESS=JPEG editierbar (Standard 75). Output ist immer 8-Bit. |
| **Datum / Zeitstempel** | Beschriftung und erwartetes Format passen sich automatisch dem Produkttyp an (siehe Hinweistext direkt unter dem Feld). Rot umrandet bei ungültigem Format. |
| **STAC-Upload aktiv** | Ausschalten für einen Testlauf ohne Upload (Ergebnis landet lokal in `./output/`). |
| **Debug-Modus** | Sequentielle Verarbeitung mit ausführlicherem Log — nur bei Problemsuche aktivieren, sonst aus lassen (schneller). |
| **Netzwerk-Modus** | `auto` (Standard) reicht fast immer. Bei Problemen: `system` (Bundesnetz) oder einen benannten Proxy wählen. |

| Produkttyp | Was muss im Input-Verzeichnis liegen |
|------------|--------------------------|
| QDOP RGB / NRG | Genau **1 COG-TIF-Datei** (8-bit RGB) |
| QDOP-DMC4 | Ein oder mehrere **4-Band TIF-Streifen** |
| EBN / EBO | Mehrere **JPEG-Fotos** mit GPS im EXIF |

Unter dem Formular steht laufend eine Zusammenfassung der aktuellen Auswahl.

> **Der Button "▶ Verarbeitung starten" bleibt ausgegraut**, solange
> irgendein Feld ungültig ist (rot umrandet) oder — bei aktiviertem
> STAC-Upload — keine Zugangsdaten gefunden werden. Einfach das rot
> markierte Feld korrigieren, der Button aktiviert sich automatisch.

### 2.3 Starten und bestätigen

Klick auf **▶ Verarbeitung starten** öffnet eine Zusammenfassung
(Umgebung, Verzeichnis, Produkttyp, Zeitstempel, Upload an/aus) zur
Kontrolle — erst mit **Ja** wird die Verarbeitung wirklich gestartet.

### 2.4 Während der Verarbeitung

- Der Fortschritt erscheint live im Log-Fenster (inkl. Fortschrittsbalken
  bei grossen Uploads).
- **■ Abbrechen** bricht einen laufenden Import sauber ab (mit Rückfrage).
- Das Fenster bleibt bedienbar; beim Schliessen während eines laufenden
  Imports erscheint ebenfalls eine Rückfrage.

### 2.5 Nach dem Lauf

Erfolg oder Fehler werden farbig im Log markiert (grün = erfolgreich, rot =
Fehler). Die Links für den nächsten Schritt (Karte, Downloadliste) stehen
am Ende des Logs — siehe **Teil 4: Nach dem Lauf**.

---

## Teil 3: Alternative — Kommandozeile / .exe (Terminal-Dialog)

Kein Python nötig (siehe Weg B in Teil 1). Funktional identisch zur GUI,
nur ohne grafisches Formular — das Programm stellt die Fragen nacheinander
im Terminal.

### 3.1 OSGeo4W Shell öffnen

Im Windows-Startmenü suchen: **OSGeo4W Shell**
(kommt mit der QGIS-Installation)

Alternativ direkt starten: `C:\Program Files\QGIS 3.x.x\OSGeo4W.bat`

### 3.2 In das Arbeitsverzeichnis wechseln

```
cd C:\legacySW\topo-rapidmapping
```

### 3.3 Programm starten

```
rapidmapping_processor.exe
```

Das Programm startet und stellt nacheinander Fragen.

### 3.4 Die interaktiven Fragen (Schritt für Schritt)

Das Programm führt durch **5 Fragen**. Mit Enter bestätigen.

---

#### Frage 1 — Umgebung (INT oder PROD)

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

#### Frage 2 — Netzwerk / Proxy

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

#### Frage 3 — Input-Verzeichnis

```
Bitte Input-Verzeichnis angeben:
   Beispiel Windows: C:\oed\temp\rm\input
->
```

Pfad zum Ordner eingeben, der die Eingabedaten enthält (siehe Tabelle in
Teil 2.2, welcher Produkttyp welche Dateien erwartet).

---

#### Frage 4 — Produkttyp

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

#### Frage 5 — Datum / Zeitstempel

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

#### Bestätigung und Start

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

Gilt gleichermassen für GUI (Teil 2) und Kommandozeile/.exe (Teil 3).

### 4.1 Log-Datei

Das Programm erstellt automatisch eine Log-Datei im Ordner `_logs\`:

```
_logs\2025-09-03_ebn_20260720-134805.log
```

Namenskonvention: `<stac-datum>_<produkttyp>_<importDatum>.log`

- `<stac-datum>`: Datum/Zeitstempel der Aufnahme (Frage 5 bzw. Zeitstempel-Feld)
- `<produkttyp>`: `ebn`, `ebo`, `qdop-rgb`, `qdop-nrg` oder `qdop-dmc4`
- `<importDatum>`: Zeitpunkt des Programmlaufs (`JJJJMMTT-hhmmss`)

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

### 5.1 Einmalige Einrichtung

Bereits vorhanden, wenn **Weg A (GUI)** aus Teil 1 eingerichtet wurde — dann
direkt zu 5.2 springen. Sonst wie in **Teil 1, Weg A** beschrieben einrichten
(Repository, `.venv`, `pip install -r requirements.txt`, `secrets\`).

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

### "▶ Verarbeitung starten" bleibt ausgegraut (GUI)

Mindestens ein Feld ist ungültig — rot umrandete Felder prüfen (Input-Verzeichnis
existiert nicht, Zeitstempel-Format passt nicht zum Produkttyp) oder den
Hinweistext unter dem Netzwerk-Modus-Feld lesen (fehlende Zugangsdaten).

---

### Credentials fehlen

```
✗ Keine Credentials gefunden
```

Datei `secrets\stac_credentials.json` prüfen (siehe Teil 1.A.3 / 1.B.3).

---

### Keine Internet-Verbindung

```
✗ Keine Internet-Verbindung möglich
```

Netzwerk-Modus ändern: Option **Bundesnetz** (`system`) probieren.

---

### GPS-Daten fehlen (bei EBN/EBO)

```
Keine GPS-Daten gefunden
```

Kamera-Einstellungen prüfen: GPS muss beim Fotografieren aktiv gewesen sein.

---

### Bild ohne Zeitstempel — wird übersprungen (bei EBN/EBO)

```
✗ Kein Timestamp im Bild gefunden — NICHT in STAC importiert: dateiname.tif
```

Das ist gewollt: Bilder ohne auswertbaren Zeitstempel werden nicht mit einem
falschen (aktuellen) Datum importiert, sondern übersprungen und im Log
aufgelistet. Betroffene Dateien manuell prüfen.

---

### COG-Check fehlgeschlagen (bei QDOP)

```
✗ Datei ist KEIN Cloud Optimized GeoTIFF (COG)!
```

Datei muss zuerst konvertiert werden — Geodaten-Kollegen anfragen.
Anleitung: https://github.com/geostandards-ch/cog-best-practices

---

## Teil 7: Kommandozeile (für Fortgeschrittene)

Alle Eingaben können direkt als Parameter übergeben werden — kein Dialog,
weder im Terminal noch als GUI-Formular. Funktioniert mit `.exe` und mit
`rapidmapping_processor.py`. Vollständige Dokumentation und Beispiele auf GitHub:

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

## Teil 8: Für Entwickler — Tests

Nur relevant, wenn Code am Projekt geändert wird — für den normalen Betrieb
(GUI oder .exe) nicht nötig. `test_functions.py` prüft die reinen
Python-Funktionen (Namenskonventionen, Zeitstempel-Validierung, Dateisuche
usw.) automatisiert, ohne dass dafür ein echter STAC-Upload oder eine
GDAL-Installation nötig ist:

```
cd C:\legacySW\topo-rapidmapping
.venv\Scripts\activate
python test_functions.py
```

Alle Tests sollten mit `OK` durchlaufen. Vor dem Einspielen einer Code-Änderung
lohnt sich ein Durchlauf — insbesondere deckt ein Test ab, dass Bilder ohne
Timestamp weiterhin übersprungen und nicht mit dem aktuellen Datum versehen
werden (siehe Teil 6, "Bild ohne Zeitstempel").

---

## Anhang: Verzeichnis-Übersicht

```
C:\legacySW\topo-rapidmapping\
├── 0_GUI_rapidmapping_STACimport.py  <- GUI-Einstiegspunkt (Weg A)
├── rapidmapping_processor.exe        <- Terminal-Programm (Weg B)
├── rapidmapping_processor.py         <- Terminal-Programm, Python-Version
├── .venv\                            <- Python-Umgebung (nur Weg A/GUI)
├── gui\                              <- GUI-Module
├── test_functions.py                 <- Unit-Tests (nur für Entwickler, Teil 8)
├── secrets\
│   ├── stac_credentials.json         <- Zugangsdaten INT + PROD (Passwörter!)
│   └── proxy_config.json             <- Proxy-Konfiguration (optional)
├── utilities\
│   └── util_stac_delete_ram.py       <- Lösch-Script (nur Python)
└── _logs\
    └── 2025-09-03_ebn_20260720-134805.log   <- Automatisch erstellt nach jedem Lauf
```

---

*Bei Problemen: Log-Datei an die zuständige Person weitergeben.*
*Technische Dokumentation: https://github.com/swisstopo/topo-rapidmapping*
