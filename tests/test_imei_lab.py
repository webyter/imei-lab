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

    def test_check_digit_rejects_non_digits(self):
        with self.assertRaises(ValueError):
            t.check_digit("12ab")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv = Path(self.tmp.name) / "tac.csv"
        self.csv.write_text(
            "Brand,TAC,SPECS\n"
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

    def test_ensure_db_explicit(self):
        self.assertEqual(t.ensure_db(self.csv), self.csv)

    def test_ensure_db_env(self):
        with mock.patch.dict(os.environ, {"IMEI_LAB_DB": str(self.csv)}):
            self.assertEqual(t.ensure_db(), self.csv)

    def test_fmt(self):
        self.assertEqual(t._fmt("APPLE", "iPhone 13"), "APPLE - iPhone 13")
        self.assertEqual(t._fmt("APPLE", ""), "APPLE")


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


if __name__ == "__main__":
    unittest.main()
