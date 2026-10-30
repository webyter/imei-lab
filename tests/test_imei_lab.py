import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import imei_lab as t


class LuhnTests(unittest.TestCase):
    def test_known_imei(self):
        self.assertEqual(t.check_digit("49015420323751"), 8)
        self.assertTrue(t.luhn_valid("490154203237518"))

    def test_bad_check_digit(self):
        self.assertFalse(t.luhn_valid("490154203237519"))
        self.assertFalse(t.luhn_valid("49015420323751"))
        self.assertFalse(t.luhn_valid("49015420323751x"))
        self.assertFalse(t.luhn_valid("٤90154203237518"))

    def test_check_digit_rejects_non_digits(self):
        with self.assertRaises(ValueError):
            t.check_digit("12ab")
        with self.assertRaises(ValueError):
            t.check_digit("١23")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv = Path(self.tmp.name) / "tac.csv"
        self.csv.write_text(
            "\ufeffBrand,TAC,SPECS\n"
            "APPLE,35729040,\"APPLE IPHONE 13, Apple iPhone 13, A2634, 2021\"\n"
            "SAMSUNG,35332510,\"SAMSUNG GALAXY S9\"\n"
            "badrow,,\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_db(self):
        db = t.load_db(self.csv)
        self.assertEqual(len(db), 2)
        self.assertEqual(db["35729040"][0], "APPLE")
        self.assertIn("iPhone 13", db["35729040"][1])

    def test_load_db_ignores_invalid_tac_rows(self):
        invalid = Path(self.tmp.name) / "invalid.csv"
        invalid.write_text(
            "Brand,TAC,SPECS\n"
            "APPLE,123,Short TAC\n"
            "APPLE,ABCDEFGH,Non-numeric TAC\n"
            ",35729040,Missing brand\n",
            encoding="utf-8",
        )
        self.assertEqual(t.load_db(invalid), {})

    def test_ensure_db_explicit(self):
        self.assertEqual(t.ensure_db(self.csv), self.csv)

    def test_ensure_db_env(self):
        with mock.patch.dict(os.environ, {"IMEI_LAB_DB": str(self.csv)}):
            self.assertEqual(t.ensure_db(), self.csv)

    def test_fmt(self):
        self.assertEqual(t._fmt("APPLE", "iPhone 13"), "APPLE - iPhone 13")
        self.assertEqual(t._fmt("APPLE", ""), "APPLE")

    def test_model_drops_duplicate_brand(self):
        self.assertEqual(t._fmt("APPLE", "APPLE IPHONE 13"), "APPLE - IPHONE 13")
        self.assertEqual(
            t._model("APPLE", "APPLE IPHONE 13 PRO MAX, Apple iPhone 13 Pro Max"),
            "IPHONE 13 PRO MAX, Apple iPhone 13 Pro Max",
        )
        self.assertEqual(t._model("APPLE", "IPHONE 13"), "IPHONE 13")
        self.assertEqual(t._model("", "APPLE IPHONE 13"), "APPLE IPHONE 13")


class OnlineCheckTests(unittest.TestCase):
    def test_imeiproof_found(self):
        html = (
            "<html><head><title>Apple iPhone 14 — IMEI 358426431038400 | IMEIProof</title></head>"
            "<body>Checksum Passed</body></html>"
        )
        with mock.patch.object(t, "_get", return_value=html):
            res = t.check_imeiproof("358426431038400")
        self.assertTrue(res["found"])
        self.assertEqual(res["model"], "Apple iPhone 14")
        self.assertIn("Passed", res["checksum"])

    def test_imeiproof_not_found_has_no_model(self):
        html = (
            "<html><head><title>IMEI 358426431038400 — device not found | IMEIProof</title></head>"
            "<body>device not found</body></html>"
        )
        with mock.patch.object(t, "_get", return_value=html):
            res = t.check_imeiproof("358426431038400")
        self.assertFalse(res["found"])
        self.assertIsNone(res["model"])

    def test_imei_org_404(self):
        err = urllib.error.HTTPError("https://imei.org", 404, "Not Found", {}, None)
        with mock.patch.object(t, "_get", side_effect=err):
            res = t.check_imei_org("358426431038400")
        self.assertEqual(res["status"], "NOT FOUND")


class CliTests(unittest.TestCase):
    """End-to-end runs of the command line against a temporary database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv = Path(self.tmp.name) / "tac.csv"
        self.csv.write_text(
            "Brand,TAC,SPECS\n"
            'Ericsson,52036945,"Ericsson T20e"\n'
            'APPLE,35729040,"APPLE IPHONE 13, Apple iPhone 13, A2634, 2021"\n',
            encoding="utf-8",
        )
        self.imei = "35729040213301"
        self.imei += str(t.check_digit(self.imei))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = t.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_generate_brand_is_case_insensitive(self):
        for brand in ("Ericsson", "ERICSSON", "ericsson"):
            code, out, _ = self.run_cli("generate", "--brand", brand, "--db", str(self.csv), "-n", "3")
            self.assertEqual(code, 0, brand)
            imeis = [line.split()[0] for line in out.strip().splitlines()]
            self.assertEqual(len(imeis), 3, brand)
            self.assertTrue(all(imei.startswith("52036945") for imei in imeis), brand)
            self.assertTrue(all(t.luhn_valid(imei) for imei in imeis), brand)

    def test_generate_unknown_brand(self):
        code, _, err = self.run_cli("generate", "--brand", "Nokia", "--db", str(self.csv))
        self.assertEqual(code, 1)
        self.assertIn("No TAC found", err)

    def test_generate_rejects_zero_count(self):
        code, _, err = self.run_cli("generate", "--count", "0", "--db", str(self.csv))
        self.assertEqual(code, 2)
        self.assertIn("--count", err)

    def test_lookup(self):
        code, out, _ = self.run_cli("lookup", "35729040", "--db", str(self.csv))
        self.assertEqual(code, 0)
        self.assertIn("APPLE", out)

    def test_check_brand_warning_is_case_insensitive(self):
        code, out, _ = self.run_cli("check", self.imei, "--brand", "samsung", "--db", str(self.csv))
        self.assertEqual(code, 0)
        self.assertIn("warning", out)

        code, out, _ = self.run_cli("check", self.imei, "--brand", "apple", "--db", str(self.csv))
        self.assertEqual(code, 0)
        self.assertNotIn("warning", out)

    def test_check_rejects_short_imei(self):
        code, _, err = self.run_cli("check", "12345", "--db", str(self.csv))
        self.assertEqual(code, 2)
        self.assertIn("15 digits", err)

    def test_generate_json(self):
        code, out, _ = self.run_cli("generate", "--brand", "apple", "--json", "--db", str(self.csv), "-n", "2")
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.strip().splitlines()]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["tac"], "35729040")
            self.assertEqual(row["brand"], "APPLE")
            self.assertTrue(t.luhn_valid(row["imei"]))

    def test_check_online_prints_sources(self):
        proof = {"source": "imeiproof", "model": "Apple iPhone 13", "checksum": "Checksum Passed", "found": True}
        org = {"source": "imei.org", "status": "found", "model": "iPhone 13"}
        with (
            mock.patch.object(t, "check_imeiproof", return_value=proof),
            mock.patch.object(t, "check_imei_org", return_value=org),
            mock.patch.object(t.time, "sleep"),
        ):
            code, out, _ = self.run_cli("check", self.imei, "--online", "--db", str(self.csv))
        self.assertEqual(code, 0)
        self.assertIn("imeiproof", out)
        self.assertIn("imei.org", out)


class DownloadTests(unittest.TestCase):
    """ensure_db() when no local copy of the TAC csv exists."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def response(self, payload=b'Brand,TAC,SPECS\nAPPLE,35729040,"APPLE IPHONE 13"\n'):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = payload
        return resp

    def test_downloads_when_no_local_copy(self):
        target = self.dir / "tac_full.csv"
        with (
            mock.patch.object(t, "BUNDLED_DB", self.dir / "missing.csv"),
            mock.patch.object(t, "DB_PATH", target),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(t, "MIN_DB_TACS", 1),
            mock.patch.object(t.urllib.request, "urlopen", return_value=self.response()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(t.ensure_db(), target)
        self.assertTrue(target.exists())
        self.assertIn("APPLE", target.read_text(encoding="utf-8"))

    def test_retries_before_giving_up(self):
        target = self.dir / "tac_full.csv"
        with (
            mock.patch.object(t, "BUNDLED_DB", self.dir / "missing.csv"),
            mock.patch.object(t, "DB_PATH", target),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(t, "MIN_DB_TACS", 1),
            mock.patch.object(t.urllib.request, "urlopen", side_effect=[OSError("boom"), self.response()]),
            mock.patch.object(t.time, "sleep"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(t.ensure_db(), target)
        self.assertTrue(target.exists())

    def test_raises_after_three_failures(self):
        target = self.dir / "tac_full.csv"
        with (
            mock.patch.object(t, "BUNDLED_DB", self.dir / "missing.csv"),
            mock.patch.object(t, "DB_PATH", target),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(t.urllib.request, "urlopen", side_effect=OSError("boom")),
            mock.patch.object(t.time, "sleep"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(RuntimeError):
                t.ensure_db()
        self.assertFalse(target.exists())

    def test_rejects_truncated_download(self):
        target = self.dir / "tac_full.csv"
        with (
            mock.patch.object(t, "BUNDLED_DB", self.dir / "missing.csv"),
            mock.patch.object(t, "DB_PATH", target),
            mock.patch.object(t, "MIN_DB_TACS", 2),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(t.urllib.request, "urlopen", return_value=self.response()),
            mock.patch.object(t.time, "sleep"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaisesRegex(RuntimeError, "only 1 unique TACs"):
                t.ensure_db()
        self.assertFalse(target.exists())

    def test_rejects_download_without_valid_tacs(self):
        target = self.dir / "tac_full.csv"
        response = self.response(b"Brand,TAC,SPECS\nAPPLE,123,Short TAC\n")
        with (
            mock.patch.object(t, "BUNDLED_DB", self.dir / "missing.csv"),
            mock.patch.object(t, "DB_PATH", target),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(t.urllib.request, "urlopen", return_value=response),
            mock.patch.object(t.time, "sleep"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaisesRegex(RuntimeError, "valid 8-digit"):
                t.ensure_db()
        self.assertFalse(target.exists())
        self.assertEqual(list(self.dir.glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
