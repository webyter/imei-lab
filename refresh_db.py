#!/usr/bin/env python3
"""Refresh the bundled TAC database from the upstream csv.

    python3 refresh_db.py            # download, validate and replace data/tac_full.csv
    python3 refresh_db.py --dry-run  # download and report, write nothing
    python3 refresh_db.py --url URL  # use a different source csv

The download goes to a temporary file, is sanity checked, and only then replaces
the bundled copy, so a failed run leaves data/tac_full.csv untouched.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

import imei_lab as t

MIN_ROWS = t.MIN_DB_TACS


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": t.UA})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as out:
        out.write(resp.read())


def _count_rows(path: Path) -> int:
    rows = 0
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 3:
                continue
            tac = row[1].strip()
            if row[0].strip() and len(tac) == 8 and tac.isascii() and tac.isdigit():
                rows += 1
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="refresh_db", description="Refresh the bundled TAC database.")
    ap.add_argument("--url", default=t.DB_URL, help="source csv (default: the upstream TAC database)")
    ap.add_argument("--dest", default=str(t.BUNDLED_DB), help="file to replace (default: the bundled csv)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    ap.add_argument(
        "--min-rows",
        type=int,
        default=MIN_ROWS,
        help=f"minimum valid rows and unique TACs (default: {MIN_ROWS})",
    )
    args = ap.parse_args(argv)
    if args.min_rows < 1:
        ap.error("--min-rows must be at least 1")

    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{dest.name}.", suffix=".part", dir=dest.parent)
    os.close(fd)
    tmp = Path(tmp_name)

    print(f"downloading {args.url}", file=sys.stderr, flush=True)
    try:
        _download(args.url, tmp)
        os.chmod(tmp, 0o644)
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        print(f"error: download failed: {e}", file=sys.stderr)
        return 1

    try:
        rows = _count_rows(tmp)
        db = t.load_db(tmp)
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        print(f"error: that is not a usable TAC csv: {e}", file=sys.stderr)
        return 1

    iphones = sum(1 for _, (b, s) in db.items() if b.upper() == "APPLE" and "IPHONE" in s.upper())
    size = tmp.stat().st_size / 1_000_000
    print(f"{rows} rows, {len(db)} TACs, {iphones} iPhones, {size:.1f} MB")

    if rows < args.min_rows or len(db) < args.min_rows:
        tmp.unlink(missing_ok=True)
        print(
            f"error: only {rows} valid rows and {len(db)} unique TACs, expected at least {args.min_rows} of each",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        tmp.unlink(missing_ok=True)
        print("dry run: nothing written")
        return 0

    before = dest.stat().st_size / 1_000_000 if dest.exists() else 0.0
    tmp.replace(dest)
    print(f"updated {dest} ({before:.1f} MB -> {dest.stat().st_size / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
