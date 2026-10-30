import contextlib
import io
import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import imei_lab as t
import imei_server as s

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(port, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"User-Agent": "test"})
    try:
        with OPENER.open(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        try:
            data = e.read()
        finally:
            e.close()
        return e.code, dict(e.headers), data


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_db, cls.old_tacs = s.DB, s.IPHONE_TACS
        cls.imei = "35729040213301"
        cls.imei += str(t.check_digit(cls.imei))
        s.DB = {"35729040": ("APPLE", "APPLE IPHONE 13, Apple iPhone 13, A2634, 2021")}
        s.IPHONE_TACS = [("35729040", "APPLE", "APPLE IPHONE 13, Apple iPhone 13, A2634, 2021")]
        cls.srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        cls.srv.daemon_threads = True
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(timeout=5)
        s.DB, s.IPHONE_TACS = cls.old_db, cls.old_tacs

    def test_index(self):
        code, headers, body = get(self.port, "/")
        self.assertEqual(code, 200)
        self.assertIn(b"IMEI Lab", body)
        self.assertIn("© 𝑺𝒕𝒆𝒗. 𝐃𝐎𝐆𝐁𝐘𝐓𝐄 🦴".encode(), body)
        self.assertIn("Content-Security-Policy", headers)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_index_is_responsive(self):
        _, _, body = get(self.port, "/")
        self.assertIn(b'name="viewport" content="width=device-width', body)
        self.assertIn(b"max-width:480px", body)
        self.assertIn(b"min-height:100dvh", body)
        self.assertIn(b"@media (max-height:560px)", body)

    def test_index_uses_light_theme(self):
        _, _, body = get(self.port, "/")
        self.assertIn(b'content="#f4f7fb"', body)
        self.assertIn(b"color-scheme:light", body)
        self.assertIn(b"background:#f4f7fb", body)

    def test_inline_script_is_valid_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed")
        script = s.PAGE.split("<script>", 1)[1].split("</script>", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.js"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_index_disables_zooming(self):
        _, _, body = get(self.port, "/")
        self.assertIn(b"maximum-scale=1", body)
        self.assertIn(b"user-scalable=no", body)
        self.assertIn(b"touch-action:pan-x pan-y", body)
        self.assertIn(b"gesturestart", body)
        self.assertIn(b"gesturechange", body)
        self.assertIn(b"e.touches.length > 1", body)

    def test_manifest(self):
        code, headers, body = get(self.port, "/manifest.webmanifest")
        data = json.loads(body)
        self.assertEqual(code, 200)
        self.assertIn("manifest+json", headers["Content-Type"])
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["theme_color"], "#f4f7fb")
        self.assertEqual(data["background_color"], "#f4f7fb")
        self.assertEqual([i["sizes"] for i in data["icons"]], ["192x192", "512x512"])

    def test_icons_are_png(self):
        for path, size in (("/icon-192.png", 192), ("/icon-512.png", 512)):
            code, headers, body = get(self.port, path)
            self.assertEqual(code, 200, path)
            self.assertEqual(headers["Content-Type"], "image/png", path)
            self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"), path)
            width, height = struct.unpack(">II", body[16:24])
            self.assertEqual((width, height), (size, size), path)

    def test_icon_is_cached(self):
        self.assertIs(s.icon(192), s.icon(192))

    def test_service_worker(self):
        code, headers, body = get(self.port, "/sw.js")
        self.assertEqual(code, 200)
        self.assertIn("javascript", headers["Content-Type"])
        self.assertIn(b"fetch", body)
        self.assertIn(b"imei-lab-2", body)

    def test_checker_listener_is_closed(self):
        _, _, body = get(self.port, "/")
        self.assertIn(
            b'catch(err){ out.className = "result bad"; out.textContent = "error: " + err; }\n});',
            body,
        )

    def test_index_has_controls(self):
        _, _, body = get(self.port, "/")
        for needle in (b'id="count"', b'id="batch"', b'id="checkForm"', b'rel="manifest"'):
            self.assertIn(needle, body)

    def test_count_selector_offers_one_to_three(self):
        _, _, body = get(self.port, "/")
        for value in (1, 2, 3):
            option = f'<option value="{value}">{value}</option>'.encode()
            self.assertIn(option, body)
        for value in (5, 10, 25):
            self.assertNotIn(f'<option value="{value}">'.encode(), body)

    def test_health(self):
        code, _, body = get(self.port, "/health")
        data = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["tacs"], 1)
        self.assertEqual(data["iphones"], 1)
        self.assertEqual(data["version"], t.__version__)

    def test_generate_default(self):
        code, _, body = get(self.port, "/api/generate")
        data = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(len(data["items"]), 1)
        self.assertTrue(t.luhn_valid(data["items"][0]["imei"]))

    def test_generate_count(self):
        code, _, body = get(self.port, "/api/generate?count=5")
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(body)["items"]), 5)

    def test_generate_rejects_bad_count(self):
        for path in ("/api/generate?count=0", "/api/generate?count=51", "/api/generate?count=abc"):
            code, _, _ = get(self.port, path)
            self.assertEqual(code, 400, path)

    def test_check_valid(self):
        code, _, body = get(self.port, f"/api/check?imei={self.imei}")
        data = json.loads(body)
        self.assertEqual(code, 200)
        self.assertTrue(data["luhn"])
        self.assertIn("APPLE", data["db_model"])

    def test_check_invalid(self):
        code, _, body = get(self.port, "/api/check?imei=123")
        self.assertEqual(code, 400)
        self.assertIn("error", json.loads(body))

    def test_generate_empty_pool_is_503(self):
        old = s.IPHONE_TACS
        s.IPHONE_TACS = []
        try:
            code, _, body = get(self.port, "/api/generate")
        finally:
            s.IPHONE_TACS = old
        self.assertEqual(code, 503)
        self.assertIn("error", json.loads(body))

    def test_check_online_uses_sources(self):
        proof = {"source": "imeiproof", "model": "Apple iPhone 13", "checksum": "Checksum Passed", "found": True}
        org = {"source": "imei.org", "status": "found", "model": "iPhone 13"}
        with (
            mock.patch.object(s.t, "check_imeiproof", return_value=proof),
            mock.patch.object(s.t, "check_imei_org", return_value=org),
        ):
            code, _, body = get(self.port, f"/api/check?imei={self.imei}&online=1")
        data = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual([r["source"] for r in data["online"]], ["imeiproof", "imei.org"])

    def test_not_found(self):
        code, _, _ = get(self.port, "/nope")
        self.assertEqual(code, 404)

    def test_check_online_returns_503_when_busy(self):
        old = s.ONLINE_SLOTS
        s.ONLINE_SLOTS = threading.BoundedSemaphore(0)
        try:
            code, _, body = get(self.port, f"/api/check?imei={self.imei}&online=1")
        finally:
            s.ONLINE_SLOTS = old
        self.assertEqual(code, 503)
        self.assertIn("busy", json.loads(body)["error"])

    def test_unknown_api_path(self):
        code, _, _ = get(self.port, "/api/nope")
        self.assertEqual(code, 404)

    def test_rate_limit(self):
        old = s.LIMITER
        s.LIMITER = s.RateLimiter(limit=2, window=60)
        try:
            codes = [get(self.port, "/api/generate")[0] for _ in range(3)]
            self.assertEqual(codes, [200, 200, 429])
        finally:
            s.LIMITER = old


