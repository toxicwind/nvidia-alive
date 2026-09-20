#!/usr/bin/env python3
"""Live completion probes for every kimi model OpenRouter + NVIDIA catalogs list.
Catalogs are claims; completions are truth. Tiny max_tokens, bounded workers,
no sleeps, per-request timeouts. Keys from env only.
"""
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

K = os.environ


def probe(provider, url, headers, model, timeout=60):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 8,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers=headers,
                                 method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
            dt = time.time() - t0
            try:
                content = body["choices"][0]["message"]["content"]
            except Exception:
                content = "?"
            return {"provider": provider, "model": model, "http": r.status,
                    "ok": True, "secs": round(dt, 1),
                    "reply": str(content)[:40]}
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode())
            err = d.get("error", d)
            if isinstance(err, dict):
                etype = err.get("type", "") or err.get("code", "")
                msg = err.get("message", str(err))
            else:
                etype, msg = "", str(err)
        except Exception:
            etype, msg = "", "unparseable-body"
        return {"provider": provider, "model": model, "http": e.code,
                "ok": False, "err_type": str(etype)[:40],
                "err": str(msg)[:120]}
    except Exception as e:
        return {"provider": provider, "model": model, "http": -1,
                "ok": False, "err_type": type(e).__name__,
                "err": str(e)[:120]}


jobs = []
OR_MODELS = ["moonshotai/kimi-k3", "moonshotai/kimi-k3:batch",
             "moonshotai/kimi-k2.7-code", "~moonshotai/kimi-latest",
             "moonshotai/kimi-k2.6", "moonshotai/kimi-k2.5",
             "moonshotai/kimi-k2-thinking", "moonshotai/kimi-k2-0905",
             "moonshotai/kimi-k2"]
for keyname in ["OPENROUTER_API_KEY_1", "OPENROUTER_API_KEY"]:
    key = K.get(keyname, "")
    if not key:
        print("SKIP openrouter[%s]: key unset" % keyname)
        continue
    for m in OR_MODELS:
        jobs.append(("openrouter[%s]" % keyname,
                     "https://openrouter.ai/api/v1/chat/completions",
                     {"Authorization": "Bearer " + key,
                      "Content-Type": "application/json",
                      "HTTP-Referer": "https://sovereign.local",
                      "X-Title": "kimi-live-probe"},
                     m))

NV_MODELS = ["moonshotai/kimi-k3", "moonshotai/kimi-k2.6"]
for keyname in ["NVIDIA_API_KEY", "NIM_PROXY_API_KEY", "NVIDIA_NIM_API_KEY"]:
    key = K.get(keyname, "")
    if not key:
        print("SKIP nvidia[%s]: key unset" % keyname)
        continue
    for m in NV_MODELS:
        jobs.append(("nvidia[%s]" % keyname,
                     "https://integrate.api.nvidia.com/v1/chat/completions",
                     {"Authorization": "Bearer " + key,
                      "Content-Type": "application/json"},
                     m))

print("probing %d model/provider combos..." % len(jobs), flush=True)
with ThreadPoolExecutor(max_workers=6) as ex:
    for r in ex.map(lambda j: probe(*j), jobs):
        if r["ok"]:
            print("OK   %-28s %-28s http=%s %ss reply=%r"
                  % (r["provider"], r["model"], r["http"], r["secs"],
                     r["reply"]), flush=True)
        else:
            print("FAIL %-28s %-28s http=%s [%s] %s"
                  % (r["provider"], r["model"], r["http"], r["err_type"],
                     r["err"]), flush=True)
print("done")
