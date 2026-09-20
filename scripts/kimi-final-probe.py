#!/usr/bin/env python3
"""Final targeted probes: NVCF 404 body on a second key, k2.5 (not in NVIDIA
catalog), and a k3 liveness re-confirmation. Keys from env only."""
import json
import os
import urllib.error
import urllib.request

K = os.environ
URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def probe(key, model, timeout=30):
    req = urllib.request.Request(
        URL,
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 8,
            "temperature": 0,
        }).encode(),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            try:
                d = json.loads(body)
                text = str(d["choices"][0]["message"]["content"])[:80]
            except Exception:
                text = body[:80]
            return r.status, "ALIVE reply=" + text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300].replace("\n", " ")
    except Exception as e:
        return -1, type(e).__name__ + ": " + str(e)[:120]


def clean(v):
    return v.strip().strip("'").strip('"')


nv_parts = [clean(p) for p in K.get("NVIDIA_API_KEYS", "").split(",")
            if clean(p)]

tests = [
    ("__NV1", nv_parts[0] if nv_parts else "", "moonshotai/kimi-k2.6", 30),
    ("NVIDIA_API_KEY", K.get("NVIDIA_API_KEY", ""), "moonshotai/kimi-k2.5", 30),
    ("NVIDIA_API_KEY", K.get("NVIDIA_API_KEY", ""), "moonshotai/kimi-k3", 200),
]
for label, key, model, timeout in tests:
    if not key:
        print("=== %s %s -> SKIP (no key)" % (label, model))
        continue
    st, body = probe(key, model, timeout)
    print("=== %s %s -> http=%s" % (label, model, st))
    print(body[:280])
    print()
