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
import main_multipart_upload_via_api
import util_publish_stac_fsdi
import rapidmapping_processor


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
#  aktuelle Datum als Ersatzwert bekommen (siehe HANDBUCH.md Teil 6).
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
