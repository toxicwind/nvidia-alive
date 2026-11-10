#!/usr/bin/env python3
"""Audit every provider we can reach for *kimi* in its models listing.
Keys come from the environment (sourced from ~/.secrets on yote).
Prints only provider, HTTP status, and matching model IDs -- never key material.
"""
import json
import os
import urllib.error
import urllib.request


def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, str(e)[:100])


def kimi_ids(payload):
    try:
        d = json.loads(payload)
    except Exception:
        return None
    if isinstance(d, dict):
        data = d.get("data") or []
    elif isinstance(d, list):
        data = d
    else:
        data = []
    out = []
    for m in data:
        mid = m.get("id") if isinstance(m, dict) else m
        if mid and "kimi" in str(mid).lower():
            out.append(str(mid))
    return out


K = os.environ
providers = [
    ("moonshot",
     "https://api.moonshot.ai/v1/models",
     {"Authorization": "Bearer " + K.get("MOONSHOT_API_KEY", "")}),
    ("nvidia",
     "https://integrate.api.nvidia.com/v1/models",
     {"Authorization": "Bearer " + K.get("NVIDIA_API_KEY", "")}),
    ("openrouter",
     "https://openrouter.ai/api/v1/models",
     {"Authorization": "Bearer " + K.get("OPENROUTER_API_KEY_1", "")}),
    ("pollinations",
     "https://text.pollinations.ai/models", {}),
    ("hf-router",
     "https://router.huggingface.co/v1/models",
     {"Authorization": "Bearer " + K.get("HF_TOKEN", "")}),
    ("herd",
     "http://127.0.0.1:25100/v1/models", {}),
    ("flock",
     "http://127.0.0.1:8000/v1/models",
     {"Authorization": "Bearer " + K.get("FLOCK_API_KEY", "")}),
]

for name, url, headers in providers:
    status, body = get(url, headers)
    ids = kimi_ids(body)
    print("### %s: http=%s" % (name, status))
    if ids is None:
        print("   (unparseable: %s)" % body[:120].replace("\n", " "))
    elif not ids:
        print("   (no kimi models)")
    else:
        for i in ids:
            print("   -", i)