class EnvIntTests(unittest.TestCase):
    def test_reads_integer(self):
        with mock.patch.dict(os.environ, {"IMEI_TEST_INT": " 9000 "}, clear=True):
            self.assertEqual(s._env_int("IMEI_TEST_INT", 8000), 9000)

    def test_falls_back_on_garbage(self):
        with mock.patch.dict(os.environ, {"IMEI_TEST_INT": "nine"}, clear=True):
            self.assertEqual(s._env_int("IMEI_TEST_INT", 8000), 8000)

    def test_falls_back_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(s._env_int("IMEI_TEST_INT", 8000), 8000)


class IPhonePoolTests(unittest.TestCase):
    ROWS = {
        "35729040": ("APPLE", "APPLE IPHONE 16, Apple iPhone 16, A3081, 2024"),
        "35729041": ("APPLE", "APPLE IPHONE 13 MINI, Apple iPhone 13 mini, A2628, 2021"),
        "35729042": ("APPLE", "APPLE IPHONE XS, Apple iPhone XS, A1920 - (US Model), 2018"),
        "35729043": ("APPLE", "APPLE IPHONE XR, Apple iPhone XR, A1984, 2018"),
        "35729044": ("APPLE", "APPLE IPHONE SE, Apple iPhone SE, A1662, 2016"),
        "35332510": ("SAMSUNG", "SAMSUNG GALAXY S9"),
    }
    ALL_IPHONES = {"35729040", "35729041", "35729042", "35729043", "35729044"}

    def setUp(self):
        self.old_db, self.old_tacs = s.DB, s.IPHONE_TACS

    def tearDown(self):
        s.DB, s.IPHONE_TACS = self.old_db, self.old_tacs

    def init_pool(self, minimum=None):
        env = {} if minimum is None else {"IMEI_MIN_IPHONE": minimum}
        with (
            mock.patch.object(s.t, "load_db", return_value=self.ROWS),
            mock.patch.object(s.t, "ensure_db", return_value=Path("unused.csv")),
            mock.patch.dict(os.environ, env, clear=True),
        ):
            s.init_data()
        return {tac for tac, _, _ in s.IPHONE_TACS}

    def test_default_pool_starts_at_iphone_13(self):
        self.assertEqual(self.init_pool(), {"35729040", "35729041"})

    def test_empty_database_is_rejected(self):
        with (
            mock.patch.object(s.t, "load_db", return_value={}),
            mock.patch.object(s.t, "ensure_db", return_value=Path("unused.csv")),
        ):
            with self.assertRaisesRegex(RuntimeError, "valid 8-digit"):
                s.init_data()

    def test_zero_includes_pre13_and_unnumbered_models(self):
        self.assertEqual(self.init_pool("0"), self.ALL_IPHONES)

    def test_empty_when_no_models_meet_minimum(self):
        self.assertEqual(self.init_pool("17"), set())

    def test_iphone_num(self):
        self.assertEqual(s._iphone_num("APPLE IPHONE XS, Apple iPhone XS, A1920"), 0)
        self.assertEqual(s._iphone_num("APPLE IPHONE 15 PRO MAX, Apple iPhone 15 Pro Max"), 15)
        self.assertEqual(s._iphone_num("APPLE IPHONE AIR, Apple iPhone 16 Pro, A3516, 2025"), 16)
        self.assertEqual(s._iphone_num("SAMSUNG GALAXY S9"), 0)


