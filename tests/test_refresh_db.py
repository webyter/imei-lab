import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import refresh_db as r

CSV = (
    b'Brand,TAC,SPECS\n'
    b'APPLE,35729040,"APPLE IPHONE 13, Apple iPhone 13, A2634, 2021"\n'
    b'SAMSUNG,35332510,"SAMSUNG GALAXY S9"\n'
)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name) / "tac_full.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def response(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = CSV
        return resp

    def run_refresh(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(r.urllib.request, "urlopen", return_value=self.response()),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = r.main(["--dest", str(self.dest), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_writes_valid_csv(self):
        code, out, _ = self.run_refresh("--min-rows", "1")
        self.assertEqual(code, 0)
        self.assertTrue(self.dest.exists())
        self.assertIn("2 TACs", out)
        self.assertIn("APPLE", self.dest.read_text(encoding="utf-8"))

    def test_minimum_must_be_positive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                r.main(["--dest", str(self.dest), "--min-rows", "0"])
        self.assertFalse(self.dest.exists())

    def test_rejects_short_file(self):
        code, _, err = self.run_refresh("--min-rows", "10")
        self.assertEqual(code, 1)
        self.assertFalse(self.dest.exists())
        self.assertIn("at least", err)

    def test_dry_run_writes_nothing(self):
        code, out, _ = self.run_refresh("--min-rows", "1", "--dry-run")
        self.assertEqual(code, 0)
        self.assertFalse(self.dest.exists())
        self.assertIn("dry run", out)

    def test_download_failure(self):
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(r.urllib.request, "urlopen", side_effect=OSError("down")),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = r.main(["--dest", str(self.dest)])
        self.assertEqual(code, 1)
        self.assertIn("download failed", err.getvalue())
        self.assertFalse(self.dest.exists())

    def test_rejects_duplicate_only_dataset(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = (
            b"Brand,TAC,SPECS\n"
            b"APPLE,35729040,Model A\n"
            b"APPLE,35729040,Model B\n"
        )
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(r.urllib.request, "urlopen", return_value=response),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = r.main(["--dest", str(self.dest), "--min-rows", "2"])
        self.assertEqual(code, 1)
        self.assertIn("1 unique TACs", err.getvalue())
        self.assertFalse(self.dest.exists())

    def test_count_rows_ignores_invalid_tacs(self):
        invalid = Path(self.tmp.name) / "invalid.csv"
        invalid.write_text(
            "Brand,TAC,SPECS\n"
            "APPLE,123,Short TAC\n"
            "APPLE,ABCDEFGH,Non-numeric TAC\n"
            ",35729040,Missing brand\n",
            encoding="utf-8",
        )
        self.assertEqual(r._count_rows(invalid), 0)


if __name__ == "__main__":
    unittest.main()
