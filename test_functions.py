"""
Unit-Tests für die reinen Python-Funktionen von topo-rapidmapping.

Getestet werden nur Funktionen ohne echte GDAL-/Netzwerk-Abhängigkeiten
(kein rapidmapping_processor.py-Hauptlauf, kein echter STAC-Upload). Wo ein
Modul beim Import rasterio/pyproj braucht (util_publish_stac_fsdi.py), wird
das per Mock ersetzt, damit die Tests auch ohne OSGeo4W-Installation laufen.

Ausführen:
    python test_functions.py
    python -m pytest test_functions.py -v   (falls pytest installiert)
"""

import math
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# util_publish_stac_fsdi.py importiert rasterio/pyproj auf Modulebene
# (u.a. für pyproj.Transformer.from_crs(...) beim Import) — durch Mocks
# ersetzen, damit der Import auch ohne OSGeo4W-Umgebung funktioniert.
sys.modules.setdefault("rasterio", MagicMock())
sys.modules.setdefault("pyproj", MagicMock())

import configuration
from configuration import ProductType
from utilities import file_handler
from utilities import gdal_helpers
from utilities import photo_processor
from utilities import kml_generator
from utilities import proxy_handler
import main_multipart_upload_via_api
import util_publish_stac_fsdi
import rapidmapping_processor
from datetime import date
from utilities import util_stac_delete_ram


# ============================================================
#  configuration.validate_timestamp
# ============================================================
class TestValidateTimestamp(unittest.TestCase):

    def test_gueltiger_6stelliger_zeitstempel(self):
        self.assertTrue(configuration.validate_timestamp("2024-07-15t143000"))

    def test_gueltiger_8stelliger_zeitstempel_mit_hundertstel(self):
        self.assertTrue(configuration.validate_timestamp("2024-07-15t14300099"))

    def test_ungueltiger_monat(self):
        self.assertFalse(configuration.validate_timestamp("2024-13-01t000000"))

    def test_ungueltiger_tag(self):
        self.assertFalse(configuration.validate_timestamp("2024-01-32t000000"))

    def test_fehlendes_t_trennzeichen(self):
        self.assertFalse(configuration.validate_timestamp("2024-07-15 143000"))

    def test_leerer_string(self):
        self.assertFalse(configuration.validate_timestamp(""))


# ============================================================
#  configuration.normalize_cli_timestamp
# ============================================================
class TestNormalizeCliTimestamp(unittest.TestCase):

    def test_kompaktes_datum(self):
        self.assertEqual(configuration.normalize_cli_timestamp("20240715"), "2024-07-15")

    def test_kompakter_zeitstempel(self):
        self.assertEqual(
            configuration.normalize_cli_timestamp("20240715t143000"), "2024-07-15t143000"
        )

    def test_kompakter_zeitstempel_mit_hundertstel(self):
        self.assertEqual(
            configuration.normalize_cli_timestamp("20240715t14300099"), "2024-07-15t14300099"
        )

    def test_bereits_normalisiert_bleibt_unveraendert(self):
        self.assertEqual(
            configuration.normalize_cli_timestamp("2024-07-15t143000"), "2024-07-15t143000"
        )

    def test_unbekanntes_format_wird_unveraendert_zurueckgegeben(self):
        # Kein Crash — validate_timestamp() weist es später sauber zurück
        self.assertEqual(configuration.normalize_cli_timestamp("garbage"), "garbage")


# ============================================================
#  configuration.ensure_hundredths_suffix
# ============================================================
class TestEnsureHundredthsSuffix(unittest.TestCase):

    def test_fuegt_fehlendes_suffix_an(self):
        self.assertEqual(
            configuration.ensure_hundredths_suffix("2024-07-15t143000"), "2024-07-15t14300000"
        )

    def test_laesst_vorhandenes_suffix_unveraendert(self):
        self.assertEqual(
            configuration.ensure_hundredths_suffix("2024-07-15t14300099"), "2024-07-15t14300099"
        )


# ============================================================
#  configuration: Item-/Asset-Namenskonvention
# ============================================================
class TestItemAssetNaming(unittest.TestCase):

    def test_item_name_hat_ram_prefix_und_hundertstel_suffix(self):
        name = configuration.generate_item_name("2024-07-15t143000", ProductType.QDOP_RGB)
        self.assertEqual(name, "ram-2024-07-15t14300000")

    def test_asset_name_enthaelt_produkt_suffix_und_extension(self):
        name = configuration.generate_asset_name("2024-07-15t143000", ProductType.QDOP_RGB)
        self.assertTrue(name.startswith("ram-2024-07-15t14300000-"))
        self.assertTrue(name.endswith(".tif"))

    def test_alle_produkttypen_haben_gueltige_config(self):
        # QDOP_DMC4 hat bewusst keinen eigenen Eintrag: process_dmc4_workflow()
        # holt stattdessen die Configs von QDOP_RGB und QDOP_NRG separat,
        # da DMC4 aus einem Streifen beide Mosaike gleichzeitig erzeugt.
        for product in ProductType:
            if product is ProductType.QDOP_DMC4:
                with self.assertRaises(KeyError):
                    configuration.get_product_config(product)
                continue
            config = configuration.get_product_config(product)
            self.assertIn("suffix", config)
            self.assertIn("file_extension", config)
            self.assertTrue(config["file_extension"].startswith("."))