class KeepaliveTests(unittest.TestCase):
    def start(self, env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            with (
                mock.patch.object(s.threading, "Thread") as thread,
                contextlib.redirect_stdout(out),
            ):
                s.start_keepalive()
        return thread, out.getvalue()

    def test_without_url_starts_nothing(self):
        thread, _ = self.start({})
        thread.assert_not_called()

    def test_disabled_by_flag(self):
        thread, _ = self.start({"KEEPALIVE_URL": "https://example.com", "KEEPALIVE": "0"})
        thread.assert_not_called()

    def test_pings_health_and_clamps_interval(self):
        thread, out = self.start({"KEEPALIVE_URL": "https://example.com/", "KEEPALIVE_INTERVAL": "5"})
        thread.assert_called_once()
        self.assertIn("https://example.com/health", out)
        self.assertIn("every 60s", out)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_allows_up_to_limit_then_blocks(self):
        clock = FakeClock()
        with mock.patch.object(s.time, "monotonic", clock):
            limiter = s.RateLimiter(limit=2, window=60)
            self.assertEqual(limiter.allow("1.2.3.4"), (True, 0))
            self.assertEqual(limiter.allow("1.2.3.4"), (True, 0))
            allowed, retry = limiter.allow("1.2.3.4")
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)
        self.assertLessEqual(retry, 60)

    def test_window_slides(self):
        clock = FakeClock()
        with mock.patch.object(s.time, "monotonic", clock):
            limiter = s.RateLimiter(limit=1, window=60)
            self.assertTrue(limiter.allow("k")[0])
            self.assertFalse(limiter.allow("k")[0])
            clock.advance(61)
            self.assertTrue(limiter.allow("k")[0])

    def test_keys_are_independent(self):
        clock = FakeClock()
        with mock.patch.object(s.time, "monotonic", clock):
            limiter = s.RateLimiter(limit=1, window=60)
            self.assertTrue(limiter.allow("a")[0])
            self.assertTrue(limiter.allow("b")[0])

    def test_tracked_keys_are_bounded(self):
        clock = FakeClock()
        with mock.patch.object(s.time, "monotonic", clock):
            limiter = s.RateLimiter(limit=5, window=60, max_keys=3)
            for key in ("a", "b", "c"):
                limiter.allow(key)
            clock.advance(120)  # every bucket is now stale
            limiter.allow("d")
            self.assertEqual(list(limiter._buckets), ["d"])

    def test_full_key_table_does_not_reset_active_limits(self):
        clock = FakeClock()
        with mock.patch.object(s.time, "monotonic", clock):
            limiter = s.RateLimiter(limit=1, window=60, max_keys=2)
            self.assertTrue(limiter.allow("a")[0])
            self.assertTrue(limiter.allow("b")[0])
            self.assertFalse(limiter.allow("c")[0])
            self.assertFalse(limiter.allow("a")[0])
            self.assertEqual(set(limiter._buckets), {"a", "b"})


