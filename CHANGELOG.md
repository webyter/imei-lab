# Changelog

## 1.4.1

- `imei_server.main()` accepts an argv list again, which the port-range test
  needs; without it that test raised `TypeError` instead of asserting.
- Behind a proxy the rate-limit key is now the last `X-Forwarded-For` entry (the
  one our proxy appends) instead of the first, which a client can forge to get a
  fresh budget per request.
- `TRUST_PROXY`'s Render auto-detection treats `RENDER=0`/`false` as off.
- The clipboard fallback keeps its textarea off-screen instead of flashing it.

## 1.4.0

- Give the web app and installed PWA a light theme, including matching browser
  chrome, app metadata and icon background.
- Limit the generation selector to 1, 2 or 3 and keep the configured iPhone
  minimum strict instead of silently falling back to older models.
- Reject malformed or undersized TAC data, preserve active rate-limit buckets
  at capacity, and reject out-of-range server ports.
- Clear stale generated results and report clipboard failures; add a JavaScript
  syntax check and use unique temporary files for concurrent data refreshes.

## 1.3.1

- Fix a JavaScript syntax error that prevented the generator, copy action,
  checker and service-worker registration from running.
- Add a regression assertion for the check-form listener closure.

## 1.3.0

- The 22 MB TAC csv is no longer committed. Render and Docker fetch it during
  the build, a plain checkout fetches it on first use, and `refresh_db.py`
  writes a pinned copy to `data/tac_full.csv` (git-ignored).
- A failed database load at startup now prints a clear error instead of a
  traceback.

## 1.2.0

- `refresh_db.py` updates the bundled TAC data, verifying the download before
  replacing the file.
- The web UI generates 1, 5, 10 or 25 IMEIs at once and can check an IMEI
  offline, both of which the API already supported.
- Installable PWA: a web app manifest, icons rendered on the fly and a
  network-first service worker.

## 1.1.0

- The iPhone pool honours `IMEI_MIN_IPHONE`: models named without a generation
  number (XS, XR, SE, X) count as 0 and stay out of a filtered pool.
- `--brand` matching is case-insensitive in `generate` and `check`.
- A malformed `PORT`, `RATE_LIMIT` or `IMEI_MIN_IPHONE` falls back to its
  default instead of crashing; an empty iPhone pool answers `503`; `HOST=""` no
  longer binds every interface.
- Rate limiting can key on `X-Forwarded-For` (`TRUST_PROXY`, on by default on
  Render), so visitors behind a proxy each get their own budget.
- `/api/check?online=1` is concurrency limited (`ONLINE_CONCURRENCY`) with a
  shorter timeout (`ONLINE_TIMEOUT`) and answers `503` while saturated.
- The web UI is responsive on phones, and pinch, double-tap and ctrl-wheel zoom
  are disabled.
- The README no longer claims a generated number cannot match a real device.
- Tests cover the CLI, TAC download, pool filtering, keepalive, rate limiter,
  client IP handling and the online check paths; ruff is pinned in CI.

## 1.0.0

- Initial release: IMEI generation, validation and TAC lookup, with a CLI and a
  single-page web app.
