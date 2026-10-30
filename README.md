# IMEI Lab

Generate, validate and look up IMEIs using the open TAC database. Stdlib-only
Python with a tiny web UI and a CLI.

![python](https://img.shields.io/badge/python-3.11%2B-blue)

## What it does

- Generates **Luhn-valid** IMEIs from real TACs (default: modern iPhones).
- Validates any IMEI's check digit and identifies the TAC/model offline.
- Optionally checks an IMEI online against imeiproof.com and imei.org.
- Ships a single-page web app with generate/copy, health checks and a
  self-pinger for free-tier hosting.

> Generated IMEIs are structurally valid but correspond to no real handset.
> eSIM and SIM-lock status live in carrier/device records and **cannot** be
> derived from an IMEI, so no generated number can pass a real eSIM/unlock check.

## Quick start

```bash
git clone https://github.com/webyter/imei-lab
cd imei-lab

./imei_lab.py generate --model "iPhone 15" -n 3
./imei_lab.py check 358426431038400 --online
./imei_lab.py lookup 35842643

./run.sh            # web UI at http://127.0.0.1:8000
./run.sh 9000       # custom port
HOST=0.0.0.0 ./run.sh
```

The TAC database is bundled in `data/tac_full.csv` (275k rows). If it is
missing, it is downloaded and cached in `~/.cache/imei-lab/`.

The `--brand` and `--model` filters are case-insensitive.

## Web API

| Endpoint | Description |
| --- | --- |
| `GET /` | Single-page UI |
| `GET /health` | `{status, tacs, iphones, version}` |
| `GET /api/generate?count=1..50` | Generate IMEIs |
| `GET /api/check?imei=<15 digits>&online=1` | Validate/look up |

Endpoints return `400` for invalid input, `429` when rate limited and `503`
when the iPhone pool is empty.

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

Legacy `IMEI_TOOL_DB` / `IMEI_TOOL_CACHE` are still honoured.

## Tests

```bash
python3 -m unittest discover -s tests -v
ruff check .
```

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
