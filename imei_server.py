#!/usr/bin/env python3
"""Minimal IMEI generator web app (stdlib only).

Run:
    python3 imei_server.py            # http://127.0.0.1:8000
    python3 imei_server.py --port 9000 --host 0.0.0.0

One button: generate a valid iPhone IMEI, one button: copy it.
Generated IMEIs are structurally valid but are not real devices.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import struct
import sys
import threading
import time
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import imei_lab as t

# Loaded in main() so import stays fast and startup order is explicit.
DB: dict[str, tuple[str, str]] = {}
IPHONE_TACS: list[tuple[str, str, str]] = []

_IPHONE_GEN = re.compile(r"IPHONE\s+(\d+)")


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to default when unset or malformed."""
    try:
        return int(os.environ.get(name, "").strip())
    except ValueError:
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable (1/true/yes/on)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Render (and most PaaS) front the app with a proxy, so the peer address is the
# proxy's. Trust the forwarded header only when something says we are behind one.
TRUST_PROXY = _env_flag("TRUST_PROXY", default=bool(os.environ.get("RENDER")))


def _client_ip(handler: BaseHTTPRequestHandler) -> str:
    """Rate-limit key: the visitor's address, taken from X-Forwarded-For behind a proxy."""
    if TRUST_PROXY:
        first = handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if first:
            return first
    return handler.client_address[0]


def _iphone_num(specs: str) -> int:
    """Highest iPhone generation named in the TAC specs, 0 when there is none.

    Models named without a number (XS, XR, SE, X) carry no generation, so they
    count as 0 and stay out of a generation-filtered pool.
    """
    gens = [int(n) for n in _IPHONE_GEN.findall(specs.upper())]
    return max(gens) if gens else 0


