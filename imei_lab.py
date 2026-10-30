#!/usr/bin/env python3
"""IMEI generator / validator / checker.

Offline:
  - generate Luhn-valid IMEIs from real TACs (model-filtered)
  - validate the Luhn check digit
  - look up a TAC / IMEI against the full ~272k TAC database

Online (optional):
  - identify model + checksum via imeiproof.com and imei.org

The TAC -> model data comes from the MoazEb open TAC database
(https://github.com/MoazEb/tac-database, MIT), downloaded on first use.

NOTE: generated IMEIs pass the Luhn checksum and carry a real TAC, but no
manufacturer or carrier has assigned them. Their serials are random, so a
number can rarely coincide with a real device. They do not encode eSIM or
SIM-lock status; those live in carrier/device records and cannot be derived
from an IMEI.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

__version__ = "1.3.0"

DB_URL = "https://raw.githubusercontent.com/MoazEb/tac-database/main/tac_full.csv"
CACHE_DIR = Path(
    os.environ.get("IMEI_LAB_CACHE")
    or os.environ.get("IMEI_TOOL_CACHE")
    or Path.home() / ".cache" / "imei-lab"
)
DB_PATH = CACHE_DIR / "tac_full.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


# ---------------------------------------------------------------- Luhn
def check_digit(digits: str) -> int:
    """Luhn check digit for the first 14 digits of an IMEI."""
    if not digits.isdigit():
        raise ValueError("Luhn input must be digits only")
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def luhn_valid(imei: str) -> bool:
    return imei.isdigit() and len(imei) == 15 and check_digit(imei[:14]) == int(imei[14])


# ---------------------------------------------------------------- database
BUNDLED_DB = Path(__file__).resolve().parent / "data" / "tac_full.csv"


def ensure_db(path: Path | None = None) -> Path:
    """Return a usable TAC csv, preferring a bundled/local copy, else download."""
    if path is not None and path.exists():
        return path
    env = os.environ.get("IMEI_LAB_DB") or os.environ.get("IMEI_TOOL_DB")
    if env and Path(env).exists():
        return Path(env)
    if BUNDLED_DB.exists():
        return BUNDLED_DB
    if DB_PATH.exists():
        return DB_PATH

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".part")
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            print(f"Downloading TAC database (~12 MB), attempt {attempt}/3 ...", file=sys.stderr, flush=True)
            req = urllib.request.Request(DB_URL, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as out:
                out.write(resp.read())
            tmp.replace(DB_PATH)
            return DB_PATH
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * attempt)
    raise RuntimeError(f"could not obtain TAC database: {last_err}")


def load_db(path: Path = DB_PATH) -> dict[str, tuple[str, str]]:
    """Return {tac: (brand, specs)}."""
    db: dict[str, tuple[str, str]] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 3 and row[1]:
                db.setdefault(row[1], (row[0], row[2]))
    return db


def _fmt(brand: str, specs: str) -> str:
    return f"{brand} - {specs}" if specs else brand


# ---------------------------------------------------------------- online
def _get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _titles_text(html: str) -> str:
    txt = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt)


def check_imeiproof(imei: str, timeout: int = 25) -> dict:
    try:
        html = _get(f"https://imeiproof.com/imei/{imei}", timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return {"source": "imeiproof", "error": str(e)}
    title = re.search(r"<title>([^<]*)", html, re.I)
    raw_title = title.group(1).strip() if title else ""
    text = _titles_text(html)
    found = "device not found" not in text.lower() and "device not found" not in raw_title.lower()
    model = None
    if found and raw_title:
        model = re.sub(r"\s*[—-]\s*IMEI.*", "", raw_title).replace(" | IMEIProof", "").strip() or None
    chk = re.search(r"Checksum\s+(Passed|Failed|Valid|Invalid)", text, re.I)
    return {
        "source": "imeiproof",
        "model": model,
        "checksum": chk.group(0) if chk else None,
        "found": found,
    }


def check_imei_org(imei: str, timeout: int = 25) -> dict:
    try:
        text = _titles_text(_get(f"https://imei.org/check-imei/{imei}", timeout=timeout))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"source": "imei.org", "status": "NOT FOUND"}
        return {"source": "imei.org", "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"source": "imei.org", "error": str(e)}
    if re.search(r"\bNOT FOUND\b|not found|invalid", text, re.I):
        return {"source": "imei.org", "status": "NOT FOUND"}
    m = re.search(r"(iPhone\s+[A-Za-z0-9 ]{1,15})", text, re.I)
    return {"source": "imei.org", "status": "found", "model": m.group(1).strip() if m else None}


# ---------------------------------------------------------------- commands
def _db_from_args(args):
    """Load the DB honouring an explicit --db path, else the cached/bundled one."""
    if getattr(args, "db", None):
        p = Path(args.db)
        if not p.exists():
            print(f"error: database not found: {p}", file=sys.stderr)
            return None
        return load_db(p)
    try:
        return load_db(ensure_db())
    except Exception as e:  # noqa: BLE001
        print(f"error: could not load TAC database: {e}", file=sys.stderr)
        return None


def cmd_generate(args) -> int:
    if args.count < 1:
        print("error: --count must be >= 1", file=sys.stderr)
        return 2
    if args.count > 1000:
        args.count = 1000

    db = _db_from_args(args)
    if db is None:
        return 1
    brand = args.brand.upper() if args.brand else None
    model = args.model.lower() if args.model else None

    matches = [
        (tac, b, s)
        for tac, (b, s) in db.items()
        if (brand is None or b.upper() == brand)
        and (model is None or model in s.lower())
    ]
    if not matches:
        print("No TAC found matching the filters.", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    for _ in range(args.count):
        tac, b, s = rng.choice(matches)
        serial = f"{rng.randint(0, 999_999):06d}"
        base = tac + serial
        imei = base + str(check_digit(base))
        if args.json:
            import json

            print(json.dumps({"imei": imei, "tac": tac, "brand": b, "specs": s}))
        else:
            print(f"{imei}  {_fmt(b, s)}")
    return 0


def cmd_lookup(args) -> int:
    key = re.sub(r"\D", "", args.tac)
    if len(key) >= 8:
        key = key[:8]
    db = _db_from_args(args)
    if db is None:
        return 1
    hit = db.get(key)
    if not hit:
        print(f"{key}: not in TAC database")
        return 1
    print(f"{key}: {_fmt(*hit)}")
    return 0


def cmd_check(args) -> int:
    imei = re.sub(r"\D", "", args.imei)
    if len(imei) != 15:
        print(f"error: IMEI must be 15 digits (got {len(imei)})", file=sys.stderr)
        return 2

    valid = luhn_valid(imei)
    print(f"IMEI      : {imei}")
    print(f"Luhn      : {'PASS' if valid else 'FAIL'}")
    print(f"TAC       : {imei[:8]}")
    print(f"Serial    : {imei[8:14]}")
    print(f"Check     : {imei[14]}")

    db = _db_from_args(args)
    if db is None:
        return 1
    hit = db.get(imei[:8])
    print(f"DB model  : {_fmt(*hit) if hit else '(TAC not in database)'}")

    if hit and args.brand and args.brand.upper() not in hit[0].upper():
        print(f"warning   : expected brand {args.brand!r}, DB says {hit[0]!r}")

    if args.online:
        print("Online checks:")
        for fn in (check_imeiproof, check_imei_org):
            res = fn(imei)
            if "error" in res:
                print(f"  {res['source']:10}: error: {res['error']}")
            elif res["source"] == "imeiproof":
                print(
                    f"  imeiproof : model={res.get('model')!r} "
                    f"checksum={res.get('checksum')!r} found={res.get('found')}"
                )
            else:
                extra = f" model={res.get('model')!r}" if res.get("model") else ""
                print(f"  imei.org  : {res.get('status')}{extra}")
            time.sleep(1)
    return 0 if valid else 3


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="imei_lab",
        description="Generate, validate and look up IMEIs using the open TAC database.",
        epilog="Generated IMEIs are structurally valid but not real devices; "
        "eSIM/SIM-lock status cannot be derived from an IMEI.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate Luhn-valid IMEIs")
    g.add_argument("--model", help="filter by model substring, e.g. 'iPhone 14'")
    g.add_argument("--brand", help="filter by brand, case-insensitive, e.g. Apple")
    g.add_argument("-n", "--count", type=int, default=1)
    g.add_argument("--seed", type=int, help="deterministic output")
    g.add_argument("--json", action="store_true")
    g.add_argument("--db", help="path to TAC csv (default: cached copy)")
    g.set_defaults(func=cmd_generate)

    lk = sub.add_parser("lookup", help="look up a TAC (8 digits) or IMEI")
    lk.add_argument("tac")
    lk.add_argument("--db")
    lk.set_defaults(func=cmd_lookup)

    c = sub.add_parser("check", help="validate an IMEI and identify its model")
    c.add_argument("imei")
    c.add_argument("--online", action="store_true", help="also query imeiproof.com / imei.org")
    c.add_argument("--brand", help="warn if the DB brand does not match")
    c.add_argument("--db")
    c.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
