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
python3 refresh_db.py          # fetch the TAC data up front

./run.sh            # web UI at http://127.0.0.1:8000
./run.sh 9000       # custom port
HOST=0.0.0.0 ./run.sh
```

The TAC database (275k rows, ~22 MB) is not committed. Render and Docker fetch
it during the build with `refresh_db.py`; on a plain checkout the first run
downloads it into `~/.cache/imei-lab/`. It is loaded into memory at startup (a
few tens of MB). A `data/tac_full.csv` is used first when it exists, so
`python3 refresh_db.py` pins a specific copy.

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

The TAC data is not committed. `refresh_db.py` writes a verified copy to
`data/tac_full.csv`, which is used first when present; its default source is
upstream:

```bash
python3 refresh_db.py            # download, verify and write data/tac_full.csv
python3 refresh_db.py --dry-run  # report only
```

It downloads to a temporary file, checks that it is loadable and contains at
least 200k valid rows and unique TACs, and only then replaces the file, so a
failed run leaves the current copy untouched. The file is git-ignored, so each
machine or deploy fetches its own.

## Install

Open the site on a phone and use "Add to Home Screen": the page ships a web app
manifest, icons and a service worker, so it opens standalone and still loads
when the network is down.

## Deploy

**Render**: create a Blueprint from `render.yaml`. The build installs the (empty)
requirements and downloads the TAC data; the service then starts with
`python3 imei_server.py --host 0.0.0.0 --port $PORT`.

**Docker**:

```bash
docker build -t imei-lab .
docker run -p 8000:8000 imei-lab
```

The image fetches and verifies the TAC data during `docker build`.

After deploying, set the `RENDER_URL` Actions secret to your public URL so
`.github/workflows/keepalive.yml` can ping `/health` every ~14 minutes.

## Data & credits

TAC data comes from [MoazEb/tac-database](https://github.com/MoazEb/tac-database)
(MIT). See `NOTICE`.

## License

MIT for the application code. See `LICENSE` and `NOTICE` for third-party data.
