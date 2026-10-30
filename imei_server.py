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
import os
import random
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import imei_lab as t

# Loaded in main() so import stays fast and startup order is explicit.
DB: dict[str, tuple[str, str]] = {}
IPHONE_TACS: list[tuple[str, str, str]] = []


def _iphone_num(specs: str) -> int:
    m = re.search(r"IPHONE\s+(\d+)", specs.upper())
    return int(m.group(1)) if m else 10**6


def init_data() -> None:
    global DB, IPHONE_TACS
    DB = t.load_db(t.ensure_db())
    try:
        min_v = int(os.environ.get("IMEI_MIN_IPHONE", "13"))
    except ValueError:
        min_v = 13
    all_iphones = [(tac, b, s) for tac, (b, s) in DB.items() if b == "APPLE" and "IPHONE" in s.upper()]
    IPHONE_TACS = [x for x in all_iphones if _iphone_num(x[2]) >= min_v]
    if not IPHONE_TACS:  # never end up with an empty pool
        IPHONE_TACS = all_iphones

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b0d12">
<title>IMEI Lab</title>
<style>
  :root{
    --fg:#eef1f7; --mut:#8b93a7; --line:rgba(255,255,255,.09);
    --acc1:#5b8cff; --acc2:#8b5cf6; --ok:#34d399;
  }
  *{box-sizing:border-box;}
  html,body{height:100%;}
  body{
    margin:0; display:grid; place-items:center;
    font:16px/1.55 ui-sans-serif,system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    color:var(--fg); background:#0b0d12;
    background-image:
      radial-gradient(60rem 40rem at 15% -10%, rgba(91,140,255,.18), transparent 60%),
      radial-gradient(50rem 40rem at 110% 110%, rgba(139,92,246,.20), transparent 55%),
      radial-gradient(40rem 30rem at 50% 120%, rgba(52,211,153,.08), transparent 60%);
    padding:24px;
  }
  .app{
    width:min(480px,100%); position:relative; padding:34px 32px 26px;
    border-radius:26px; text-align:center;
    background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.025));
    border:1px solid var(--line);
    box-shadow:0 30px 80px -30px rgba(0,0,0,.8), inset 0 1px 0 rgba(255,255,255,.06);
    backdrop-filter:blur(18px) saturate(140%);
    -webkit-backdrop-filter:blur(18px) saturate(140%);
  }
  .brand{display:flex; align-items:center; justify-content:center; gap:10px; margin-bottom:4px;}
  .brand svg{width:26px; height:26px; filter:drop-shadow(0 2px 8px rgba(91,140,255,.5));}
  .brand h1{font-size:16px; font-weight:650; letter-spacing:.3px; margin:0;}
  .tag{font-size:12px; color:var(--mut); margin:0 0 26px;}

  .screen{
    position:relative; padding:26px 18px 22px; border-radius:18px;
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
    font-size:clamp(20px,6vw,29px); font-weight:600; letter-spacing:.12em;
    line-height:1.25; word-break:break-word; min-height:1.4em;
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

  .btns{display:flex; gap:12px; margin-top:26px;}
  button{
    flex:1; display:inline-flex; align-items:center; justify-content:center; gap:8px;
    padding:14px 16px; border-radius:13px; font:inherit; font-weight:600; cursor:pointer;
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

  .foot{color:var(--mut); font-size:11px; margin:20px 0 0; letter-spacing:.2px;}
  .dot{display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--ok);
    margin-right:6px; vertical-align:middle; box-shadow:0 0 8px var(--ok);}
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
    <p class="tag">Generate a valid iPhone IMEI — instant.</p>

    <section class="screen" id="screen">
      <div class="imei" id="imei">…</div>
      <div class="meta" id="meta">loading…</div>
    </section>

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

    <p class="foot"><span class="dot"></span>Valid Luhn checksum · real TAC · not a real device</p>
  </main>

<script>
const $ = s => document.querySelector(s);
let current = "";
const fmt = d => d.length === 15 ? `${d.slice(0,2)} ${d.slice(2,8)} ${d.slice(8,14)} ${d.slice(14)}` : d;
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

async function generate(){
  const screen = $('#screen'), imeiEl = $('#imei'), metaEl = $('#meta');
  screen.classList.remove('loading'); void screen.offsetWidth; screen.classList.add('loading');
  metaEl.textContent = "generating…";
  try{
    const r = await fetch('/api/generate?count=1');
    const d = await r.json();
    if(d.error){ metaEl.textContent = d.error; return; }
    const i = d.items[0];
    current = i.imei;
    imeiEl.textContent = fmt(i.imei);
    imeiEl.classList.remove('pop'); void imeiEl.offsetWidth; imeiEl.classList.add('pop');
    metaEl.textContent = i.specs.replace(/,\s*/g, ' · ');
    const c = $('#copy'); c.classList.remove('copied'); c.lastChild.textContent = " Copy";
  }catch(e){ metaEl.textContent = "error: " + e; }
}

$('#gen').onclick = generate;
$('#copy').onclick = async () => {
  if(!current) return;
  try{ await navigator.clipboard.writeText(current); }
  catch{ const ta=document.createElement('textarea'); ta.value=current; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
  const c = $('#copy'); c.classList.add('copied'); c.lastChild.textContent = " Copied";
  setTimeout(()=>{ c.classList.remove('copied'); c.lastChild.textContent = " Copy"; }, 1300);
};

generate();
</script>
</body>
</html>
"""


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
    """Fixed-window per-key limiter that also bounds memory."""

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


try:
    _RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "120"))
except ValueError:
    _RATE_LIMIT = 120
LIMITER = RateLimiter(limit=_RATE_LIMIT)


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
        out["online"] = [t.check_imeiproof(imei), t.check_imei_org(imei)]
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
            allowed, retry = LIMITER.allow(self.client_address[0])
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
            return _json(self, _generate(count))
        if u.path == "/api/check":
            online = q.get("online", ["0"])[0].lower() in ("1", "true", "on", "yes")
            result = _check(q.get("imei", [""])[0], online)
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
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = ap.parse_args()
    init_data()
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