# ============================================================
#  utilities.file_handler.validate_directory
# ============================================================
class TestValidateDirectory(unittest.TestCase):

    def test_existierendes_verzeichnis_wird_akzeptiert(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = file_handler.validate_directory(tmp)
            self.assertEqual(result, Path(tmp))

    def test_nicht_existierendes_verzeichnis_wirft_filenotfounderror(self):
        with self.assertRaises(FileNotFoundError):
            file_handler.validate_directory(r"C:\dieser\pfad\existiert\sicher\nicht_12345")

    def test_leerer_pfad_wirft_valueerror(self):
        with self.assertRaises(ValueError):
            file_handler.validate_directory("")

    def test_datei_statt_verzeichnis_wirft_valueerror(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_path = tmp_file.name
        try:
            with self.assertRaises(ValueError):
                file_handler.validate_directory(tmp_path)
        finally:
            os.unlink(tmp_path)


# ============================================================
#  utilities.file_handler: Bilddatei-Suche
# ============================================================
class TestImageFileDiscovery(unittest.TestCase):

    def _make_files(self, tmp, names):
        for name in names:
            (Path(tmp) / name).touch()

    def test_get_tif_files_findet_nur_tif_dateien(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_files(tmp, ["a.tif", "b.TIFF", "c.jpg", "notes.txt"])
            result = file_handler.get_tif_files(Path(tmp))
            self.assertEqual({p.name for p in result}, {"a.tif", "b.TIFF"})

    def test_get_jpg_files_findet_nur_jpg_dateien(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_files(tmp, ["a.jpg", "b.jpeg", "c.tif"])
            result = file_handler.get_jpg_files(Path(tmp))
            self.assertEqual({p.name for p in result}, {"a.jpg", "b.jpeg"})

    def test_leeres_verzeichnis_wirft_valueerror(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                file_handler.get_tif_files(Path(tmp))


# ============================================================
#  utilities.file_handler.get_file_size_mb
# ============================================================
class TestFileSizeMb(unittest.TestCase):

    def test_dateigroesse_wird_korrekt_in_mb_umgerechnet(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(b"0" * (2 * 1024 * 1024))  # exakt 2 MiB
            tmp_path = tmp_file.name
        try:
            size_mb = file_handler.get_file_size_mb(Path(tmp_path))
            self.assertAlmostEqual(size_mb, 2.0, places=6)
        finally:
            os.unlink(tmp_path)


# ============================================================
#  main_multipart_upload_via_api.b64_md5
# ============================================================
class TestB64Md5(unittest.TestCase):

    def test_bekannter_wert_leerer_bytestring(self):
        # md5("") = d41d8cd98f00b204e9800998ecf8427e -> Base64 der Rohbytes
        self.assertEqual(
            main_multipart_upload_via_api.b64_md5(b""), "1B2M2Y8AsgTpgAmY7PhCfg=="
        )


# ============================================================
#  utilities.gdal_helpers.supports_progress (subprocess gemockt)
# ============================================================
class TestSupportsProgress(unittest.TestCase):

    def setUp(self):
        # Cache zwischen Tests zurücksetzen, da supports_progress() ihn
        # modulweit persistiert.
        gdal_helpers._GDAL_PROGRESS_SUPPORTED.clear()

    def test_erkennt_progress_flag_aus_help_ausgabe(self):
        fake_result = MagicMock(stdout="... -progress ...", stderr="")
        with patch("subprocess.run", return_value=fake_result) as mock_run:
            self.assertTrue(gdal_helpers.supports_progress("gdal_translate"))
            mock_run.assert_called_once()

    def test_ergebnis_wird_pro_executable_gecacht(self):
        fake_result = MagicMock(stdout="-progress", stderr="")
        with patch("subprocess.run", return_value=fake_result) as mock_run:
            gdal_helpers.supports_progress("gdalwarp")
            gdal_helpers.supports_progress("gdalwarp")
            self.assertEqual(mock_run.call_count, 1, "zweiter Aufruf hätte aus dem Cache kommen müssen")

    def test_fehlendes_progress_flag_wird_erkannt(self):
        fake_result = MagicMock(stdout="... keine Progress-Option ...", stderr="")
        with patch("subprocess.run", return_value=fake_result):
            self.assertFalse(gdal_helpers.supports_progress("ogr2ogr"))


# ============================================================
#  utilities.photo_processor.parse_exif_timestamp
#  Regressionstest: Bilder ohne ermittelbaren Timestamp dürfen NIE das
#  aktuelle Datum als Ersatzwert bekommen (siehe CLAUDE.md, Abschnitt Timestamps).
# ============================================================
class TestParseExifTimestamp(unittest.TestCase):

    def test_gueltiger_exif_timestamp(self):
        result = photo_processor.parse_exif_timestamp("2025:07:10 08:00:28", "foto.jpg")
        self.assertEqual(result, "2025-07-10t08002800")

    def test_exif_timestamp_mit_ms_offset(self):
        result = photo_processor.parse_exif_timestamp("2025:07:10 08:00:28:01", "foto.jpg")
        self.assertEqual(result, "2025-07-10t08002801")

    def test_fallback_auf_timestamp_im_dateinamen(self):
        result = photo_processor.parse_exif_timestamp(None, "IMG_20240715_120523.jpg")
        self.assertEqual(result, "2024-07-15t12052300")

    def test_kein_timestamp_ermittelbar_gibt_none_zurueck_kein_heutiges_datum(self):
        result = photo_processor.parse_exif_timestamp(None, "dsc0001.jpg")
        self.assertIsNone(result, "darf NIE auf das aktuelle Datum zurückfallen")

    def test_ungueltiger_exif_timestamp_faellt_auf_none_zurueck(self):
        result = photo_processor.parse_exif_timestamp("nicht-geparst-werdbar", "dsc0002.jpg")
        self.assertIsNone(result)


# ============================================================
#  utilities.photo_processor._assign_sequential_ms_offsets
# ============================================================
class TestAssignSequentialMsOffsets(unittest.TestCase):

    def _gdalinfo_text(self, timestamp: str) -> str:
        return f"Metadata:\n  TIFFTAG_DATETIME={timestamp}\n"

    def test_eindeutiger_timestamp_bekommt_offset_00(self):
        tif = Path("bild_001.tif")
        cache = {tif: self._gdalinfo_text("2025:07:10 08:00:28")}
        result = photo_processor._assign_sequential_ms_offsets([tif], cache)
        self.assertEqual(result[tif], "2025:07:10 08:00:28:00")

    def test_burst_gruppe_bekommt_sequentielle_offsets(self):
        tifs = [Path(f"001_id111cL15015{n}.tif") for n in (6, 7, 8)]
        cache = {t: self._gdalinfo_text("2025:07:10 08:00:28") for t in tifs}
        result = photo_processor._assign_sequential_ms_offsets(tifs, cache)
        offsets = sorted(v.split(":")[-1] for v in result.values())
        self.assertEqual(offsets, ["01", "02", "03"])

    def test_fehlender_timestamp_wird_als_no_ts_markiert(self):
        tif = Path("kaputt.tif")
        cache = {tif: "Metadata:\n  (kein TIFFTAG_DATETIME vorhanden)\n"}
        result = photo_processor._assign_sequential_ms_offsets([tif], cache)
        self.assertTrue(
            result[tif].startswith("__no_ts_"),
            "muss als 'kein Timestamp' erkennbar sein, damit die Datei übersprungen wird",
        )


# ============================================================
#  util_publish_stac_fsdi.asset_create_title
#  Regressionstest: löste vorher einen AttributeError statt einer
#  klaren Fehlermeldung aus, wenn kein Muster im Dateinamen passte.
# ============================================================
class TestAssetCreateTitle(unittest.TestCase):

    def test_thumbnail_bekommt_festen_titel(self):
        self.assertEqual(
            util_publish_stac_fsdi.asset_create_title("thumbnail.jpg", None), "THUMBNAIL"
        )

    def test_titel_aus_zeitstempel_dateiname(self):
        # asset_create_title() schneidet alles bis zum ersten "_" nach dem
        # Datum ab -> Titel entspricht dem Teil danach (ohne Extension).
        title = util_publish_stac_fsdi.asset_create_title(
            "2024-07-15t143000_qdop_rgb.tif", None
        )
        self.assertEqual(title, "QDOP_RGB")

    def test_titel_fuer_current_variante(self):
        title = util_publish_stac_fsdi.asset_create_title(
            "current_qdop_rgb.tif", "current"
        )
        self.assertEqual(title, "QDOP_RGB")

    def test_unpassendes_muster_wirft_klare_valueerror_statt_attributeerror(self):
        with self.assertRaises(ValueError):
            util_publish_stac_fsdi.asset_create_title("ohne_erkennbares_muster.tif", None)


# ============================================================
#  utilities.kml_generator.query_stac_items_by_date
#  Regressionstest: der serverseitige 'datetime'-Filter muss durch eine
#  clientseitige Pruefung abgesichert sein (sonst landet bei fehlender
#  Server-Unterstuetzung effektiv der gesamte Katalog im KML), und die
#  Paginierung muss GET- und POST-'next'-Links korrekt bedienen.
# ============================================================
class TestQueryStacItemsByDate(unittest.TestCase):

    def _feature(self, item_id, dt, has_ebn_asset=True):
        assets = {"thumbnail.jpg": {"href": f"https://x/{item_id}/thumbnail.jpg"}}
        if has_ebn_asset:
            assets[f"{item_id}-ebn-photo.jpg"] = {"href": f"https://x/{item_id}/photo.jpg"}
        return {
            "id": item_id,
            "properties": {"datetime": dt},
            "geometry": {"type": "Point", "coordinates": [7.1, 46.1]},
            "assets": assets,
        }

    def test_items_ausserhalb_des_datums_werden_clientseitig_verworfen(self):
        # Simuliert eine STAC-API, deren 'datetime'-Filter serverseitig nicht greift:
        # Seite 1 enthaelt ein Item vom falschen Tag und ein Overview-Item.
        page1 = {
            "features": [
                self._feature("ram-2025-09-03t120000", "2025-09-03T12:00:00Z"),
                self._feature("ram-2025-09-02t235900", "2025-09-02T23:59:00Z"),  # falscher Tag
                self._feature("ram-2025-09-03t130000-overview", "2025-09-03T13:00:00Z"),  # overview
            ],
            "links": [{"rel": "next", "href": "https://x/search?page=2", "method": "GET"}],
        }
        page2 = {
            "features": [self._feature("ram-2025-09-03t140000", "2025-09-03T14:00:00Z")],
            "links": [],
        }

        mock_session = MagicMock()
        mock_resp1 = MagicMock(); mock_resp1.json.return_value = page1
        mock_resp2 = MagicMock(); mock_resp2.json.return_value = page2
        mock_session.post.return_value = mock_resp1
        mock_session.get.return_value = mock_resp2

        with patch.object(kml_generator, "get_session", return_value=mock_session):
            results = kml_generator.query_stac_items_by_date(
                "https://x/api/stac/v0.9/", "coll", "2025-09-03", "ebn"
            )

        ids = sorted(r["item_id"] for r in results)
        self.assertEqual(ids, ["ram-2025-09-03t120000", "ram-2025-09-03t140000"],
                          "Items vom falschen Tag und Overview-Items duerfen nicht im Ergebnis landen")

        # Erste Seite per POST (mit datetime-Filter im Body), zweite Seite per GET
        # (da der 'next'-Link method=GET meldet) - vorher wurde faelschlicherweise
        # immer gePOSTet.
        mock_session.post.assert_called_once()
        mock_session.get.assert_called_once_with("https://x/search?page=2")

    def test_leeres_ergebnis_bei_fehlerhafter_anfrage(self):
        mock_session = MagicMock()
        mock_session.post.side_effect = RuntimeError("connection failed")
        with patch.object(kml_generator, "get_session", return_value=mock_session):
            results = kml_generator.query_stac_items_by_date(
                "https://x/api/stac/v0.9/", "coll", "2025-09-03", "ebn"
            )
        self.assertEqual(results, [])

    def test_next_link_mit_merge_true_behaelt_collections_und_datetime_filter(self):
        # Regressionstest fuer einen echten Bug (empirisch gegen die STAC-API von
        # data.geo.admin.ch verifiziert): der 'next'-Link dieser API liefert
        # "merge": true mit body={"cursor": ...}. Wird dieser body den
        # urspruenglichen Request-Body ERSETZT statt hineingemergt, gehen
        # collections/datetime/limit ab Seite 2 verloren - die zweite Anfrage
        # durchsucht dann faktisch den gesamten Katalog statt nur den Tag.
        page1 = {
            "features": [self._feature("ram-2025-09-03t120000", "2025-09-03T12:00:00Z")],
            "links": [{
                "rel": "next", "href": "https://x/search",
                "method": "POST", "merge": True,
                "body": {"cursor": "cD0zNzc5NDkxNA=="},
            }],
        }
        page2 = {
            "features": [self._feature("ram-2025-09-03t130000", "2025-09-03T13:00:00Z")],
            "links": [],
        }

        mock_session = MagicMock()
        mock_resp1 = MagicMock(); mock_resp1.json.return_value = page1
        mock_resp2 = MagicMock(); mock_resp2.json.return_value = page2
        mock_session.post.side_effect = [mock_resp1, mock_resp2]

        with patch.object(kml_generator, "get_session", return_value=mock_session):
            results = kml_generator.query_stac_items_by_date(
                "https://x/api/stac/v0.9/", "coll", "2025-09-03", "ebn"
            )

        self.assertEqual(
            sorted(r["item_id"] for r in results),
            ["ram-2025-09-03t120000", "ram-2025-09-03t130000"]
        )

        self.assertEqual(mock_session.post.call_count, 2)
        second_call_body = mock_session.post.call_args_list[1].kwargs["json"]
        self.assertEqual(second_call_body, {
            "collections": ["coll"],
            "datetime": "2025-09-03T00:00:00Z/2025-09-03T23:59:59Z",
            "limit": 100,
            "cursor": "cD0zNzc5NDkxNA==",
        }, "cursor muss in den urspruenglichen Body gemergt werden, nicht ihn ersetzen")


# ============================================================
#  rapidmapping_processor.prompt_secrets_dir_if_missing
#  Der "Simon"-Rettungsanker: App im falschen Arbeitsverzeichnis gestartet
#  (kein 'secrets'-Ordner) -> interaktiv nach dem Pfad fragen und dorthin
#  wechseln, statt erst spaeter mit einer unklaren Fehlermeldung abzubrechen.
# ============================================================
class TestPromptSecretsDirIfMissing(unittest.TestCase):

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmp_root = tempfile.mkdtemp()
        os.chdir(self._tmp_root)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_secrets_ordner_vorhanden_kein_prompt(self):
        (Path(self._tmp_root) / "secrets").mkdir()
        with patch("builtins.input") as mock_input:
            rapidmapping_processor.prompt_secrets_dir_if_missing()
        mock_input.assert_not_called()

    def test_env_credentials_vorhanden_kein_prompt(self):
        with patch.dict(os.environ, {"STAC_USERNAME": "u", "STAC_PASSWORD": "p"}):
            with patch("builtins.input") as mock_input:
                rapidmapping_processor.prompt_secrets_dir_if_missing()
        mock_input.assert_not_called()

    def test_gueltiger_pfad_wechselt_ins_uebergeordnete_arbeitsverzeichnis(self):
        other_root = tempfile.mkdtemp()
        secrets_dir = Path(other_root) / "secrets"
        secrets_dir.mkdir()
        try:
            with patch.dict(os.environ, {"STAC_USERNAME": "", "STAC_PASSWORD": ""}):
                with patch("builtins.input", return_value=str(secrets_dir)):
                    rapidmapping_processor.prompt_secrets_dir_if_missing()
            self.assertEqual(Path(os.getcwd()).resolve(), Path(other_root).resolve())
        finally:
            os.chdir(self._tmp_root)  # weg von other_root, bevor es geloescht wird
            shutil.rmtree(other_root, ignore_errors=True)

    def test_leere_eingabe_bricht_ohne_fehler_ab(self):
        with patch.dict(os.environ, {"STAC_USERNAME": "", "STAC_PASSWORD": ""}):
            with patch("builtins.input", return_value=""):
                rapidmapping_processor.prompt_secrets_dir_if_missing()
        self.assertEqual(Path(os.getcwd()).resolve(), Path(self._tmp_root).resolve())

    def test_voller_cli_aufruf_ruft_prompt_ebenfalls_auf_wenn_secrets_fehlen(self):
        # Ein voller CLI-Aufruf (--product/--input/--timestamp alle gesetzt) wird in
        # der Praxis meistens unbeaufsichtigt gestartet (z.B. Scheduled Task). Der
        # Secrets-Check muss deshalb IMMER laufen, nicht nur im Dialog-Modus - aber
        # mit interactive=False, damit dabei nicht auf Eingabe gewartet wird
        # (siehe test_voller_cli_aufruf_bricht_ohne_input_ab weiter unten).
        fake_argv = [
            'rapidmapping_processor.py',
            '--product', 'ebn',
            '--input', str(Path(self._tmp_root) / 'input'),
            '--timestamp', '2025-09-03',
        ]
        with patch.dict(os.environ, {"STAC_USERNAME": "", "STAC_PASSWORD": ""}), \
             patch.object(sys, 'argv', fake_argv), \
             patch.object(rapidmapping_processor, 'prompt_secrets_dir_if_missing') as mock_prompt:
            rapidmapping_processor.main()

        mock_prompt.assert_called_once_with(interactive=False)

    def test_voller_cli_aufruf_bricht_ohne_input_ab_wenn_secrets_fehlen(self):
        # Kernaenderung: im vollen CLI-Modus wird bei fehlendem 'secrets'-Ordner
        # NICHT mehr interaktiv nachgefragt (ein input() wuerde in einem
        # unbeaufsichtigten Lauf, z.B. Scheduled Task, unbemerkt haengen bleiben).
        # Stattdessen gibt das Tool die Meldung aus und beendet sich sauber mit
        # Exit-Code 1.
        fake_argv = [
            'rapidmapping_processor.py',
            '--product', 'ebn',
            '--input', str(Path(self._tmp_root) / 'input'),
            '--timestamp', '2025-09-03',
        ]
        with patch.dict(os.environ, {"STAC_USERNAME": "", "STAC_PASSWORD": ""}), \
             patch.object(sys, 'argv', fake_argv), \
             patch('builtins.input', side_effect=AssertionError(
                 "voller CLI-Aufruf darf nicht interaktiv nach dem Pfad fragen"
             )):
            exit_code = rapidmapping_processor.main()

        self.assertEqual(exit_code, 1)

    def test_dialog_modus_fragt_weiterhin_interaktiv_nach(self):
        # Gegenprobe: im Dialog-Modus (kein voller CLI-Aufruf) bleibt das bisherige
        # Verhalten erhalten - es wird interaktiv nach dem Pfad gefragt.
        with patch.dict(os.environ, {"STAC_USERNAME": "", "STAC_PASSWORD": ""}):
            with patch("builtins.input", return_value="") as mock_input:
                result = rapidmapping_processor.prompt_secrets_dir_if_missing(interactive=True)
        mock_input.assert_called_once()
        self.assertFalse(result)

    def test_voller_cli_aufruf_ruft_prompt_nicht_auf_wenn_secrets_vorhanden(self):
        # Umgekehrter Fall: 'secrets/' existiert bereits - main() darf im vollen
        # CLI-Modus dann nicht unnoetig auf Eingabe warten. Die eigentliche
        # "existiert schon -> kein Prompt"-Logik liegt in
        # prompt_secrets_dir_if_missing() selbst (siehe deren eigene Tests); hier
        # wird nur sichergestellt, dass main() die Funktion weiterhin tatsaechlich
        # aufruft (Aufruf allein loest ohne fehlenden Ordner keinen input() aus).
        (Path(self._tmp_root) / "secrets").mkdir()
        fake_argv = [
            'rapidmapping_processor.py',
            '--product', 'ebn',
            '--input', str(Path(self._tmp_root) / 'input'),
            '--timestamp', '2025-09-03',
        ]
        with patch.dict(os.environ, {"STAC_USERNAME": "", "STAC_PASSWORD": ""}), \
             patch.object(sys, 'argv', fake_argv), \
             patch('builtins.input', side_effect=AssertionError(
                 "kein Prompt noetig - 'secrets/' existiert bereits"
             )):
            exit_code = rapidmapping_processor.main()

        # Credentials-Datei fehlt weiterhin (nur der Ordner wurde angelegt) ->
        # main() bricht sauber ab, aber ohne je input() aufzurufen.
        self.assertEqual(exit_code, 1)


# ============================================================
#  rapidmapping_processor.use_secrets_dir / --secrets-dir
#  Expliziter Pfad zum 'secrets'-Ordner via CLI-Parameter - Alternative zum
#  interaktiven Prompt bzw. zum unbeaufsichtigten Abbruch (siehe oben).
# ============================================================
class TestUseSecretsDir(unittest.TestCase):

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmp_root = tempfile.mkdtemp()
        os.chdir(self._tmp_root)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_gueltiger_secrets_pfad_wechselt_ins_elternverzeichnis(self):
        other_root = tempfile.mkdtemp()
        secrets_dir = Path(other_root) / "secrets"
        secrets_dir.mkdir()
        try:
            result = rapidmapping_processor.use_secrets_dir(str(secrets_dir))
            self.assertTrue(result)
            self.assertEqual(Path(os.getcwd()).resolve(), Path(other_root).resolve())
        finally:
            os.chdir(self._tmp_root)
            shutil.rmtree(other_root, ignore_errors=True)

    def test_uebergeordneter_pfad_wird_ebenfalls_akzeptiert(self):
        other_root = tempfile.mkdtemp()
        (Path(other_root) / "secrets").mkdir()
        try:
            result = rapidmapping_processor.use_secrets_dir(other_root)
            self.assertTrue(result)
            self.assertEqual(Path(os.getcwd()).resolve(), Path(other_root).resolve())
        finally:
            os.chdir(self._tmp_root)
            shutil.rmtree(other_root, ignore_errors=True)

    def test_nicht_existierender_pfad_gibt_false_zurueck_ohne_chdir(self):
        result = rapidmapping_processor.use_secrets_dir(
            str(Path(self._tmp_root) / "does-not-exist")
        )
        self.assertFalse(result)
        self.assertEqual(Path(os.getcwd()).resolve(), Path(self._tmp_root).resolve())

    def test_voller_cli_aufruf_mit_secrets_dir_fragt_nicht_interaktiv(self):
        other_root = tempfile.mkdtemp()
        (Path(other_root) / "secrets").mkdir()
        try:
            fake_argv = [
                'rapidmapping_processor.py',
                '--product', 'ebn',
                '--input', str(Path(self._tmp_root) / 'input'),
                '--timestamp', '2025-09-03',
                '--secrets-dir', str(Path(other_root) / "secrets"),
            ]
            with patch.dict(os.environ, {"STAC_USERNAME": "", "STAC_PASSWORD": ""}), \
                 patch.object(sys, 'argv', fake_argv), \
                 patch('builtins.input', side_effect=AssertionError(
                     "--secrets-dir angegeben - darf nicht interaktiv nachfragen"
                 )):
                exit_code = rapidmapping_processor.main()

            # Credentials-Datei fehlt weiterhin (nur der Ordner wurde angelegt) ->
            # main() bricht sauber ab, aber ohne je input() aufzurufen und ohne
            # den interaktiven 'secrets'-Prompt zu bemuehen.
            self.assertEqual(exit_code, 1)
        finally:
            os.chdir(self._tmp_root)
            shutil.rmtree(other_root, ignore_errors=True)


# ============================================================
#  util_publish_stac_fsdi.publish_to_stac -> dynamische Multipart-Part-Groesse
#  Fixe DEFAULT_PART_SIZE (250 MB) x MAX_PARTS_NUMBER (100) deckelt Assets bei
#  ~24.4 GB. Die Part-Groesse muss ab da mitwachsen, sonst lehnt die STAC-API
#  den Upload ab. Fuer normal grosse Assets darf sich nichts aendern.
# ============================================================
class TestPublishToStacPartSize(unittest.TestCase):

    def _run_publish_with_size(self, size_bytes: int):
        tmp_dir = tempfile.mkdtemp()
        try:
            asset_path = Path(tmp_dir) / "2025-09-03t120000_report.txt"
            asset_path.write_text("x")  # Inhalt irrelevant, Groesse wird gemockt

            captured = {}

            def _fake_multipart_upload(*args, **kwargs):
                captured['part_size_mb'] = kwargs.get('part_size_mb')
                return True

            with patch.object(util_publish_stac_fsdi, "is_existing", return_value=False), \
                 patch.object(util_publish_stac_fsdi, "create_asset", return_value=True), \
                 patch.object(main_multipart_upload_via_api, "multipart_upload",
                               side_effect=_fake_multipart_upload), \
                 patch("os.path.getsize", return_value=size_bytes):
                success = util_publish_stac_fsdi.publish_to_stac(
                    username="u", password="p", asset=str(asset_path),
                    item_name="2025-09-03t120000", collection="coll",
                    geocat_id="geocat", stac_hostname="sys-data.int.bgdi.ch",
                )

            self.assertTrue(success)
            return captured['part_size_mb']
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_normal_grosses_asset_behaelt_default_part_size(self):
        part_size = self._run_publish_with_size(1 * 1024 * 1024)  # 1 MB
        self.assertEqual(part_size, main_multipart_upload_via_api.DEFAULT_PART_SIZE)

    def test_riesiges_asset_bekommt_groessere_part_size_unter_dem_api_limit(self):
        size_mb = 27000  # ~26.4 GiB - ueber der ~24.4GB-Grenze fixer 250MB-Parts
        part_size = self._run_publish_with_size(size_mb * 1024 * 1024)
        self.assertEqual(part_size, 300)  # ceil(27000 / 90) = 300
        self.assertLessEqual(
            math.ceil(size_mb / part_size), main_multipart_upload_via_api.MAX_PARTS_NUMBER,
            "Anzahl Parts muss unter dem API-Limit bleiben"
        )


# ============================================================
#  proxy_handler._apply_no_proxy
# ============================================================
class TestApplyNoProxy(unittest.TestCase):
    DEFAULTS = proxy_handler.DEFAULT_PROXY_CONFIG['no_proxy']

    def test_ohne_bestehende_werte_werden_defaults_gesetzt(self):
        with patch.dict(os.environ, {}, clear=True):
            proxy_handler._apply_no_proxy(self.DEFAULTS)
            self.assertEqual(os.environ['NO_PROXY'], "localhost,127.0.0.1,.admin.ch,.bgdi.ch")
            self.assertEqual(os.environ['no_proxy'], os.environ['NO_PROXY'])

    def test_bestehende_benutzerwerte_bleiben_ohne_duplikate(self):
        with patch.dict(os.environ, {'NO_PROXY': 'intern.local, .admin.ch'}, clear=True):
            proxy_handler._apply_no_proxy(self.DEFAULTS)
            self.assertEqual(
                os.environ['NO_PROXY'],
                "intern.local,.admin.ch,localhost,127.0.0.1,.bgdi.ch"
            )

    def test_leere_liste_aendert_nichts(self):
        with patch.dict(os.environ, {}, clear=True):
            proxy_handler._apply_no_proxy([])
            self.assertNotIn('NO_PROXY', os.environ)
            self.assertNotIn('no_proxy', os.environ)

    def test_kommagetrennter_string_aus_config_wird_akzeptiert(self):
        with patch.dict(os.environ, {}, clear=True):
            proxy_handler._apply_no_proxy(".admin.ch, .bgdi.ch")
            self.assertEqual(os.environ['NO_PROXY'], ".admin.ch,.bgdi.ch")


# ============================================================
#  proxy_handler._install_kerberos_tunnel_patch
# ============================================================
class TestKerberosTunnelPatch(unittest.TestCase):
    """Der Kerberos-Token muss im CONNECT-Request beim Proxy ankommen, auch
    wenn urllib3 eine eigene _tunnel-Methode mitbringt (Python < 3.11.9).
    Lokaler Fake-Proxy auf 127.0.0.1, kein Internet nötig."""

    def test_connect_enthaelt_negotiate_token(self):
        import socket
        import threading
        import types
        import requests

        received = []
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def fake_proxy():
            conn, _ = server.accept()
            received.append(conn.recv(65536).decode("latin-1"))
            conn.sendall(b"HTTP/1.1 407 Proxy authentication required\r\n\r\n")
            conn.close()

        thread = threading.Thread(target=fake_proxy, daemon=True)
        thread.start()

        fake_spnego = types.ModuleType("spnego")
        fake_spnego.client = lambda **kw: types.SimpleNamespace(step=lambda: b"testtoken")
        try:
            with patch.dict(sys.modules, {"spnego": fake_spnego}):
                proxy_handler._install_kerberos_tunnel_patch()
                session = requests.Session()
                # System-Proxy der Maschine ignorieren (z.B. Bundesnetz): sonst
                # überschreibt requests session.proxies mit dem Windows-Proxy.
                session.trust_env = False
                session.proxies = {"https": f"http://127.0.0.1:{port}"}
                with self.assertRaises(requests.exceptions.ProxyError):
                    session.get("https://sys-data.int.bgdi.ch/", timeout=5)
            thread.join(timeout=5)
        finally:
            server.close()

        self.assertTrue(received, "Fake-Proxy hat keinen CONNECT erhalten")
        self.assertIn("Proxy-Authorization: Negotiate dGVzdHRva2Vu", received[0])


# ============================================================
#  configuration.suggest_dmc4_timestamp  (Issue #24)
#  DMC4-Zeitstempel aus den Streifen-Dateinamen: MMDD_hhmm_Linie_..._RGBN.tif
#  (Jahr aus Systemzeit) bzw. Linie_hhmmss.tif (Datum muss angegeben werden).
# ============================================================
class TestSuggestDmc4Timestamp(unittest.TestCase):

    FILES = [
        "0312_1245_041_41216_RGBN.tif",
        "0312_1234_052_41216_RGBN.tif",   # frühester Streifen (nicht die tiefste Liniennummer)
        "0312_1240_001_41216_RGBN.tif",
    ]
    TODAY = date(2026, 5, 1)

    def test_fruehester_streifen_und_jahr_aus_systemzeit(self):
        ts, info = configuration.suggest_dmc4_timestamp(self.FILES, today=self.TODAY)
        self.assertEqual(ts, "2026-03-12t12340000")
        self.assertIn("0312_1234_052_41216_RGBN.tif", info)

    def test_ergebnis_ist_gueltiger_zeitstempel(self):
        ts, _ = configuration.suggest_dmc4_timestamp(self.FILES, today=self.TODAY)
        self.assertTrue(configuration.validate_timestamp(ts))

    def test_flug_im_dezember_verarbeitung_im_januar_nimmt_vorjahr(self):
        ts, _ = configuration.suggest_dmc4_timestamp(
            ["1212_0900_001_41216_RGBN.tif"], today=date(2027, 1, 3))
        self.assertEqual(ts, "2026-12-12t09000000")

    def test_explizites_jahr_hat_vorrang(self):
        ts, _ = configuration.suggest_dmc4_timestamp(
            self.FILES, date="2025-03-12", today=self.TODAY)
        self.assertEqual(ts, "2025-03-12t12340000")

    def test_datum_mm_dd_filtert_streifen_dieses_tages(self):
        files = self.FILES + ["0313_0800_001_41216_RGBN.tif"]
        ts, _ = configuration.suggest_dmc4_timestamp(files, date="03-13", today=self.TODAY)
        self.assertEqual(ts, "2026-03-13t08000000")

    def test_datum_ohne_passende_streifen_gibt_none_mit_erklaerung(self):
        ts, info = configuration.suggest_dmc4_timestamp(self.FILES, date="03-20", today=self.TODAY)
        self.assertIsNone(ts)
        self.assertIn("03-20", info)

    def test_format_linie_hhmmss_braucht_datum(self):
        files = ["041_091636.tif", "042_091000.tif"]
        ts, info = configuration.suggest_dmc4_timestamp(files, today=self.TODAY)
        self.assertIsNone(ts)
        self.assertIn("Datum", info)

        ts, _ = configuration.suggest_dmc4_timestamp(files, date="2026-03-12", today=self.TODAY)
        self.assertEqual(ts, "2026-03-12t09100000")  # früheste Uhrzeit, nicht tiefste Linie

    def test_kein_passender_dateiname_gibt_none_kein_heutiges_datum(self):
        ts, info = configuration.suggest_dmc4_timestamp(["foo.tif", "bar.tif"], today=self.TODAY)
        self.assertIsNone(ts)
        self.assertIn("Zeitstempel", info)

    def test_ungueltiges_datum_im_dateinamen_gibt_none(self):
        ts, _ = configuration.suggest_dmc4_timestamp(["0231_1200_001_41216_RGBN.tif"], today=self.TODAY)
        self.assertIsNone(ts)

    def test_unlesbares_datum_argument_gibt_none(self):
        ts, info = configuration.suggest_dmc4_timestamp(self.FILES, date="12.03.", today=self.TODAY)
        self.assertIsNone(ts)
        self.assertIn("MM-DD", info)


# ============================================================
#  rapidmapping_processor.get_dmc4_timestamp / main() mit DMC4 ohne --timestamp
# ============================================================
class TestDmc4TimestampInProcessor(unittest.TestCase):

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmp_root = tempfile.mkdtemp()
        os.chdir(self._tmp_root)
        self.input_dir = Path(self._tmp_root) / "dmc4"
        self.input_dir.mkdir()
        for name in ("0312_1234_052_41216_RGBN.tif", "0312_1240_001_41216_RGBN.tif"):
            (self.input_dir / name).write_bytes(b"")

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_cli_ohne_timestamp_nimmt_zeit_aus_dateinamen(self):
        ts = rapidmapping_processor.get_dmc4_timestamp(self.input_dir, None, interactive=False)
        self.assertRegex(ts, r"^\d{4}-03-12t12340000$")

    def test_cli_mit_datum_ergaenzt_uhrzeit_aus_dateinamen(self):
        ts = rapidmapping_processor.get_dmc4_timestamp(self.input_dir, "2025-03-12", interactive=False)
        self.assertEqual(ts, "2025-03-12t12340000")

    def test_cli_voller_zeitstempel_wird_unveraendert_verwendet(self):
        ts = rapidmapping_processor.get_dmc4_timestamp(
            self.input_dir, "2024-07-15t143000", interactive=False)
        self.assertEqual(ts, "2024-07-15t143000")

    def test_cli_ohne_passende_dateinamen_gibt_none_ohne_nachfrage(self):
        empty = Path(self._tmp_root) / "other"
        empty.mkdir()
        (empty / "irgendwas.tif").write_bytes(b"")
        with patch("builtins.input", side_effect=AssertionError("CLI darf nicht nachfragen")):
            ts = rapidmapping_processor.get_dmc4_timestamp(empty, None, interactive=False)
        self.assertIsNone(ts)

    def test_dialog_enter_uebernimmt_vorschlag(self):
        with patch("builtins.input", return_value=""):
            ts = rapidmapping_processor.get_dmc4_timestamp(self.input_dir, None, interactive=True)
        self.assertRegex(ts, r"^\d{4}-03-12t12340000$")

    def test_dialog_eingabe_ueberschreibt_vorschlag(self):
        with patch("builtins.input", return_value="2024-07-15t143000"):
            ts = rapidmapping_processor.get_dmc4_timestamp(self.input_dir, None, interactive=True)
        self.assertEqual(ts, "2024-07-15t143000")

    def test_main_dmc4_ohne_timestamp_laeuft_ohne_nachfrage_durch(self):
        fake_argv = ['rapidmapping_processor.py', '--product', 'qdop-dmc4',
                     '--input', str(self.input_dir), '--upload=False']
        with patch.object(sys, 'argv', fake_argv), \
             patch('builtins.input', side_effect=AssertionError("kein Dialog erwartet")), \
             patch.object(rapidmapping_processor, 'process_dmc4_workflow', return_value=True) as mock_wf:
            exit_code = rapidmapping_processor.main()

        self.assertEqual(exit_code, 0)
        used_timestamp = mock_wf.call_args[0][1]
        self.assertRegex(used_timestamp, r"^\d{4}-03-12t12340000$")


# ============================================================
#  util_stac_delete_ram.normalize_delete_target  (Issue #30)
# ============================================================
class TestNormalizeDeleteTarget(unittest.TestCase):

    def test_item_mit_und_ohne_prefix_und_hundertstel(self):
        n = util_stac_delete_ram.normalize_delete_target
        self.assertEqual(n('item', '2017-08-25t10092400'), 'ram-2017-08-25t10092400')
        self.assertEqual(n('item', 'RAM-2017-08-25t10092400'), 'ram-2017-08-25t10092400')
        self.assertEqual(n('item', '2017-08-25t100924'), 'ram-2017-08-25t10092400')

    def test_item_ungueltig(self):
        with self.assertRaises(ValueError):
            util_stac_delete_ram.normalize_delete_target('item', '2017-13-25t10092400')

    def test_asset_normal_und_tolerante_schreibweise(self):
        n = util_stac_delete_ram.normalize_delete_target
        self.assertEqual(n('asset', 'ram-2017-08-25t10092400-ebn-photo.jpg'),
                         'ram-2017-08-25t10092400-ebn-photo.jpg')
        self.assertEqual(n('asset', '2017-08-25t10092400-ebn-photo-jpg'),
                         'ram-2017-08-25t10092400-ebn-photo.jpg')

    def test_asset_thumbnail_ohne_item_wird_abgelehnt(self):
        with self.assertRaises(ValueError):
            util_stac_delete_ram.normalize_delete_target('asset', 'thumbnail.jpg')

    def test_item_id_aus_asset_name(self):
        self.assertEqual(
            util_stac_delete_ram.item_id_from_asset_name('ram-2017-08-25t10092400-ebn-photo.jpg'),
            'ram-2017-08-25t10092400')

    def test_datum(self):
        n = util_stac_delete_ram.normalize_delete_target
        self.assertEqual(n('date', '2024-07-15'), '2024-07-15')
        for bad in ('2024-7-15', '2024-02-30', '15.07.2024'):
            with self.assertRaises(ValueError):
                n('date', bad)

    def test_leeres_ziel_und_unbekannte_variante(self):
        with self.assertRaises(ValueError):
            util_stac_delete_ram.normalize_delete_target('item', '  ')
        with self.assertRaises(ValueError):
            util_stac_delete_ram.normalize_delete_target('alles', 'x')


# ============================================================
#  util_stac_delete_ram.run_delete  (Issue #30)
#  Netzwerk komplett gemockt. Wichtig: nur "yes" gefolgt von "I agree" löscht.
# ============================================================
class TestRunDelete(unittest.TestCase):

    ITEM_ID = 'ram-2017-08-25t10092400'
    ASSET = 'ram-2017-08-25t10092400-ebn-photo.jpg'

    def _item(self, item_id=None, assets=None):
        return {'id': item_id or self.ITEM_ID,
                'assets': {k: {} for k in (assets or [self.ASSET, 'thumbnail.jpg'])}}

    def _run(self, mode, target, inputs, item=None, collection=None):
        """Führt run_delete mit gemockter STAC-API aus. Gibt (ok, mocks) zurück."""
        u = util_stac_delete_ram
        with patch.object(u, 'get_item', return_value=item) as get_item, \
             patch.object(u, 'get_collection_items', return_value=collection or []), \
             patch.object(u, 'get_item_assets',
                          side_effect=lambda b, c, i, a: ([self.ASSET, 'thumbnail.jpg'])), \
             patch.object(u, 'delete_asset', return_value=True) as del_asset, \
             patch.object(u, 'delete_item', return_value=True) as del_item, \
             patch('builtins.input', side_effect=inputs) as mock_input:
            ok = u.run_delete(mode, target, 'INT', 'sys-data.int.bgdi.ch', ('u', 'p'))
        return ok, {'get_item': get_item, 'delete_asset': del_asset,
                    'delete_item': del_item, 'input': mock_input}

    def test_asset_loeschen_mit_yes_und_i_agree(self):
        ok, m = self._run('asset', self.ASSET, ['yes', 'I agree'], item=self._item())
        self.assertTrue(ok)
        m['delete_asset'].assert_called_once()
        self.assertEqual(m['delete_asset'].call_args[0][2:4], (self.ITEM_ID, self.ASSET))
        m['delete_item'].assert_not_called()   # das Item selbst bleibt bestehen

    def test_item_loeschen_entfernt_alle_assets_und_dann_das_item(self):
        ok, m = self._run('item', '2017-08-25t10092400', ['yes', 'I agree'], item=self._item())
        self.assertTrue(ok)
        self.assertEqual(m['delete_asset'].call_count, 2)
        m['delete_item'].assert_called_once()

    def test_datum_loescht_nur_ram_items_dieses_tages(self):
        collection = [
            self._item('ram-2024-07-15t10000000'),
            self._item('ram-2024-07-15t23595900'),
            self._item('ram-2024-07-16t10000000'),            # anderer Tag
            self._item('anderes-item-2024-07-15t10000000'),   # kein RAM-Item
        ]
        ok, m = self._run('date', '2024-07-15', ['yes', 'I agree'], collection=collection)
        self.assertTrue(ok)
        deleted = [c[0][2] for c in m['delete_item'].call_args_list]
        self.assertEqual(deleted, ['ram-2024-07-15t10000000', 'ram-2024-07-15t23595900'])

    def test_falsche_erste_bestaetigung_loescht_nichts(self):
        for first in ('', 'ja', 'y', 'I agree', 'no'):
            ok, m = self._run('item', self.ITEM_ID, [first, 'I agree'], item=self._item())
            self.assertFalse(ok, first)
            m['delete_asset'].assert_not_called()
            m['delete_item'].assert_not_called()

    def test_falsche_zweite_bestaetigung_loescht_nichts(self):
        for second in ('', 'yes', 'i agree', 'I AGREE', 'agree'):
            ok, m = self._run('item', self.ITEM_ID, ['yes', second], item=self._item())
            self.assertFalse(ok, second)
            m['delete_asset'].assert_not_called()
            m['delete_item'].assert_not_called()

    def test_ohne_terminal_eingabe_wird_nichts_geloescht(self):
        ok, m = self._run('item', self.ITEM_ID, EOFError(), item=self._item())
        self.assertFalse(ok)
        m['delete_item'].assert_not_called()

    def test_nicht_vorhandenes_item_fragt_nicht_nach_und_loescht_nichts(self):
        ok, m = self._run('item', self.ITEM_ID, AssertionError("keine Nachfrage erwartet"), item=None)
        self.assertFalse(ok)
        m['delete_item'].assert_not_called()

    def test_nicht_vorhandenes_asset_fragt_nicht_nach_und_loescht_nichts(self):
        item = self._item(assets=['thumbnail.jpg'])
        ok, m = self._run('asset', self.ASSET, AssertionError("keine Nachfrage erwartet"), item=item)
        self.assertFalse(ok)
        m['delete_asset'].assert_not_called()

    def test_ungueltiges_ziel_wird_abgelehnt(self):
        ok, m = self._run('date', '15.07.2024', AssertionError("keine Nachfrage erwartet"))
        self.assertFalse(ok)
        m['delete_item'].assert_not_called()

    def test_item_wird_nicht_geloescht_wenn_ein_asset_fehlschlaegt(self):
        u = util_stac_delete_ram
        with patch.object(u, 'get_item', return_value=self._item()), \
             patch.object(u, 'get_item_assets', return_value=[self.ASSET, 'thumbnail.jpg']), \
             patch.object(u, 'delete_asset', side_effect=[True, False]), \
             patch.object(u, 'delete_item', return_value=True) as del_item, \
             patch('builtins.input', side_effect=['yes', 'I agree']):
            ok = u.run_delete('item', self.ITEM_ID, 'INT', 'sys-data.int.bgdi.ch', ('u', 'p'))
        self.assertFalse(ok)
        del_item.assert_not_called()

    def _delete_asset_mit_status(self, status_code):
        """Ruft delete_asset auf, die API antwortet mit dem gegebenen HTTP-Status."""
        u = util_stac_delete_ram
        response = MagicMock(status_code=status_code)
        with patch.object(u, 'PROXY_AVAILABLE', False), \
             patch.object(u.requests, 'delete', return_value=response):
            return u.delete_asset('https://x/api/', 'coll', self.ITEM_ID, self.ASSET, ('u', 'p'))

    def test_asset_404_gilt_als_bereits_geloescht(self):
        # Asset wurde kurz zuvor einzeln gelöscht: Item darf trotzdem gelöscht werden
        self.assertTrue(self._delete_asset_mit_status(404))

    def test_asset_anderer_fehler_gilt_weiter_als_fehlgeschlagen(self):
        for status in (401, 403, 500):
            self.assertFalse(self._delete_asset_mit_status(status), status)


# ============================================================
#  rapidmapping_processor: --delete / --target (CLI) und Startfrage (Dialog)
# ============================================================
class TestDeleteOptionInProcessor(unittest.TestCase):

    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmp_root = tempfile.mkdtemp()
        os.chdir(self._tmp_root)

    def tearDown(self):
        logging_root = __import__('logging').getLogger()
        for h in list(logging_root.handlers):
            if isinstance(h, __import__('logging').FileHandler):
                logging_root.removeHandler(h)
                h.close()
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def _main(self, extra_args, **patches):
        rp = rapidmapping_processor
        argv = ['rapidmapping_processor.py'] + extra_args
        with patch.object(sys, 'argv', argv), \
             patch.object(rp, 'prompt_secrets_dir_if_missing', return_value=True), \
             patch.object(rp, 'load_stac_credentials', return_value=('u', 'p', 'host.example')), \
             patch.object(rp, 'initialize_proxy'), \
             patch.object(rp, 'run_delete', return_value=True) as mock_delete:
            exit_code = rp.main()
        return exit_code, mock_delete

    def test_cli_delete_item_ruft_run_delete_mit_int_als_standard(self):
        code, mock_delete = self._main(['--delete', 'item', '--target', '2017-08-25t10092400'])
        self.assertEqual(code, 0)
        mock_delete.assert_called_once_with(
            'item', 'ram-2017-08-25t10092400', 'INT', 'host.example', ('u', 'p'))

    def test_cli_delete_mit_prod_flag(self):
        _, mock_delete = self._main(['--delete', 'date', '--target', '2024-07-15', '--prod'])
        self.assertEqual(mock_delete.call_args[0][2], 'PROD')

    def test_cli_delete_ohne_target_bricht_ab(self):
        code, mock_delete = self._main(['--delete', 'item'])
        self.assertEqual(code, 1)
        mock_delete.assert_not_called()

    def test_cli_delete_mit_ungueltigem_ziel_bricht_ab(self):
        code, mock_delete = self._main(['--delete', 'date', '--target', '15.07.2024'])
        self.assertEqual(code, 1)
        mock_delete.assert_not_called()

    def test_delete_nicht_kombinierbar_mit_produkt(self):
        code, mock_delete = self._main(
            ['--delete', 'item', '--target', '2017-08-25t10092400', '--product', 'ebn'])
        self.assertEqual(code, 1)
        mock_delete.assert_not_called()

    def test_target_ohne_delete_wird_abgelehnt(self):
        code, _ = self._main(['--target', '2024-07-15'])
        self.assertEqual(code, 1)

    def test_dialog_startfrage_enter_bedeutet_verarbeiten(self):
        with patch('builtins.input', return_value=''):
            self.assertEqual(rapidmapping_processor.prompt_start_action(), 'process')

    def test_dialog_startfrage_2_ist_loeschen(self):
        with patch('builtins.input', return_value='2'):
            self.assertEqual(rapidmapping_processor.prompt_start_action(), 'delete')

    def test_dialog_loeschen_fragt_variante_und_ziel_ab(self):
        # Startfrage "2" -> Umgebung (Enter = INT) -> Netzwerk (Enter = Autodetect)
        # -> Variante 2 (Item) -> Ziel
        inputs = ['2', '', '', '2', '2017-08-25t10092400']
        rp = rapidmapping_processor
        with patch.object(sys, 'argv', ['rapidmapping_processor.py']), \
             patch('builtins.input', side_effect=inputs), \
             patch.object(rp, 'get_configured_proxy_names', return_value=[]), \
             patch.object(rp, 'prompt_secrets_dir_if_missing', return_value=True), \
             patch.object(rp, 'load_stac_credentials', return_value=('u', 'p', 'host.example')), \
             patch.object(rp, 'initialize_proxy'), \
             patch.object(rp, 'run_delete', return_value=True) as mock_delete:
            code = rp.main()
        self.assertEqual(code, 0)
        mock_delete.assert_called_once_with(
            'item', 'ram-2017-08-25t10092400', 'INT', 'host.example', ('u', 'p'))

    def test_dialog_loeschen_abbruch_mit_enter_loescht_nichts(self):
        inputs = ['2', '', '', '']   # Start=Löschen, INT, Autodetect, Variante: Enter = abbrechen
        rp = rapidmapping_processor
        with patch.object(sys, 'argv', ['rapidmapping_processor.py']), \
             patch('builtins.input', side_effect=inputs), \
             patch.object(rp, 'get_configured_proxy_names', return_value=[]), \
             patch.object(rp, 'prompt_secrets_dir_if_missing', return_value=True), \
             patch.object(rp, 'load_stac_credentials', return_value=('u', 'p', 'host.example')), \
             patch.object(rp, 'initialize_proxy'), \
             patch.object(rp, 'run_delete', return_value=True) as mock_delete:
            code = rp.main()
        self.assertEqual(code, 0)
        mock_delete.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