def init_data() -> None:
    global DB, IPHONE_TACS
    DB = t.load_db(t.ensure_db())
    min_v = _env_int("IMEI_MIN_IPHONE", 13)
    all_iphones = [(tac, b, s) for tac, (b, s) in DB.items() if b.upper() == "APPLE" and "IPHONE" in s.upper()]
    IPHONE_TACS = [x for x in all_iphones if _iphone_num(x[2]) >= min_v]
    if not IPHONE_TACS:  # never end up with an empty pool
        IPHONE_TACS = all_iphones

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="theme-color" content="#0b0d12">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="IMEI Lab">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<title>IMEI Lab</title>
<style>
  :root{
    --fg:#eef1f7; --mut:#8b93a7; --line:rgba(255,255,255,.09);
    --acc1:#5b8cff; --acc2:#8b5cf6; --ok:#34d399;
  }
  *{box-sizing:border-box;}
  html{-webkit-text-size-adjust:100%; touch-action:pan-x pan-y;}
  body{
    margin:0; min-height:100vh; min-height:100dvh;
    display:flex; flex-direction:column;
    font:16px/1.55 ui-sans-serif,system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    color:var(--fg); background:#0b0d12;
    background-image:
      radial-gradient(60rem 40rem at 15% -10%, rgba(91,140,255,.18), transparent 60%),
      radial-gradient(50rem 40rem at 110% 110%, rgba(139,92,246,.20), transparent 55%),
      radial-gradient(40rem 30rem at 50% 120%, rgba(52,211,153,.08), transparent 60%);
    padding:clamp(10px,4vw,24px);
  }
  .app{
    width:100%; max-width:480px; margin:auto; position:relative;
    padding:clamp(20px,6vw,34px) clamp(16px,5.5vw,32px) clamp(16px,4.5vw,26px);
    border-radius:clamp(18px,6vw,26px); text-align:center;
    background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));
    border:1px solid var(--line);
    box-shadow:0 30px 80px -30px rgba(0,0,0,.8), inset 0 1px 0 rgba(255,255,255,.06);
    backdrop-filter:blur(18px) saturate(140%);
    -webkit-backdrop-filter:blur(18px) saturate(140%);
  }
  .brand{display:flex; align-items:center; justify-content:center; gap:10px; margin-bottom:4px;}
  .brand svg{width:26px; height:26px; filter:drop-shadow(0 2px 8px rgba(91,140,255,.5));}
  .brand h1{font-size:16px; font-weight:650; letter-spacing:.3px; margin:0;}
  .head{display:flex; align-items:center; justify-content:center; gap:10px;
    margin:0 0 clamp(12px,4vw,22px);}
  .tag{font-size:12px; color:var(--mut); margin:0;}

  .screen{
    position:relative; padding:clamp(16px,5vw,26px) clamp(10px,4vw,18px) clamp(14px,4vw,22px);
    border-radius:clamp(14px,4vw,18px);
    background:rgba(0,0,0,.28); border:1px solid var(--line);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
    overflow:hidden;
  }
  .screen::before{
    content:""; position:absolute; inset:0;
    background:linear-gradient(115deg,transparent 30%,rgba(255,255,255,.045) 50%,transparent 70%);
    transform:translateX(-100%);
  }
  .screen.loading::before{animation:sweep 1s ease;}
  @keyframes sweep{to{transform:translateX(100%);}}

  .imei{
    font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    font-size:min(5.6vw,30px); font-weight:600; letter-spacing:.05em;
    line-height:1.3; white-space:nowrap; min-height:1.3em;
    background:linear-gradient(180deg,#fff,#c9d3ea);
    -webkit-background-clip:text; background-clip:text; color:transparent;
    text-shadow:0 0 30px rgba(120,160,255,.15);
    transition:opacity .18s ease;
  }
  .imei.pop{animation:pop .28s ease;}
  @keyframes pop{0%{opacity:.15; transform:scale(.98);}100%{opacity:1; transform:scale(1);}}

  .meta{
    margin-top:14px; display:inline-block; max-width:100%;
    font-size:12.5px; color:var(--mut); padding:6px 12px; border-radius:999px;
    background:rgba(255,255,255,.045); border:1px solid var(--line);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }

  .btns{display:flex; gap:clamp(8px,2.5vw,12px); margin-top:clamp(14px,5vw,26px);}
  button{
    flex:1; min-width:0; display:inline-flex; align-items:center; justify-content:center; gap:8px;
    padding:clamp(11px,3vw,14px) clamp(8px,3vw,16px); border-radius:clamp(11px,3.5vw,13px);
    font:inherit; font-weight:600; cursor:pointer; white-space:nowrap;
    border:1px solid transparent; transition:transform .08s ease, box-shadow .2s, background .2s, opacity .2s;
  }
  button:active{transform:translateY(1px) scale(.995);}
  button svg{width:18px; height:18px;}
  .primary{
    color:#fff; background:linear-gradient(135deg,var(--acc1),var(--acc2));
    box-shadow:0 12px 30px -10px rgba(91,140,255,.7), inset 0 1px 0 rgba(255,255,255,.25);
  }
  .primary:hover{box-shadow:0 16px 38px -10px rgba(120,140,255,.85);}
  .secondary{
    color:var(--fg); background:rgba(255,255,255,.05); border-color:var(--line);
  }
  .secondary:hover{background:rgba(255,255,255,.09);}
  .secondary.copied{color:#06251b; border-color:var(--ok);
    background:var(--ok); box-shadow:0 10px 26px -12px rgba(52,211,153,.8);}
  button:disabled{opacity:.6; cursor:default;}

  .foot{color:var(--mut); font-size:11px; margin:clamp(12px,4vw,20px) 0 0; letter-spacing:.2px;}
  .dot{display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--ok);
    margin-right:6px; vertical-align:middle; box-shadow:0 0 8px var(--ok);}

  .count{
    font:inherit; font-size:12px; color:var(--mut); cursor:pointer;
    background:rgba(255,255,255,.05); border:1px solid var(--line);
    border-radius:999px; padding:2px 4px 2px 8px;
  }
  .count:focus-visible{outline:2px solid var(--acc1); outline-offset:2px;}

  .batch{list-style:none; display:flex; flex-wrap:wrap; gap:6px; justify-content:center;
    margin:12px 0 0; padding:0;}
  .batch[hidden]{display:none;}
  .batch li{
    font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; font-size:12px;
    padding:5px 9px; border-radius:8px; cursor:pointer; color:var(--fg);
    background:rgba(255,255,255,.045); border:1px solid var(--line);
  }
  .batch li.copied{color:#06251b; background:var(--ok); border-color:var(--ok);}

  .check{display:flex; gap:8px; margin-top:clamp(12px,4vw,18px);}
  .field{
    flex:1; min-width:0; font:inherit; font-size:16px; color:var(--fg);
    background:rgba(0,0,0,.28); border:1px solid var(--line); border-radius:11px;
    padding:10px 12px;
  }
  .field::placeholder{color:var(--mut);}
  .field:focus{outline:none; border-color:rgba(91,140,255,.6);}
  .ghost{
    flex:0 0 auto; padding:10px 16px; border-radius:11px; font-size:14px;
    color:var(--fg); background:rgba(255,255,255,.06); border-color:var(--line);
  }
  .ghost:hover{background:rgba(255,255,255,.1);}
  .result{margin:10px 0 0; font-size:12px; color:var(--mut); min-height:1.2em;
    overflow-wrap:anywhere;}
  .result.good{color:var(--ok);}
  .result.bad{color:#fca5a5;}

  /* Narrow phones: keep both buttons on one row. */
  @media (max-width:340px){
    button{font-size:14px; gap:6px;}
    button svg{width:16px; height:16px;}
    .brand h1{font-size:15px;}
  }

  /* Short screens (landscape phones, small windows): pack the card tighter. */
  @media (max-height:560px){
    body{padding:10px;}
    .app{padding:16px 18px 12px; border-radius:16px;}
    .brand{margin-bottom:2px;}
    .brand svg{width:22px; height:22px;}
    .tag{margin-bottom:10px;}
    .screen{padding:12px 10px 10px;}
    .btns{margin-top:10px;}
    .foot{margin-top:8px;}
  }
</style>
</head>
<body>
  <main class="app">
    <div class="brand">
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="6" y="2.5" width="12" height="19" rx="3" stroke="#8fb0ff" stroke-width="1.6"/>
        <path d="M10 5.2h4" stroke="#8fb0ff" stroke-width="1.6" stroke-linecap="round"/>
        <circle cx="12" cy="18" r="1.2" fill="#8fb0ff"/>
      </svg>
      <h1>IMEI Lab</h1>
    </div>
    <div class="head">
      <p class="tag">Generate a valid iPhone IMEI</p>
      <select id="count" class="count" aria-label="How many IMEIs">
        <option value="1">1</option>
        <option value="5">5</option>
        <option value="10">10</option>
        <option value="25">25</option>
      </select>
    </div>

    <section class="screen" id="screen">
      <div class="imei" id="imei">…</div>
      <div class="meta" id="meta">loading…</div>
    </section>

    <ul class="batch" id="batch" hidden></ul>

    <div class="btns">
      <button id="gen" class="primary">
        <svg viewBox="0 0 24 24" fill="none"><path d="M4 12a8 8 0 1 1 2.3 5.6" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/><path d="M4 17v-5h5" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Generate
      </button>
      <button id="copy" class="secondary">
        <svg viewBox="0 0 24 24" fill="none"><rect x="9" y="9" width="11" height="11" rx="2.5" stroke="currentColor" stroke-width="1.7"/><path d="M15 9V6.5A2.5 2.5 0 0 0 12.5 4h-6A2.5 2.5 0 0 0 4 6.5v6A2.5 2.5 0 0 0 6.5 15H9" stroke="currentColor" stroke-width="1.7"/></svg>
        Copy
      </button>
    </div>

    <form class="check" id="checkForm" autocomplete="off">
      <input id="checkIn" class="field" inputmode="numeric" maxlength="19" placeholder="Check an IMEI"
        aria-label="An IMEI to check" spellcheck="false">
      <button class="ghost" type="submit">Check</button>
    </form>
    <p class="result" id="result">Paste an IMEI to validate it offline.</p>

    <p class="foot"><span class="dot"></span>Valid Luhn · real TAC · may match a real device</p>
  </main>

<script>
/* Zoom is off everywhere. Safari ignores user-scalable=no and has no touch-action
   that stops pinch, so block the pinch gestures and multi-touch moves directly. */
const blockZoom = e => e.preventDefault();
['gesturestart', 'gesturechange', 'gestureend'].forEach(
  type => window.addEventListener(type, blockZoom, { passive: false, capture: true })
);
['touchstart', 'touchmove'].forEach(type =>
  window.addEventListener(type, e => { if (e.touches.length > 1) e.preventDefault(); }, { passive: false, capture: true })
);
window.addEventListener('wheel', e => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });

const $ = s => document.querySelector(s);
let current = "";

const fmt = d => d.length === 15 ? `${d.slice(0,2)} ${d.slice(2,8)} ${d.slice(8,14)} ${d.slice(14)}` : d;

async function copyText(text, el){
  try{ await navigator.clipboard.writeText(text); }
  catch{ const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
  if(el){ el.classList.add('copied'); setTimeout(()=>el.classList.remove('copied'), 900); }
}

function showCopy(copied){
  const c = $('#copy');
  c.classList.toggle('copied', copied);
  c.lastChild.textContent = copied ? " Copied" : " Copy";
}

async function generate(){
  const screen = $('#screen'), imeiEl = $('#imei'), metaEl = $('#meta'), list = $('#batch');
  const count = Number($('#count').value) || 1;
  screen.classList.remove('loading'); void screen.offsetWidth; screen.classList.add('loading');
  metaEl.textContent = "generating…";
  try{
    const r = await fetch(`/api/generate?count=${count}`);
    const d = await r.json();
    if(d.error){ metaEl.textContent = d.error; return; }
    const items = d.items;
    current = items.map(i => i.imei).join("\n");
    imeiEl.textContent = fmt(items[0].imei);
    imeiEl.classList.remove('pop'); void imeiEl.offsetWidth; imeiEl.classList.add('pop');
    metaEl.textContent = items[0].specs.replace(/,\s*/g, ' · ');
    list.textContent = "";
    items.slice(1).forEach(i => {
      const li = document.createElement('li');
      li.textContent = fmt(i.imei);
      li.title = i.specs;
      li.addEventListener('click', () => copyText(i.imei, li));
      list.appendChild(li);
    });
    list.hidden = list.children.length === 0;
    showCopy(false);
  }catch(e){ metaEl.textContent = "error: " + e; }
}

$('#gen').onclick = generate;
$('#copy').onclick = async () => {
  if(!current) return;
  await copyText(current, null);
  showCopy(true);
  setTimeout(()=>showCopy(false), 1300);
};

$('#checkForm').addEventListener('submit', async e => {
  e.preventDefault();
  const out = $('#result');
  const imei = $('#checkIn').value.replace(/\D/g, "");
  if(imei.length !== 15){ out.className = "result bad"; out.textContent = "An IMEI is 15 digits."; return; }
  out.className = "result"; out.textContent = "checking…";
  try{
    const d = await (await fetch(`/api/check?imei=${imei}`)).json();
    if(d.error){ out.className = "result bad"; out.textContent = d.error; return; }
    out.className = "result " + (d.luhn ? "good" : "bad");
    out.textContent = `${d.luhn ? "Valid" : "Bad check digit"} · ${d.db_model}`;
  }catch(err){ out.className = "result bad"; out.textContent = "error: " + err; }
};

if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});

generate();
</script>
</body>
</html>
"""


MANIFEST = {
    "name": "IMEI Lab",
    "short_name": "IMEI Lab",
    "description": "Generate and check Luhn-valid IMEIs from the open TAC database.",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#0b0d12",
    "theme_color": "#0b0d12",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}

SERVICE_WORKER = """\
const CACHE = 'imei-lab-1';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.add('/')));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
  );
  self.clients.claim();
});

