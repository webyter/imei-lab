# Changelog

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
