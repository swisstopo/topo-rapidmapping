#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rapid Mapping Processor - Hauptskript v2.0 (subprocess version)
Version: 2.0

CHANGES v2.2:
- All item/asset names always have 2-digit ms-suffix ("00" if no burst)
- Mosaic workflow: appends "00" to timestamp
- KML/CSV overview item: timestamp t23595900

Usage:
    python rapidmapping_processor.py
    python rapidmapping_processor.py --upload=False
    python rapidmapping_processor.py --prod
"""

import argparse
import logging
import re
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime

from configuration import (
    ProductType,
    get_product_config,
    validate_timestamp,
    normalize_cli_timestamp,
    generate_item_name,
    generate_asset_name,
    get_collection_url,
    COG_CONFIG,
    STAC_COLLECTION,
    GEOCAT_ID,
    STAC_SCHEME,
    STAC_API_PATH
)
from utilities.file_handler import (
    validate_directory,
    cleanup_temp_directory
)
from utilities.mosaic_processor import process_single_cog_file
from utilities.photo_processor import process_individual_photos, generate_csv_from_stac
from utilities.kml_generator import create_overview_kml
from utilities.stac_publisher import publish_to_stac_wrapper
from utilities.proxy_handler import initialize_proxy, get_configured_proxy_names
from utilities.credentials import load_stac_credentials
from utilities.gdal_helpers import GDAL_PERF_FLAGS, supports_progress
# publish_to_stac importiert lazy (verhindert circular import)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def print_banner():
    print("=" * 70)
    print(" " * 12 + "SWISSTOPO RAPID MAPPING PROCESSOR v2.0")
    print(" " * 18 + "(POC - not for operational use)")
    print("=" * 70)
    print()


def prompt_proxy_mode() -> tuple:
    """
    Interaktive Auswahl des Netzwerk-/Proxy-Modus.
    Gibt (mode, proxy_name) zurück:
      ('auto',   None)         — Autodetect (Standard)
      ('direct', None)         — Kein Proxy, direkte Verbindung
      ('system', None)         — Bundesnetz (System-Proxy)
      ('named',  '<Name>')     — definierter Proxy aus proxy_config.json
    """
    named_proxies = get_configured_proxy_names()

    print("\nNetzwerk / Proxy:")
    print("  1) Autodetect  (direkt -> System-Proxy -> proxy_config.json)")
    print("  2) Kein Proxy  (direkte Verbindung, kein Proxy)")
    print("  3) Bundesnetz  (System-Proxy aus Windows-Einstellungen)")
    for i, name in enumerate(named_proxies, 4):
        print(f" {i}) {name}")
    print(" [Standard: 1]")

    choices_map = {'1': ('auto', None), '2': ('direct', None), '3': ('system', None)}
    for i, name in enumerate(named_proxies, 4):
        choices_map[str(i)] = ('named', name)

    while True:
        raw = input("-> ").strip()
        if raw == '':
            raw = '1'
        if raw in choices_map:
            mode, proxy_name = choices_map[raw]
            label = {
                'auto':   'Autodetect',
                'direct': 'Kein Proxy (direkte Verbindung)',
                'system': 'Bundesnetz (System-Proxy)',
                'named':  f"Proxy '{proxy_name}'",
            }[mode]
            logger.info(f"✓ Netzwerk-Modus: {label}")
            return mode, proxy_name
        print(f" Ungültige Eingabe. Bitte 1–{len(choices_map)} eingeben.")


def prompt_environment() -> str:
    print("\n Bitte Umgebung auswählen:")
    print("   1) INT  - Integrationsumgebung (default)")
    print("   2) PROD - Produktionsumgebung")
    while True:
        choice = input("-> ").strip()
        if choice in ("", "1"):
            logger.info("✓ Umgebung: INT")
            return "INT"
        elif choice == "2":
            logger.info("✓ Umgebung: PROD")
            return "PROD"
        else:
            logger.error("✗ Ungültige Auswahl. Bitte 1 oder 2 eingeben (oder Enter für INT).")


def prompt_secrets_dir_if_missing() -> None:
    """
    Rettungsanker für den Klassiker: App laeuft nicht im selben Verzeichnis wie
    der 'secrets'-Ordner (Credentials/Proxy-Config), typischerweise weil das
    Arbeitsverzeichnis beim Start ein anderes ist als erwartet.

    Fragt interaktiv nach dem korrekten Pfad und wechselt dorthin (chdir), damit
    alle relativen 'secrets/...'-Zugriffe im restlichen Code (credentials.py,
    proxy_handler.py) wieder funktionieren - ohne dass an mehreren Stellen im
    Code der Pfad durchgereicht werden muss.
    """
    if Path("secrets").is_dir():
        return
    if os.environ.get('STAC_USERNAME') and os.environ.get('STAC_PASSWORD'):
        return  # Credentials kommen aus Env-Vars, 'secrets/' wird nicht zwingend gebraucht

    # logger statt print(): dessen StreamHandler faengt UnicodeEncodeError (z.B. bei
    # Emoji auf einer Windows-Konsole mit cp1252-Codepage) intern ab statt abzustuerzen
    # - print() hat diese Absicherung nicht. Der input()-Prompt selbst bleibt daher
    # bewusst reines ASCII.
    logger.info("=" * 70)
    logger.info("  \U0001F913 Hallo Simon! \U0001F44B")
    logger.info("=" * 70)
    logger.info(" Ich kann den 'secrets'-Ordner (Credentials + Proxy-Config) im")
    logger.info(" aktuellen Arbeitsverzeichnis nicht finden. Vermutlich laeuft die")
    logger.info(" App mal wieder nicht im selben Verzeichnis wie 'secrets/' ;-)")
    logger.info(" Kein Grund zur Panik - gib einfach kurz")
    logger.info(" den Pfad zum 'secrets'-Ordner, dann cd ich uns gemeinsam dahin:")
    logger.info("   Beispiel Windows: C:\\oed\\temp\\rm\\secrets")
    logger.info("   Beispiel Linux:   /home/simon/rm/secrets")

    while True:
        raw = input(" -> Pfad zum secrets-Ordner (Enter = abbrechen): ").strip().strip('"')
        if not raw:
            logger.warning("! Kein Pfad angegeben - bis zum naechsten Mal, Simon.")
            return

        candidate = Path(raw).expanduser()
        if candidate.name.lower() != "secrets" and (candidate / "secrets").is_dir():
            candidate = candidate / "secrets"  # übergeordneten Ordner angegeben

        if candidate.is_dir():
            os.chdir(candidate.parent)
            logger.info(f"✓ Nice catch! Arbeitsverzeichnis gewechselt nach: {candidate.parent.resolve()}")
            return

        logger.error(f"✗ '{candidate}' existiert nicht oder ist kein Verzeichnis. Nochmal?")


def prompt_input_directory():
    while True:
        print("\n Bitte Input-Verzeichnis angeben:")
        print("   Beispiel Windows: C:\\oed\\temp\\rm\\input")
        print("   Beispiel Linux:   /home/user/rm/input")
        input_dir = input("-> ").strip()
        try:
            validated_path = validate_directory(input_dir)
            logger.info(f"✓ Input-Verzeichnis validiert: {validated_path}")
            return validated_path
        except (ValueError, FileNotFoundError) as e:
            logger.error(f"✗ {str(e)}")
            continue


def prompt_product_type():
    print("\n Bitte Produkttyp auswählen:")
    print("   1) QDOP RGB Mosaic (Orthophoto RGB)")
    print("   2) QDOP NRG Mosaic (Orthophoto Nahinfrarot)")
    print("   3) EBN - Einzelbilder Nadir (Senkrecht)")
    print("   4) EBO - Einzelbilder Oblique (Schrägaufnahmen)")
    print("   5) QDOP-DMC4 (4-Kanal DMC4-Streifen → RGB + NRG)")
    choices = {
        '1': ProductType.QDOP_RGB,
        '2': ProductType.QDOP_NRG,
        '3': ProductType.EBN,
        '4': ProductType.EBO,
        '5': ProductType.QDOP_DMC4,
    }
    while True:
        choice = input("-> ").strip()
        if choice in choices:
            product = choices[choice]
            logger.info(f"✓ Produkttyp gewählt: {product.value}")
            return product
        else:
            logger.error("✗ Ungültige Auswahl. Bitte 1-5 eingeben.")


def prompt_timestamp(product_type):
    if product_type in [ProductType.EBN, ProductType.EBO]:
        print("\n Bitte Aufnahmedatum angeben:")
        print("   Format: YYYY-MM-DD  Beispiel: 2024-07-15")
        while True:
            date_input = input("-> ").strip()
            try:
                datetime.strptime(date_input, '%Y-%m-%d')
                logger.info(f"✓ Datum validiert: {date_input}")
                return date_input
            except ValueError:
                logger.error("✗ Ungültiges Format. Bitte YYYY-MM-DD verwenden.")
    else:
        print("\n Bitte Aufnahmezeitpunkt angeben:")
        print("   Format: YYYY-MM-DDthhmmss  Beispiel: 2024-07-15t143000")
        while True:
            timestamp = input("-> ").strip().lower()
            if validate_timestamp(timestamp):
                logger.info(f"✓ Zeitstempel validiert: {timestamp}")
                return timestamp
            else:
                logger.error("✗ Ungültiges Format. Bitte YYYY-MM-DDthhmmss verwenden.")


def _ensure_ms_suffix(timestamp: str) -> str:
    """
    Stellt sicher dass ein Timestamp ein 2-stelliges ms-Suffix hat.
    "2024-07-15t143000"   ->  "2024-07-15t14300000"
    "2024-07-15t14300000" ->  "2024-07-15t14300000"  (unveraendert)
    """
    if re.match(r'^\d{4}-\d{2}-\d{2}t\d{6}$', timestamp):
        return timestamp + "00"
    return timestamp


def _poll_progress(output_path: "Path", ref_size_bytes: int, stop_event, interval: float = 0.5):
    """
    Background thread: polls output_path size and prints a live progress bar.
    Runs until stop_event is set.

    Uses the input file size as a rough 100% reference (output will differ
    due to compression, but it gives a useful visual indicator).
    """
    import time
    import os

    bar_width = 30
    while not stop_event.is_set():
        try:
            written = os.path.getsize(output_path) if output_path.exists() else 0
        except OSError:
            written = 0

        if ref_size_bytes > 0:
            pct = min(written / ref_size_bytes * 100, 99)  # cap at 99 until done
        else:
            pct = 0

        filled  = int(bar_width * pct / 100)
        bar     = "█" * filled + "░" * (bar_width - filled)
        written_mb = written / 1_048_576
        print(f"\r    [{bar}] {pct:5.1f}%  {written_mb:.1f} MB written", end="", flush=True)
        time.sleep(interval)

    # Final 100% line
    bar = "█" * bar_width
    try:
        done_mb = os.path.getsize(output_path) / 1_048_576 if output_path.exists() else 0
    except OSError:
        done_mb = 0
    print(f"\r    [{bar}] 100.0%  {done_mb:.1f} MB written", flush=True)


def _run_gdal(label: str, cmd: list, output_path: "Path | None" = None) -> bool:
    """
    Run a GDAL subprocess with live progress feedback.

    If the GDAL build supports -progress: appended to the command and GDAL
    prints  0...10...20...30...40...50...60...70...80...90...100 - done.
    natively (stdout inherited).

    Fallback (older GDAL / QGIS-bundled builds): a background thread polls
    the output file size and renders a growing progress bar.

    In both cases stderr is captured for error logging.
    """
    import subprocess as _sp
    import threading
    import os

    logger.info(f"  → {label}")

    # Inject performance flags right after the executable name
    cmd = [cmd[0]] + GDAL_PERF_FLAGS + cmd[1:]

    if supports_progress(cmd[0]):
        full_cmd = cmd + ["-progress"]
        result = _sp.run(full_cmd, stderr=_sp.PIPE, text=True)
    else:
        # Determine reference size from the input file (last positional arg
        # before the output, i.e. second-to-last element of cmd).
        ref_path = Path(cmd[-2]) if len(cmd) >= 2 else None
        ref_size = 0
        if ref_path and ref_path.exists():
            try:
                ref_size = os.path.getsize(ref_path)
            except OSError:
                pass

        watch_path = output_path or (Path(cmd[-1]) if cmd else None)
        stop_evt   = threading.Event()

        if watch_path and ref_size > 0:
            t = threading.Thread(
                target=_poll_progress,
                args=(watch_path, ref_size, stop_evt),
                daemon=True
            )
            t.start()
        else:
            t = None
            print("    (Fortschritt nicht verfügbar für diesen GDAL-Build)")

        result = _sp.run(cmd, stderr=_sp.PIPE, text=True)

        stop_evt.set()
        if t is not None:
            t.join()

    if result.returncode != 0:
        logger.error(f"    ✗ fehlgeschlagen (exit {result.returncode})")
        if result.stderr.strip():
            logger.error(result.stderr.strip())
        return False
    return True


def process_mosaic_workflow(
    input_dir, product_type, timestamp, upload_enabled, environment, hostname,
    debug: bool = False,
):
    """Workflow fuer Orthophoto-Mosaike.

    B) QDOP-Item hat jetzt keine Produktsuffix mehr: ram-YYYY-MM-DDthhmmsscc
       Beide Varianten (RGB + NRG) landen als Assets im selben Item.
    """
    try:
        output_dir = Path("output") if not upload_enabled else Path("temp")
        output_dir.mkdir(exist_ok=True)
        temp_dir = output_dir

        config = get_product_config(product_type)

        logger.info("=" * 70)
        logger.info("ORTHOPHOTO SINGLE COG-FILE PROCESSING")
        logger.info("=" * 70)

        # NEU v2.2: ms-Suffix sicherstellen
        timestamp_ms = _ensure_ms_suffix(timestamp)
        if timestamp_ms != timestamp:
            logger.info(f"  ms-Suffix ergaenzt: {timestamp} -> {timestamp_ms}")

        item_name      = generate_item_name(timestamp_ms, product_type)
        asset_name_base = generate_asset_name(timestamp_ms, product_type)

        logger.info(f"STAC Item:  {item_name}")
        logger.info(f"STAC Asset: {asset_name_base}")

        output_file = process_single_cog_file(
            input_dir=input_dir,
            output_dir=temp_dir,
            filename=Path(asset_name_base).stem
        )

        if not output_file:
            logger.error("✗ COG-File-Processing fehlgeschlagen")
            return False

        thumbnail_file = temp_dir / "thumbnail.jpg"

        if upload_enabled:
            upload_temp_dir = temp_dir
            temp_cog_path   = upload_temp_dir / asset_name_base

            logger.info(f"\n-> Upload COG-Tiff als: {asset_name_base}")
            cog_success = publish_to_stac_wrapper(
                asset_path=temp_cog_path,
                item_name=item_name,
                collection=STAC_COLLECTION,
                geocat_id=GEOCAT_ID,
                hostname=hostname,
                asset_title=config['asset_title'],
                environment=environment
            )

            if thumbnail_file.exists():
                temp_thumb_path = upload_temp_dir / "thumbnail.jpg"
                logger.info(f"\n-> Upload Thumbnail als: thumbnail.jpg")
                publish_to_stac_wrapper(
                    asset_path=temp_thumb_path,
                    item_name=item_name,
                    collection=STAC_COLLECTION,
                    geocat_id=GEOCAT_ID,
                    hostname=hostname,
                    asset_title="THUMBNAIL",
                    environment=environment
                )

            if cog_success:
                cleanup_temp_directory(temp_dir)
                logger.info("\n" + "=" * 70)
                logger.info(f" Nächster Schritt: {config['description']}")
                logger.info(f" URL: https://map.geo.admin.ch/#/map?layers=COG|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{item_name}/{asset_name_base}")
                logger.info("=" * 70)

            return cog_success
        else:
            logger.info(f"i Upload deaktiviert. Dateien gespeichert in: {temp_dir}")
            return True

    except Exception as e:
        logger.error(f"✗ Fehler im Mosaic-Workflow: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def process_dmc4_workflow(
    input_dir, timestamp, upload_enabled, environment, hostname,
    debug: bool = False,
    cog_compress: str = COG_CONFIG['compress'],
    cog_quality: int = COG_CONFIG['quality'],
):
    """
    Workflow für DMC4 4-Kanal Bildstreifen.

    Eingabe: Verzeichnis mit 4-Band TIF-Streifen (kein CRS, Daten in EPSG:2056).
    Bänder: 1=Rot, 2=Grün, 3=Blau, 4=Nahinfrarot.

    Schritte:
      1. Alle .tif-Dateien im Input-Verzeichnis finden
      2. Für jeden Streifen: CRS EPSG:2056 zuweisen + Bänder extrahieren
         - RGB: Bänder 1, 2, 3
         - NRG: Bänder 4, 1, 2 (Nahinfrarot, Rot, Grün)
      3. VRT-Mosaike bauen (RGB + NRG)
      4. Als COG konvertieren
      5. Thumbnail aus RGB-COG erstellen
      6. RGB-COG, NRG-COG und Thumbnail ins gleiche STAC-Item hochladen
    """
    import tempfile
    import subprocess as _sp  # used for gdalbuildvrt (no -progress support)
    from utilities.file_handler import get_tif_files
    from utilities.mosaic_processor import create_thumbnail_from_cog

    try:
        output_dir = Path("output") if not upload_enabled else Path("temp")
        output_dir.mkdir(exist_ok=True)

        timestamp_ms   = _ensure_ms_suffix(timestamp)
        # Both RGB and NRG share the same item name (no product suffix in item)
        item_name      = generate_item_name(timestamp_ms, ProductType.QDOP_RGB)
        config_rgb     = get_product_config(ProductType.QDOP_RGB)
        config_nrg     = get_product_config(ProductType.QDOP_NRG)
        asset_name_rgb = generate_asset_name(timestamp_ms, ProductType.QDOP_RGB)
        asset_name_nrg = generate_asset_name(timestamp_ms, ProductType.QDOP_NRG)

        logger.info("=" * 70)
        logger.info("DMC4 PROCESSING (RGB + NRG)")
        logger.info("=" * 70)
        logger.info(f"STAC Item:      {item_name}")
        logger.info(f"STAC Asset RGB: {asset_name_rgb}")
        logger.info(f"STAC Asset NRG: {asset_name_nrg}")

        input_files = get_tif_files(input_dir, recursive=False)
        if not input_files:
            logger.error("✗ Keine TIFF-Dateien im Input-Verzeichnis gefunden!")
            return False
        logger.info(f"\nGefunden: {len(input_files)} DMC4 Streifen")

        cog_rgb = output_dir / asset_name_rgb
        cog_nrg = output_dir / asset_name_nrg

        with tempfile.TemporaryDirectory() as _tmp:
            tmp   = Path(_tmp)
            t_rgb = tmp / "rgb"
            t_nrg = tmp / "nrg"
            t_rgb.mkdir()
            t_nrg.mkdir()

            # Step 1: extract bands + assign CRS + tag nodata for each stripe
            # -a_nodata 0 tags nodata in output metadata; gdalbuildvrt reads it
            total = len(input_files)
            for idx, tif in enumerate(input_files, 1):
                stem = tif.stem
                for label, bands, out_dir in [
                    ("RGB", ["1", "2", "3"], t_rgb),
                    ("NRG", ["4", "1", "2"], t_nrg),
                ]:
                    out = out_dir / f"{stem}_{label.lower()}.tif"
                    cmd = ["gdal_translate", "-a_srs", "EPSG:2056"]
                    for b in bands:
                        cmd += ["-b", b]
                    cmd += ["-a_nodata", "0", str(tif), str(out)]
                    if not _run_gdal(
                        f"[{idx}/{total}] Streifen {label}: {tif.name}", cmd,
                        output_path=out
                    ):
                        return False

            logger.info("✓ Bänder extrahiert und CRS EPSG:2056 zugewiesen (nodata=0)")

            # Step 2: build VRT mosaics — honour nodata so stripe gaps are transparent
            # gdalbuildvrt does not support -progress, run quietly
            import subprocess as _sp
            for label, src_dir, vrt_name in [
                ("RGB", t_rgb, "mosaic_rgb.vrt"),
                ("NRG", t_nrg, "mosaic_nrg.vrt"),
            ]:
                vrt = tmp / vrt_name
                files = sorted(str(f) for f in src_dir.glob("*.tif"))
                logger.info(f"  → VRT Mosaic {label} ({len(files)} Streifen) ...")
                r = _sp.run(
                    ["gdalbuildvrt"] + GDAL_PERF_FLAGS +
                    ["-srcnodata", "0 0 0", str(vrt)] + files,
                    stderr=_sp.PIPE, text=True
                )
                if r.returncode != 0:
                    logger.error(f"    ✗ gdalbuildvrt {label} fehlgeschlagen")
                    if r.stderr.strip():
                        logger.error(r.stderr.strip())
                    return False
                logger.info(f"    ✓ {vrt.name}")

            logger.info("✓ VRT-Mosaike erstellt")

            # Step 3: convert VRTs to COG (nodata preserved)
            _cog_co = ["-co", f"COMPRESS={cog_compress}"]
            if cog_compress.upper() == "JPEG":
                _cog_co += ["-co", f"QUALITY={cog_quality}"]
            for label, vrt_name, cog in [
                ("RGB", "mosaic_rgb.vrt", cog_rgb),
                ("NRG", "mosaic_nrg.vrt", cog_nrg),
            ]:
                if not _run_gdal(
                    f"COG {label}: {cog.name}",
                    ["gdal_translate", "-of", "COG",
                     *_cog_co,
                     "-co", "BIGTIFF=YES",
                     "-a_nodata", "0",
                     str(tmp / vrt_name), str(cog)],
                    output_path=cog
                ):
                    return False

        logger.info("✓ COG-Dateien erstellt")

        # Step 4: thumbnail from RGB COG
        thumbnail_file = output_dir / "thumbnail.jpg"
        create_thumbnail_from_cog(cog_rgb, thumbnail_file, max_size=256)

        if not upload_enabled:
            logger.info(f"i Upload deaktiviert. Dateien gespeichert in: {output_dir}")
            return True

        # Step 5: upload RGB, NRG and thumbnail to the same STAC item
        ok_rgb = publish_to_stac_wrapper(
            asset_path=cog_rgb, item_name=item_name,
            collection=STAC_COLLECTION, geocat_id=GEOCAT_ID,
            hostname=hostname, asset_title=config_rgb['asset_title'],
            environment=environment
        )
        ok_nrg = publish_to_stac_wrapper(
            asset_path=cog_nrg, item_name=item_name,
            collection=STAC_COLLECTION, geocat_id=GEOCAT_ID,
            hostname=hostname, asset_title=config_nrg['asset_title'],
            environment=environment
        )
        if thumbnail_file.exists():
            publish_to_stac_wrapper(
                asset_path=thumbnail_file, item_name=item_name,
                collection=STAC_COLLECTION, geocat_id=GEOCAT_ID,
                hostname=hostname, asset_title="THUMBNAIL",
                environment=environment
            )

        if ok_rgb and ok_nrg:
            cleanup_temp_directory(output_dir)
            logger.info("\n" + "=" * 70)
            logger.info(f"Nächster Schritt: URL für rapidmapping.ch")
            logger.info(f" RGB: https://map.geo.admin.ch/#/map?layers=COG|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{item_name}/{asset_name_rgb}")
            logger.info(f" NRG: https://map.geo.admin.ch/#/map?layers=COG|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{item_name}/{asset_name_nrg}")
            logger.info("=" * 70)

        return ok_rgb and ok_nrg

    except Exception as e:
        logger.error(f"✗ Fehler im DMC4-Workflow: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def process_photos_workflow(
    input_dir, product_type, date, upload_enabled, environment, hostname,
    debug: bool = False,
):
    """
    import logging as _logging
    if not debug:
        for _mod in ['utilities.stac_publisher', 'utilities.credentials',
                     'utilities.proxy_handler', 'main_multipart_upload_via_api',
                     'util_publish_stac_fsdi', 'utilities.kml_generator']:
            _logging.getLogger(_mod).setLevel(_logging.WARNING)
    # Workflow fuer Einzelbilder: Upload -> KML -> CSV.

    v2.2:
    - KML/CSV Overview-Item: Timestamp t23595900 (ms-Suffix "00")
    - generate_csv_from_stac fragt STAC per Datum+Suffix ab -> findet alle
      Items unabhaengig vom ms-Suffix (Bug 3 automatisch geloest)
    """
    try:
        import logging
        from pathlib import Path
        from configuration import (
            STAC_COLLECTION, GEOCAT_ID, STAC_SCHEME, STAC_API_PATH,
            get_product_config, generate_item_name
        )
        from utilities.photo_processor import process_individual_photos, generate_csv_from_stac
        from utilities.kml_generator import create_overview_kml
        from utilities.stac_publisher import publish_to_stac_wrapper

        logger = logging.getLogger(__name__)

        temp_dir = Path("output") if not upload_enabled else Path("temp")
        temp_dir.mkdir(exist_ok=True)

        config         = get_product_config(product_type)
        product_suffix = config['suffix'].replace('-mosaic', '').replace('-photo', '')
        stac_url       = f"{STAC_SCHEME}://{hostname}{STAC_API_PATH}"

        logger.info("=" * 70)
        logger.info("INDIVIDUAL PHOTOS PROCESSING")
        logger.info("=" * 70)

        result = process_individual_photos(
            input_dir=input_dir,
            output_dir=temp_dir,
            product_config=config,
            product_type=product_type,
            stac_collection=STAC_COLLECTION,
            geocat_id=GEOCAT_ID,
            hostname=hostname,
            environment=environment,
            upload_enabled=upload_enabled,
            debug=debug,
        )

        if not result:
            logger.error("✗ Photo-Verarbeitung fehlgeschlagen")
            return False

        kml_item_name  = None
        kml_asset_name = None
        csv_file       = None

        if result['successful_uploads'] > 0:

            logger.info("\n" + "=" * 70)
            logger.info("GENERIERE KML-OVERVIEW (via STAC-Abfrage)")
            logger.info("=" * 70)

            # NEU v2.2: Overview-Item mit ms-Suffix "00"
            kml_timestamp  = f"{date}t23595900"
            kml_item_name  = generate_item_name(kml_timestamp, product_type)
            product_short  = config['suffix'].split('-')[0]  # 'ebn' or 'ebo'
            kml_asset_name = f"{kml_item_name}-{product_short}.kml"
            kml_file       = temp_dir / kml_asset_name

            kml_success = create_overview_kml(
                stac_url=stac_url,
                collection=STAC_COLLECTION,
                date=date,
                product_suffix=product_suffix,
                product_config=config,
                output_file=kml_file
            )

            if kml_success:
                logger.info(f"\n-> Upload KML-Overview als: {kml_asset_name}")
                publish_to_stac_wrapper(
                    asset_path=kml_file,
                    item_name=kml_item_name,
                    collection=STAC_COLLECTION,
                    geocat_id=GEOCAT_ID,
                    hostname=hostname,
                    asset_title=f"{config['asset_title']}-OVERVIEW",
                    environment=environment
                )

            if upload_enabled:
                logger.info("\n" + "=" * 70)
                logger.info("GENERIERE CSV AUS STAC")
                logger.info("=" * 70)

                csv_asset_name = f"{kml_item_name}-{product_short}.txt"
                csv_file       = temp_dir / csv_asset_name

                csv_ok = generate_csv_from_stac(
                    stac_url=stac_url,
                    collection=STAC_COLLECTION,
                    date=date,
                    product_suffix=product_suffix,
                    output_file=csv_file
                )

                if csv_ok and csv_file.exists():
                    logger.info(f"\n-> Upload TXT als: {csv_asset_name} -> Item: {kml_item_name}")
                    publish_to_stac_wrapper(
                        asset_path=csv_file,
                        item_name=kml_item_name,
                        collection=STAC_COLLECTION,
                        geocat_id=GEOCAT_ID,
                        hostname=hostname,
                        asset_title=f"{config['asset_title']}-LISTE",
                        environment=environment
                    )

        elif not upload_enabled:
            logger.info("i Upload deaktiviert - KML/CSV-Generierung uebersprungen")

        photos = result['photos']
        if result['successful_uploads'] == len(photos):
            from utilities.file_handler import cleanup_temp_directory
            cleanup_temp_directory(temp_dir)

            if kml_item_name:
                csv_stac_url = (
                    f"{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}"
                    f"/{kml_item_name}/{csv_asset_name}"
                )
                # Links immer ausgeben — auch im non-debug Modus
                logger.info("\n" + "=" * 70)
                logger.info(f" Nächster Schritt: {config['description']}")
                logger.info(f" Karte:  https://map.geo.admin.ch/#/map?layers=KML|{STAC_SCHEME}://{hostname}/{STAC_COLLECTION}/{kml_item_name}/{kml_asset_name}")
                logger.info(f" Liste:  {csv_stac_url}")
                logger.info("=" * 70)

        return result['successful_uploads'] > 0

    except Exception as e:
        import logging, traceback
        logging.getLogger(__name__).error(f"Fehler im Photos-Workflow: {str(e)}")
        logging.getLogger(__name__).error(traceback.format_exc())
        return False




# ============================================================
# C) DEBUG-MODUS: Direkt hier setzen wenn ohne CLI-Argumente gestartet wird.
#    True  = sequentielle Verarbeitung + volles Logging (Debugging)
#    False = parallele Verarbeitung, minimales Logging (Produktion)
DEBUG_MODE_DEFAULT = False
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description='Swisstopo Rapid Mapping Processor v2.0 (subprocess); POC!',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Beispiele (interaktiv):
    python rapidmapping_processor.py
    python rapidmapping_processor.py --prod
    python rapidmapping_processor.py --upload=False

    Beispiele (vollständig via CLI):
    python rapidmapping_processor.py --product ebn --input C:\\data\\rm --timestamp 2025-09-03
    python rapidmapping_processor.py --product qdop-rgb --input /data/rm --timestamp 2024-07-15t143000
    python rapidmapping_processor.py --product ebo --input /data/rm --timestamp 2025-03-12 --upload=False
    python rapidmapping_processor.py --product qdop-nrg --input /data --timestamp 2024-07-15t14300000 --prod
    python rapidmapping_processor.py --product ebn --input /data --timestamp 2025-09-03 --debug
    python rapidmapping_processor.py --proxy direct --product ebn --input /data --timestamp 2025-09-03
    python rapidmapping_processor.py --proxy system --product ebn --input /data --timestamp 2025-09-03
    python rapidmapping_processor.py --proxy BVCOL  --product ebn --input /data --timestamp 2025-09-03
        """
    )
    # Basic options
    parser.add_argument('--upload', type=lambda x: x.lower() != 'false', default=True,
                        help='Upload zu STAC (default: True). False = Ausgabe in ./output/')
    parser.add_argument('--prod', action='store_true',
                        help='Produktionsumgebung verwenden (default: INT)')
    parser.add_argument('--debug', action='store_true', default=None,
                        help='Debug-Modus: sequentiell + volles Logging')

    # D) Full CLI product configuration (optional — falls nicht angegeben: interaktiv)
    parser.add_argument('--input', '--input-dir', dest='input_dir', default=None,
                        metavar='VERZEICHNIS',
                        help='Quellverzeichnis mit Eingabedaten')
    parser.add_argument('--product', dest='product', default=None,
                        choices=['ebn', 'ebo', 'qdop-rgb', 'qdop-nrg', 'qdop-dmc4'],
                        help='Produkttyp: ebn, ebo, qdop-rgb, qdop-nrg, qdop-dmc4')
    parser.add_argument('--timestamp', '--date', dest='timestamp', default=None,
                        metavar='TIMESTAMP',
                        help=('Zeitstempel/Datum. '
                              'QDOP/EBN/EBO: YYYY-MM-DDthhmmss[cc]  '
                              'EBN/EBO Datum: YYYY-MM-DD'))
    parser.add_argument('--proxy', dest='proxy', default=None,
                        metavar='MODUS',
                        help=('Netzwerk-Modus: '
                              '"auto" (Standard: direkt -> System-Proxy -> proxy_config.json), '
                              '"direct" (kein Proxy, direkte Verbindung), '
                              '"system" (nur System-Proxy/Bundesnetz), '
                              'oder Proxy-Name aus proxy_config.json (z.B. "BVCOL")'))
    parser.add_argument('--cog-compress', dest='cog_compress', default=COG_CONFIG['compress'],
                        metavar='VERFAHREN',
                        help=f"COG-Kompressionsverfahren, nur für qdop-dmc4 (default: {COG_CONFIG['compress']})")
    parser.add_argument('--cog-quality', dest='cog_quality', type=int, default=COG_CONFIG['quality'],
                        metavar='1-100',
                        help=f"JPEG-Qualität für COG, nur bei --cog-compress JPEG (default: {COG_CONFIG['quality']})")

    args = parser.parse_args()
    _is_full_cli = bool(args.product and args.input_dir and args.timestamp)

    if not (1 <= args.cog_quality <= 100):
        logger.error(f"✗ --cog-quality muss zwischen 1 und 100 liegen (erhalten: {args.cog_quality})")
        sys.exit(1)

    # C) Resolve debug flag: CLI > DEBUG_MODE_DEFAULT
    if args.debug is None:
        args.debug = DEBUG_MODE_DEFAULT

    try:
        print_banner()

        # First interactive question: environment (INT/PROD)
        if args.prod:
            environment = "PROD"
        elif not _is_full_cli:
            environment = prompt_environment()
        else:
            environment = "INT"

        if args.upload:
            prompt_secrets_dir_if_missing()

            logger.info("=" * 70)
            logger.info(f"CREDENTIALS ({environment})")
            logger.info("=" * 70)
            username, password, hostname = load_stac_credentials(environment=environment)
            logger.info(f"✓ Credentials geladen: {hostname}")

            logger.info("=" * 70)
            logger.info("PROXY / NETZWERK")
            logger.info("=" * 70)

            # Resolve proxy mode:
            #   --proxy <value>  → use that value directly
            #   no --proxy, fully CLI (product+input+timestamp all set) → auto
            #   no --proxy, interactive mode → show prompt
            if args.proxy is not None:
                _proxy_arg = args.proxy.strip()
                if _proxy_arg.lower() == 'auto':
                    _proxy_mode, _proxy_name = 'auto', None
                elif _proxy_arg.lower() in ('direct', 'kein'):
                    _proxy_mode, _proxy_name = 'direct', None
                elif _proxy_arg.lower() == 'system':
                    _proxy_mode, _proxy_name = 'system', None
                else:
                    _proxy_mode, _proxy_name = 'named', _proxy_arg
                logger.info(f"✓ Netzwerk-Modus (CLI): {args.proxy}")
            elif _is_full_cli:
                _proxy_mode, _proxy_name = 'auto', None
                logger.info("✓ Netzwerk-Modus: Autodetect (Standard)")
            else:
                _proxy_mode, _proxy_name = prompt_proxy_mode()

            initialize_proxy(mode=_proxy_mode, proxy_name=_proxy_name)
        else:
            hostname = None

        logger.info("=" * 70)
        logger.info("KONFIGURATION")
        logger.info("=" * 70)

        # D) CLI params take priority; fall back to interactive prompts
        _product_map = {
            'ebn': ProductType.EBN, 'ebo': ProductType.EBO,
            'qdop-rgb': ProductType.QDOP_RGB, 'qdop-nrg': ProductType.QDOP_NRG,
            'qdop-dmc4': ProductType.QDOP_DMC4,
        }

        if args.input_dir:
            input_dir = validate_directory(args.input_dir)
            logger.info(f"✓ Input-Verzeichnis (CLI): {input_dir}")
        else:
            input_dir = prompt_input_directory()

        if args.product:
            product_type = _product_map[args.product]
            logger.info(f"✓ Produkttyp (CLI): {product_type.value}")
        else:
            product_type = prompt_product_type()

        if args.timestamp:
            ts = normalize_cli_timestamp(args.timestamp.lower().strip())
            if product_type in (ProductType.EBN, ProductType.EBO):
                # EBN/EBO: accept date only (YYYY-MM-DD)
                try:
                    datetime.strptime(ts[:10], '%Y-%m-%d')
                    timestamp_or_date = ts[:10]
                except ValueError:
                    logger.error(
                        f"✗ Ungültiges Datum: {args.timestamp}. Erwartet: YYYY-MM-DD"
                    )
                    return 1
            else:
                # QDOP: require full timestamp YYYY-MM-DDthhmmss[cc]
                if not validate_timestamp(ts):
                    logger.error(
                        f"✗ Ungültiger Zeitstempel: {args.timestamp}. "
                        f"Erwartet: YYYY-MM-DDthhmmss[cc] oder YYYYMMDDthhmmss[cc]"
                    )
                    return 1
                timestamp_or_date = ts
            logger.info(f"✓ Zeitstempel (CLI): {timestamp_or_date}")
        else:
            timestamp_or_date = prompt_timestamp(product_type)

        print("\n" + "=" * 70)
        print("ZUSAMMENFASSUNG")
        print("=" * 70)
        print(f" Environment:    {environment}")
        print(f" Input-Verz.:    {input_dir}")
        print(f" Produkttyp:     {product_type.value}")
        print(f" Zeitstempel:    {timestamp_or_date}")
        print(f" STAC Upload:    {'Aktiviert' if args.upload else 'Deaktiviert (→ ./output/)'}")
        print(f" Debug-Modus:    {'AN (sequentiell)' if args.debug else 'AUS (parallel)'}")
        if args.upload:
            print(f" STAC Hostname:  {hostname}")
        else:
            from pathlib import Path as _P
            _P("output").mkdir(exist_ok=True)
            print(f" Output-Verz.:   {_P('output').resolve()}")
        print("=" * 70)

        # Skip confirmation when all parameters supplied via CLI
        _all_cli = (args.input_dir is not None
                    and args.product is not None
                    and args.timestamp is not None)
        if _all_cli:
            logger.info("▶ CLI-Modus: Starte ohne Bestätigung")
            confirm = 'j'
        else:
            confirm = input("\n▶ Verarbeitung starten? [j/N]: ").strip().lower()
        if confirm not in ['j', 'ja', 'y', 'yes']:
            logger.info("Abbruch")
            return 0

        print("\n" + "=" * 70)
        print("VERARBEITUNG GESTARTET")
        print("=" * 70 + "\n")

        # ── Log-Datei einrichten ──────────────────────────────────────────────
        # Namenskonvention: <stac-datum>_<produkttyp>_<importDatum>.log
        # z.B. logs/2025-09-03_ebn_20260908-143512.log
        _logs_dir     = Path("logs")
        _logs_dir.mkdir(exist_ok=True)
        _log_ts       = datetime.now().strftime('%Y%m%d-%H%M%S')
        _log_filename = _logs_dir / f"{timestamp_or_date}_{product_type.value}_{_log_ts}.log"
        _log_handler  = logging.FileHandler(_log_filename, encoding='utf-8')
        _log_handler.setLevel(logging.INFO)
        _log_handler.setFormatter(
            logging.Formatter('%(asctime)s %(levelname)-8s %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')
        )
        logging.getLogger().addHandler(_log_handler)
        logger.info(f"Log-Datei: {_log_filename}")
        # ─────────────────────────────────────────────────────────────────────

        try:
            if product_type in [ProductType.QDOP_RGB, ProductType.QDOP_NRG]:
                success = process_mosaic_workflow(
                    input_dir, product_type, timestamp_or_date,
                    args.upload, environment, hostname,
                    debug=args.debug
                )
            elif product_type == ProductType.QDOP_DMC4:
                success = process_dmc4_workflow(
                    input_dir, timestamp_or_date,
                    args.upload, environment, hostname,
                    debug=args.debug,
                    cog_compress=args.cog_compress,
                    cog_quality=args.cog_quality
                )
            else:
                success = process_photos_workflow(
                    input_dir, product_type, timestamp_or_date,
                    args.upload, environment, hostname,
                    debug=args.debug
                )
        finally:
            logging.getLogger().removeHandler(_log_handler)
            _log_handler.close()

        print("\n" + "=" * 70)
        if success:
            logger.info("✓ VERARBEITUNG ERFOLGREICH")
        else:
            logger.error("✗ VERARBEITUNG MIT FEHLERN")
        print(f" Log:  {Path(_log_filename).resolve()}")
        print("=" * 70 + "\n")

        return 0 if success else 1

    except KeyboardInterrupt:
        logger.warning("\nAbbruch (Ctrl+C)")
        return 130
    except Exception as e:
        logger.error(f"✗ Fehler: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())