class ServerConfigTests(unittest.TestCase):
    def test_main_rejects_out_of_range_ports(self):
        for port in ("-1", "65536"):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    s.main(["--port", port])
            self.assertEqual(error.exception.code, 2)


class EnvFlagTests(unittest.TestCase):
    def test_truthy(self):
        for raw in ("1", "true", "YES", " on "):
            with mock.patch.dict(os.environ, {"IMEI_TEST_FLAG": raw}, clear=True):
                self.assertTrue(s._env_flag("IMEI_TEST_FLAG"), raw)

    def test_falsey_and_default(self):
        for raw in ("0", "false", "no", "off", ""):
            with mock.patch.dict(os.environ, {"IMEI_TEST_FLAG": raw}, clear=True):
                self.assertFalse(s._env_flag("IMEI_TEST_FLAG"), raw)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(s._env_flag("IMEI_TEST_FLAG", default=True))


class ClientIpTests(unittest.TestCase):
    def handler(self, peer="1.2.3.4", forwarded=None):
        h = mock.MagicMock()
        h.client_address = (peer, 1234)
        h.headers = {"X-Forwarded-For": forwarded} if forwarded is not None else {}
        return h

    def test_uses_peer_by_default(self):
        with mock.patch.object(s, "TRUST_PROXY", False):
            self.assertEqual(s._client_ip(self.handler(forwarded="9.9.9.9")), "1.2.3.4")

    def test_uses_forwarded_for_behind_proxy(self):
        with mock.patch.object(s, "TRUST_PROXY", True):
            self.assertEqual(s._client_ip(self.handler(forwarded="10.0.0.1")), "10.0.0.1")

    def test_ignores_client_supplied_forwarded_entries(self):
        with mock.patch.object(s, "TRUST_PROXY", True):
            self.assertEqual(s._client_ip(self.handler(forwarded="9.9.9.9, 10.0.0.1")), "10.0.0.1")

    def test_ignores_empty_forwarded_header(self):
        with mock.patch.object(s, "TRUST_PROXY", True):
            self.assertEqual(s._client_ip(self.handler(forwarded=" , ")), "1.2.3.4")


if __name__ == "__main__":
    unittest.main()
