import json
import threading
import unittest
import urllib.error
import urllib.request

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
        self.assertIn("Content-Security-Policy", headers)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

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

    def test_not_found(self):
        code, _, _ = get(self.port, "/nope")
        self.assertEqual(code, 404)

    def test_rate_limit(self):
        old = s.LIMITER
        s.LIMITER = s.RateLimiter(limit=2, window=60)
        try:
            codes = [get(self.port, "/api/generate")[0] for _ in range(3)]
            self.assertEqual(codes, [200, 200, 429])
        finally:
            s.LIMITER = old


if __name__ == "__main__":
    unittest.main()
