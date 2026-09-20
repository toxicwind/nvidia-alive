#!/usr/bin/env python3
"""Kimi ID/path fuzzing against NVIDIA integrate API.
Catalogs are claims; completions are truth. Tries many candidate model IDs
x endpoint paths x key aliases, records HTTP status + full error bodies.
No sleeps, bounded workers, fail-fast timeouts. Keys from env only.
Usage: python3 kimi-id-fuzz.py [out.jsonl]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

K = os.environ
OUT = (sys.argv[1] if len(sys.argv) > 1 else
       "/home/toxic/.local/share/nvidia-alive/kimi-id-fuzz.jsonl")
BASE = "https://integrate.api.nvidia.com"
TIMEOUT = 30
WORKERS = 10

IDS = [
    # k2.6 family
    "moonshotai/kimi-k2.6",
    "kimi-k2.6",
    "moonshotai/kimi-k2-6",
    "moonshotai/kimi-k2_6",
    "moonshotai/kimi-k2.6-instruct",
    "moonshotai/Kimi-K2.6",
    "moonshotai/Kimi-K2_6",
    # k2.5 family
    "moonshotai/kimi-k2.5",
    "kimi-k2.5",
    "moonshotai/kimi-k2-5",
    "moonshotai/kimi-k2.5-0905",
    "moonshotai/kimi-k2-5-0905",
    "moonshotai/kimi-k2-0905",
    "moonshotai/Kimi-K2.5",
    # k2 generic / thinking / latest
    "moonshotai/kimi-k2",
    "kimi-k2",
    "moonshotai/kimi-k2-thinking",
    "moonshotai/kimi-latest",
    "moonshotai/kimi-k2.7-code",
    # positive control: known alive
    "moonshotai/kimi-k3",
]

PATHS = ["/v1/chat/completions", "/v1/completions"]


def probe(path, key, key_alias, model):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 8,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        BASE + path, data=payload,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
        method="POST")
    t0 = time.time()
    try:
        # k3 control gets a longer leash (known 118s latency)
        to = 200 if model == "moonshotai/kimi-k3" else TIMEOUT
        with urllib.request.urlopen(req, timeout=to) as r:
            body = r.read().decode()
            dt = round(time.time() - t0, 2)
            try:
                d = json.loads(body)
                if "choices" in d:
                    text = str(d["choices"][0]["message"]["content"])[:60]
                else:
                    text = str(d.get("text", d))[:60]
            except Exception:
                text = body[:60]
            return {"http": 200, "verdict": "alive", "secs": dt,
                    "reply": text, "err": ""}
    except urllib.error.HTTPError as e:
        dt = round(time.time() - t0, 2)
        try:
            ebody = e.read().decode()[:400]
        except Exception:
            ebody = ""
        return {"http": e.code,
                "verdict": ("dead" if e.code in (404, 410)
                            else "quota" if e.code in (402, 403, 429)
                            else "auth" if e.code == 401 else "other"),
                "secs": dt, "reply": "", "err": ebody.replace("\n", " ")}
    except Exception as e:
        dt = round(time.time() - t0, 2)
        kind = "timeout" if "timed out" in str(e) or "Timeout" in type(e).__name__ \
            else type(e).__name__
        return {"http": -1, "verdict": kind, "secs": dt, "reply": "",
                "err": str(e)[:200].replace("\n", " ")}


def main():
    key_aliases = []
    for name in ["NVIDIA_API_KEY", "NIM_PROXY_API_KEY", "NVIDIA_NIM_API_KEY"]:
        if K.get(name):
            key_aliases.append((name, K[name]))
    multi = K.get("NVIDIA_API_KEYS", "")
    for i, part in enumerate(
            [p.strip().strip("'\"") for p in multi.split(",") if p.strip()], 1):
        key_aliases.append(("NVIDIA_API_KEYS#%d" % i, part))
    if not key_aliases:
        print("no NVIDIA keys in env; aborting")
        return

    jobs = [(p, ka, k, m) for p in PATHS for (ka, k) in key_aliases
            for m in IDS]
    print("fuzzing %d combos (%d ids x %d paths x %d keys)" %
          (len(jobs), len(IDS), len(PATHS), len(key_aliases)), flush=True)

    seen_bodies = {}
    with open(OUT, "w") as f, ThreadPoolExecutor(max_workers=WORKERS) as ex:
        def run(job):
            path, ka, k, m = job
            r = probe(path, k, ka, m)
            r.update({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "path": path, "key_alias": ka, "model": m})
            return r
        for r in ex.map(run, jobs):
            f.write(json.dumps(r) + "\n")
            f.flush()
            tag = "%s %s %s" % (r["path"], r["key_alias"], r["model"])
            if r["verdict"] == "alive":
                print("ALIVE %s %ss reply=%r" % (tag, r["secs"], r["reply"]),
                      flush=True)
            elif r["verdict"] not in ("dead",):
                print("%s %s http=%s %ss %s" %
                      (r["verdict"].upper(), tag, r["http"], r["secs"],
                       r["err"][:100]), flush=True)
            # print each distinct 404 body once
            body = r["err"]
            if r["http"] == 404 and body not in seen_bodies:
                seen_bodies[body] = True
                print("404-BODY %s :: %s" % (tag, body[:200]), flush=True)
    print("wrote %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
