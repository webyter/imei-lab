# IMEI Lab

Generate, validate and look up IMEIs using the open TAC database. Stdlib-only
Python with a tiny web UI and a CLI.

![python](https://img.shields.io/badge/python-3.11%2B-blue)

## What it does

- Generates **Luhn-valid** IMEIs from real TACs (default: modern iPhones).
- Validates any IMEI's check digit and identifies the TAC/model offline.
- Optionally checks an IMEI online against imeiproof.com and imei.org.
- Ships a single-page web app with generate/copy, batch output, an offline
  checker, health checks and a self-pinger for free-tier hosting.

> Generated IMEIs pass the Luhn checksum and carry a real TAC, but no
> manufacturer or carrier has assigned them. Serials are random, so a generated
> number can rarely coincide with a real device (about one in a million).
>
> eSIM and SIM-lock status live in carrier/device records and **cannot** be
> derived from an IMEI, so no generated number can pass a real eSIM/unlock check.

## Intended use

IMEI Lab is for testing and research: sample numbers for UI fixtures and
integration tests, offline validation, and TAC lookups. Generated numbers are
not registered to any handset and must not be used to impersonate a device,
defraud a carrier, or get past unlock or eSIM checks.

## Quick start

```bash
git clone https://github.com/webyter/imei-lab
cd imei-lab

./imei_lab.py generate --model "iPhone 15" -n 3
./imei_lab.py check 358426431038400 --online
./imei_lab.py lookup 35842643
python3 refresh_db.py          # refresh the bundled TAC data

./run.sh            # web UI at http://127.0.0.1:8000
./run.sh 9000       # custom port
HOST=0.0.0.0 ./run.sh
```

The TAC database is bundled in `data/tac_full.csv` (275k rows, ~22 MB) and
loaded into memory at startup (a few tens of MB). If it is missing, it is
downloaded and cached in `~/.cache/imei-lab/`.

The `--brand` and `--model` filters are case-insensitive.

## Web API

| Endpoint | Description |
| --- | --- |
| `GET /` | Single-page UI |
| `GET /health` | `{status, tacs, iphones, version}` |
| `GET /api/generate?count=1..50` | Generate IMEIs |
| `GET /api/check?imei=<15 digits>&online=1` | Validate/look up |
| `GET /manifest.webmanifest` | Web app manifest |
| `GET /sw.js` | Service worker (network-first cache) |
| `GET /icon-192.png`, `/icon-512.png` | App icons |

Endpoints return `400` for invalid input, `429` when rate limited and `503`
when the iPhone pool is empty. `/api/check?...&online=1` makes live requests to
imeiproof.com and imei.org, so it is concurrency limited and answers `503` with
`Retry-After` while every slot is busy.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address |
| `IMEI_LAB_DB` | bundled DB | Path to a TAC csv |
| `IMEI_LAB_CACHE` | `~/.cache/imei-lab` | Download cache |
| `IMEI_MIN_IPHONE` | `13` | Minimum iPhone generation in the web pool (`0` = all; models named without a number, e.g. XS, XR, SE, count as `0`) |
| `RATE_LIMIT` | `120` | Requests per IP per 60s on `/api/*` |
| `KEEPALIVE` / `KEEPALIVE_URL` | off / `RENDER_EXTERNAL_URL` | Self-ping |
| `KEEPALIVE_INTERVAL` | `600` | Seconds between self-pings |
| `TRUST_PROXY` | `1` on Render | Take the client IP from `X-Forwarded-For`, so limiting is per visitor behind a proxy |
| `ONLINE_CONCURRENCY` | `4` | Concurrent `/api/check?online=1` lookups before it answers `503` |
| `ONLINE_TIMEOUT` | `10` | Timeout in seconds for those lookups |

Legacy `IMEI_TOOL_DB` / `IMEI_TOOL_CACHE` are still honoured.

## Tests

```bash
python3 -m unittest discover -s tests -v
ruff check .
```

## Data freshness

`data/tac_full.csv` is a snapshot. To bring it up to date from upstream:

```bash
python3 refresh_db.py            # download, verify and replace it
python3 refresh_db.py --dry-run  # report only
```

It downloads to a temporary file, checks that it looks like a TAC database (at
least 200k rows, and loadable), and only then replaces the bundled csv, so a
failed run leaves the current copy untouched. Commit the result.

## Install

Open the site on a phone and use "Add to Home Screen": the page ships a web app
manifest, icons and a service worker, so it opens standalone and still loads
when the network is down.

## Deploy

**Render**: create a Blueprint from `render.yaml`. The service starts with
`python3 imei_server.py --host 0.0.0.0 --port $PORT`.

**Docker**:

```bash
docker build -t imei-lab .
docker run -p 8000:8000 imei-lab
```

After deploying, set the `RENDER_URL` Actions secret to your public URL so
`.github/workflows/keepalive.yml` can ping `/health` every ~14 minutes.

## Data & credits

TAC data comes from [MoazEb/tac-database](https://github.com/MoazEb/tac-database)
(MIT). See `NOTICE`.

## License

MIT for the application code. See `LICENSE` and `NOTICE` for third-party data.