// Network first: the page stays fresh online and still opens offline.
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/health') return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
"""

ICON_SIZES = {"/icon-192.png": 192, "/icon-512.png": 512}
_ICONS: dict[int, bytes] = {}


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def make_icon(size: int) -> bytes:
    """Render the app icon: a rounded gradient tile on the page background, as a PNG."""
    bg = (0x0B, 0x0D, 0x12)
    top = (0x5B, 0x8C, 0xFF)
    bottom = (0x8B, 0x5C, 0xF6)
    inset = size * 0.16
    edge = size - 2 * inset
    radius = edge * 0.26
    centre = inset + edge / 2
    half = edge / 2
    stride = size * 4 + 1
    pixels = bytearray(stride * size)
    for y in range(size):
        row = y * stride
        along = min(1.0, max(0.0, (y - inset) / edge))
        fill = tuple(int(top[i] + (bottom[i] - top[i]) * along) for i in range(3))
        for x in range(size):
            dx = abs(x + 0.5 - centre) - (half - radius)
            dy = abs(y + 0.5 - centre) - (half - radius)
            spread = math.hypot(max(dx, 0.0), max(dy, 0.0)) + min(max(dx, dy), 0.0) - radius
            alpha = min(1.0, max(0.0, 0.5 - spread))
            at = row + 1 + x * 4
            if alpha <= 0:
                pixels[at : at + 3] = bytes(bg)
            else:
                pixels[at : at + 3] = bytes(int(bg[i] + (fill[i] - bg[i]) * alpha) for i in range(3))
            pixels[at + 3] = 0xFF
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
        + _png_chunk(b"IEND", b"")
    )


def icon(size: int) -> bytes:
    """Cached PNG bytes for one icon size."""
    if size not in _ICONS:
        _ICONS[size] = make_icon(size)
    return _ICONS[size]


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)


class RateLimiter:
    """Sliding-window per-key limiter that also bounds memory."""

    def __init__(self, limit: int = 120, window: float = 60.0, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            if len(self._buckets) >= self.max_keys:
                cutoff = now - self.window
                for k in [k for k, v in self._buckets.items() if not v or v[-1] <= cutoff]:
                    del self._buckets[k]
                if len(self._buckets) >= self.max_keys:
                    self._buckets.clear()
            bucket = self._buckets.setdefault(key, [])
            cutoff = now - self.window
            while bucket and bucket[0] <= cutoff:
                bucket.pop(0)
            if len(bucket) >= self.limit:
                return False, max(1, int(self.window - (now - bucket[0])))
            bucket.append(now)
            return True, 0


LIMITER = RateLimiter(limit=_env_int("RATE_LIMIT", 120))
# Bounds the outbound work a single visitor can pile up through ?online=1.
ONLINE_SLOTS = threading.BoundedSemaphore(max(1, _env_int("ONLINE_CONCURRENCY", 4)))


def _send(
    handler: BaseHTTPRequestHandler,
    body: bytes,
    content_type: str,
    code: int = 200,
    headers: dict[str, str] | None = None,
) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    for k, v in SECURITY_HEADERS.items():
        handler.send_header(k, v)
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _json(
    handler: BaseHTTPRequestHandler,
    obj: dict,
    code: int = 200,
    headers: dict[str, str] | None = None,
) -> None:
    _send(handler, json.dumps(obj).encode(), "application/json", code, headers)


def _html(handler: BaseHTTPRequestHandler, text: str) -> None:
    _send(handler, text.encode(), "text/html; charset=utf-8", headers={"Content-Security-Policy": CSP})


def _generate(count: int) -> dict:
    if not IPHONE_TACS:
        return {"error": "no iPhone TACs in database"}
    count = max(1, min(count, 50))
    items = []
    for _ in range(count):
        tac, brand, specs = random.choice(IPHONE_TACS)
        serial = f"{random.randint(0, 999_999):06d}"
        base = tac + serial
        items.append({"imei": base + str(t.check_digit(base)), "tac": tac, "brand": brand, "specs": specs})
    return {"items": items}


def _check(imei: str, online: bool) -> dict:
    imei = re.sub(r"\D", "", imei)
    if len(imei) != 15:
        return {"error": f"IMEI must be 15 digits (got {len(imei)})"}
    hit = DB.get(imei[:8])
    out = {
        "imei": imei,
        "luhn": t.luhn_valid(imei),
        "tac": imei[:8],
        "db_model": t._fmt(*hit) if hit else "(TAC not in database)",
    }
    if online:
        timeout = _env_int("ONLINE_TIMEOUT", 10)
        out["online"] = [
            t.check_imeiproof(imei, timeout=timeout),
            t.check_imei_org(imei, timeout=timeout),
        ]
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return _html(self, PAGE)
        if u.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if u.path == "/manifest.webmanifest":
            return _send(self, json.dumps(MANIFEST).encode(), "application/manifest+json")
        if u.path == "/sw.js":
            return _send(self, SERVICE_WORKER.encode(), "application/javascript; charset=utf-8")
        if u.path in ICON_SIZES:
            return _send(self, icon(ICON_SIZES[u.path]), "image/png")
        if u.path == "/health":
            return _json(
                self,
                {
                    "status": "ok",
                    "tacs": len(DB),
                    "iphones": len(IPHONE_TACS),
                    "version": t.__version__,
                },
            )
        if u.path.startswith("/api/"):
            allowed, retry = LIMITER.allow(_client_ip(self))
            if not allowed:
                return _json(self, {"error": "rate limit exceeded"}, 429, {"Retry-After": str(retry)})
        if u.path == "/api/generate":
            raw = q.get("count", ["1"])[0]
            try:
                count = int(raw)
            except ValueError:
                return _json(self, {"error": "count must be an integer"}, 400)
            if not 1 <= count <= 50:
                return _json(self, {"error": "count must be between 1 and 50"}, 400)
            result = _generate(count)
            return _json(self, result, 503 if "error" in result else 200)
        if u.path == "/api/check":
            online = q.get("online", ["0"])[0].lower() in ("1", "true", "on", "yes")
            if online and not ONLINE_SLOTS.acquire(blocking=False):
                return _json(self, {"error": "online checks are busy, retry shortly"}, 503, {"Retry-After": "5"})
            try:
                result = _check(q.get("imei", [""])[0], online)
            finally:
                if online:
                    ONLINE_SLOTS.release()
            return _json(self, result, 400 if "error" in result else 200)
        _json(self, {"error": "not found"}, 404)


def start_keepalive() -> None:
    """Self-ping the public URL on an interval so Render free doesn't sleep.

    Enabled automatically when Render provides RENDER_EXTERNAL_URL, or set
    KEEPALIVE_URL to any public base URL. Disable with KEEPALIVE=0.
    """
    url = os.environ.get("KEEPALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if not url or os.environ.get("KEEPALIVE", "1").lower() in ("0", "false", "no", "off"):
        return
    target = url.rstrip("/") + "/health"
    try:
        interval = max(60, int(os.environ.get("KEEPALIVE_INTERVAL", "600")))
    except ValueError:
        interval = 600

    def loop() -> None:
        time.sleep(interval)
        while True:
            try:
                req = urllib.request.Request(target, headers={"User-Agent": "imei-lab-keepalive"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    print(f"keepalive {target} -> {r.status}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"keepalive failed: {e}", flush=True)
            time.sleep(interval)

    threading.Thread(target=loop, name="keepalive", daemon=True).start()
    print(f"keepalive enabled: {target} every {interval}s", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(prog="imei_server", description="IMEI Lab generator web app")
    ap.add_argument("--version", action="version", version=f"%(prog)s {t.__version__}")
    ap.add_argument("--host", default=os.environ.get("HOST") or "127.0.0.1")
    ap.add_argument("--port", type=int, default=_env_int("PORT", 8000))
    args = ap.parse_args()
    try:
        init_data()
    except Exception as e:  # noqa: BLE001
        print(f"error: could not load the TAC database: {e}", file=sys.stderr)
        return 1
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    start_keepalive()
    print(
        f"IMEI Lab v{t.__version__} running at http://{args.host}:{args.port}  (Ctrl+C to stop)",
        flush=True,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
