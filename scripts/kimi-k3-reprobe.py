#!/usr/bin/env python3
"""kimi-k3 re-probe: the decisive experiment from the 2026-09-20 debate.

Sequential, 180s ceiling, 429-aware backoff honoring Retry-After, >=30s
spacing (the provider's measured ~2 req/min free-tier limit — pacing to a
measured provider constraint, not a timer habit). Contrast probe on
moonshotai/kimi-k2.6 (expected: instant 404).

Verdict criteria:
  >=1 attempt -> 200 + non-empty choices[]  = ALIVE
  all attempts -> 410                        = DEAD
  persistent "not found for account" 404s
    while other models 200                    = ACCOUNT-GATED
  all attempts -> 180s timeout               = CAPACITY-STARVED (extend, don't declare dead)

Logs JSONL to ~/.local/share/nvidia-alive/kimi-k3-reprobe.jsonl
"""
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

API = "https://integrate.api.nvidia.com/v1/chat/completions"
KEY = os.environ.get("NVIDIA_API_KEY", "")
if not KEY:
    sys.exit("NVIDIA_API_KEY not set")

OUT = os.path.expanduser("~/.local/share/nvidia-alive/kimi-k3-reprobe.jsonl")
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def probe(model, timeout=180):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        dt = (time.monotonic() - t0) * 1000
        return ("200-alive" if data.get("choices") else "200-empty",
                dt, "")
    except urllib.error.HTTPError as e:
        dt = (time.monotonic() - t0) * 1000
        return (f"HTTP-{e.code}", dt,
                f"retry-after={e.headers.get('Retry-After')}")
    except Exception as e:  # TimeoutError, URLError, ECONNRESET...
        dt = (time.monotonic() - t0) * 1000
        return (type(e).__name__, dt, str(e)[:120])


def log(rec):
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


results = []
backoffs = [5, 10, 20, 40, 80]
for i in range(5):
    if i:
        wait = max(backoffs[i - 1] + random.uniform(0, 5), 30)
        time.sleep(wait)
    status, ms, note = probe("moonshotai/kimi-k3")
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "attempt": i + 1,
           "model": "moonshotai/kimi-k3", "status": status,
           "latency_ms": round(ms), "note": note}
    log(rec)
    results.append(rec)
    if status == "200-alive":
        break
    if status == "HTTP-429" and "retry-after=" in note:
        try:
            ra = int(note.split("retry-after=")[1])
            time.sleep(min(max(ra, 0), 300))
        except ValueError:
            pass

time.sleep(30)
status, ms, note = probe("moonshotai/kimi-k2.6", timeout=30)
log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "attempt": 1,
     "model": "moonshotai/kimi-k2.6", "status": status,
     "latency_ms": round(ms), "note": note})

alive = any(r["status"] == "200-alive" for r in results)
print("VERDICT:", "ALIVE" if alive else "NOT-ALIVE-THIS-RUN", flush=True)
