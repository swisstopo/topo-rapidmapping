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

Das Programm beginnt mit einer **Startfrage** (Frage 0) und führt dann durch **5 Fragen**. Mit Enter bestätigen.

---

### Frage 0 — Was möchten Sie tun?

```
Was möchten Sie tun?
   1) Daten verarbeiten und publizieren  (Standard)
   2) Erweitert: STAC-Daten LÖSCHEN
->
```

| Eingabe | Bedeutung |
|---------|-----------|
| `1` oder Enter | Normale Verarbeitung, weiter mit Frage 1 |
| `2` | Daten wieder entfernen, siehe [Teil 5](#teil-5-daten-löschen) |

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
| QDOP-DMC4 | Ein oder mehrere **4-Band TIF-Streifen** (Dateinamen wie `0312_1234_052_41216_RGBN.tif`, daraus wird der Zeitstempel gelesen) |
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

**Bei QDOP RGB / NRG** (Datum + Uhrzeit):

```
Bitte Aufnahmezeitpunkt angeben:
   Format: YYYY-MM-DDthhmmss  Beispiel: 2024-07-15t143000
->
```

**Bei DMC4** schlägt das Programm den Zeitstempel selbst vor. Er wird aus den Dateinamen der Streifen gelesen
(`MMDD_hhmm_Linie_..._RGBN.tif`, z.B. `0312_1234_052_41216_RGBN.tif` = 12. März, 12:34 Uhr). Das **Jahr** kommt aus der
Systemzeit des Computers (liegt das Datum damit in der Zukunft, z.B. Flug im Dezember und Verarbeitung im Januar, wird das Vorjahr genommen):

```
Bitte Aufnahmezeitpunkt bestätigen:
   Vorschlag (aus Dateiname '0312_1234_052_41216_RGBN.tif' (frühester Streifen), Jahr 2026 aus Systemzeit)
   -> 2026-03-12t12340000
   Enter = Vorschlag übernehmen, oder eigenen Wert eingeben (YYYY-MM-DDthhmmss)
->
```

| Eingabe | Bedeutung |
|---------|-----------|
| Enter | Vorschlag übernehmen |
| `2025-03-12t123400` | eigenen Wert verwenden (z.B. anderes Jahr) |

> **Prüfen:** Stimmt das Jahr? Danach zeigt das Programm an, ob für denselben Tag schon Items auf STAC existieren
> (Warnung mit Liste). Dann prüfen, ob es sich um ein Duplikat handelt, bevor die Verarbeitung gestartet wird.
>
> Passt kein Dateiname, macht das Programm **keinen** Vorschlag und fragt nach dem vollständigen Zeitstempel.

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
> Freigabe: Die Leitung RM ordnet an, der Bereitschaftsdienst führt aus.

Das Löschen ist eine **erweiterte Option des normalen Programms** und läuft in der EXE.
Es braucht keine Python-Umgebung mehr.

### 5.1 Drei Varianten

| Nr. | Variante | Eingabe (Beispiel) | Wirkung |
|-----|----------|--------------------|---------|
| 1 | **EIN Asset** | `ram-2017-08-25t10092400-ebn-photo.jpg` | Nur dieses Asset, das Item bleibt bestehen |
| 2 | **EIN Item** (inkl. aller Assets) | `2017-08-25t10092400` | Das ganze Item mit allen Assets |
| 3 | **ALLE Items eines Datums** | `2024-07-15` | Alle RAM-Items dieses Tages (auch KML-/Listen-Item) |

### 5.2 Im Dialog

```
cd C:\legacySW	opo-rapidmapping
rapidmapping_processor.exe
```

1. **Frage 0:** `2` eingeben (Erweitert: STAC-Daten LÖSCHEN)
2. **Umgebung:** `1` INT (Standard) oder `2` PROD
3. **Netzwerk:** wie beim normalen Lauf, im Zweifel `1` Autodetect
4. **Variante** `1`, `2` oder `3` wählen und das Ziel eingeben (Enter = abbrechen)
5. **Liste prüfen:** Das Programm zeigt, was gelöscht wird (Umgebung, Items, Assets)
6. **Erste Bestätigung:** `yes` eintippen (genau so)
7. **Zweite Bestätigung:** `I agree` eintippen (genau so)

Alles andere als `yes` bzw. `I agree` bricht ab, es wird nichts gelöscht.

### 5.3 Per Kommandozeile

```
rapidmapping_processor.exe --delete asset --target ram-2017-08-25t10092400-ebn-photo.jpg
rapidmapping_processor.exe --delete item  --target 2017-08-25t10092400
rapidmapping_processor.exe --delete date  --target 2024-07-15
rapidmapping_processor.exe --delete date  --target 2024-07-15 --prod
```

- Ohne `--prod` wird in **INT** gelöscht, mit `--prod` in **PROD**.
- Die Liste und die beiden Bestätigungen (`yes`, `I agree`) kommen auch hier.

### 5.4 Ergebnis

Das Programm löscht zuerst die Assets, dann das Item. Am Ende steht `SUCCESS` oder, bei Fehlern, eine Liste der nicht
gelöschten Assets/Items mit `ERROR`. Alles steht in der Log-Datei unter `logs\<ziel>_delete-<variante>_<zeit>.log`.

Wird mit Variante 1 das letzte Asset eines Items gelöscht, bleibt ein leeres Item bestehen (Hinweis im Log).
Zum Entfernen Variante 2 verwenden.

Wenn Fehler auftreten: Log-Datei an die zuständige Person weitergeben.

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

# DMC4 ohne Zeitstempel (Uhrzeit aus den Dateinamen, Jahr aus Systemzeit)
rapidmapping_processor.exe --product qdop-dmc4 --input C:\daten\dmc4

# DMC4 mit Datum (z.B. anderes Jahr), Uhrzeit aus den Dateinamen
rapidmapping_processor.exe --product qdop-dmc4 --input C:\daten\dmc4 --timestamp 2026-03-12

# Daten löschen (immer mit Liste + "yes" + "I agree")
rapidmapping_processor.exe --delete item --target 2017-08-25t10092400
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
