#!/usr/bin/env python3
"""Full endpoint sweep: all providers x all keys x catalog-listed models.
Live completions only -- catalogs generate candidates, endpoints give verdicts.
Primary key per provider gets the full model list; every other key gets a
live 5-model sample (key liveness without redundant spend).
JSONL output, bounded workers, no sleeps, fail fast.
Usage: python3 full-sweep.py [out.jsonl]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

K = os.environ
OUT = (sys.argv[1] if len(sys.argv) > 1 else
       "/home/toxic/.local/share/nvidia-alive/full-sweep.jsonl")
WORKERS = 10
TIMEOUT = 60


def http(method, url, headers=None, payload=None, timeout=TIMEOUT):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(), round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:600]
        except Exception:
            body = ""
        return e.code, body, round(time.time() - t0, 2)
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, str(e)[:200]), \
            round(time.time() - t0, 2)


def list_candidates(url, headers):
    st, body, _ = http("GET", url, headers, timeout=30)
    if st != 200:
        return []
    try:
        d = json.loads(body)
    except Exception:
        return []
    if isinstance(d, dict):
        data = d.get("data") or d.get("models") or []
    elif isinstance(d, list):
        data = d
    else:
        data = []
    out = []
    for m in data:
        if isinstance(m, dict):
            mid = str(m.get("id") or m.get("name") or "").replace("models/", "")
        else:
            mid = str(m)
        if mid:
            out.append(mid)
    return out


def err_detail(body):
    try:
        d = json.loads(body)
        err = d.get("error", d)
        if isinstance(err, dict):
            return (str(err.get("type", "") or err.get("code", ""))[:40],
                    str(err.get("message", str(err)))[:160])
        return "", str(err)[:160]
    except Exception:
        return "", body[:160].replace("\n", " ")


def classify(st, body, text):
    if st == 200 and text:
        return "alive"
    if st in (402, 429):
        return "quota"
    if st == 403:
        return "quota"
    if st in (404, 410):
        return "dead"
    if st == 401:
        return "auth"
    if st == 400:
        return "bad_request"
    return "flaky"


def probe_oai(base, key, model, extra_headers=None):
    headers = {"Authorization": "Bearer " + key,
               "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    st, body, secs = http("POST", base.rstrip("/") + "/chat/completions",
                          headers,
                          {"model": model,
                           "messages": [{"role": "user",
                                         "content": "Reply with exactly: OK"}],
                           "max_tokens": 8, "temperature": 0})
    text, etype, edetail = "", "", ""
    if st == 200:
        try:
            d = json.loads(body)
            text = str(d["choices"][0]["message"]["content"] or "")[:60]
        except Exception:
            pass
    else:
        etype, edetail = err_detail(body)
    return {"http": st, "verdict": classify(st, body, text), "secs": secs,
            "reply": text, "err_type": etype, "err": edetail}


def probe_gemini(key, model):
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + quote(model, safe="") + ":generateContent?key=" + key)
    st, body, secs = http("POST", url, {"Content-Type": "application/json"},
                          {"contents": [{"parts": [{"text":
                             "Reply with exactly: OK"}]}],
                           "generationConfig": {"maxOutputTokens": 8,
                                                "temperature": 0}})
    text, etype, edetail = "", "", ""
    if st == 200:
        try:
            d = json.loads(body)
            text = str(d["candidates"][0]["content"]["parts"][0]["text"]
                       or "")[:60]
        except Exception:
            pass
    else:
        etype, edetail = err_detail(body)
    return {"http": st, "verdict": classify(st, body, text), "secs": secs,
            "reply": text, "err_type": etype, "err": edetail}


def probe_pollinations(model):
    url = ("https://text.pollinations.ai/" +
           quote("Reply with exactly: OK") + "?model=" + quote(model, safe=""))
    st, body, secs = http("GET", url, {}, timeout=TIMEOUT)
    text = body[:60].replace("\n", " ") if st == 200 else ""
    etype, edetail = ("", "") if st == 200 else ("", body[:160])
    return {"http": st, "verdict": classify(st, body, text), "secs": secs,
            "reply": text, "err_type": etype, "err": edetail}


OR_EXTRA = {"HTTP-Referer": "https://sovereign.local",
            "X-Title": "full-sweep"}

# (provider, list_url, list_headers, key_aliases, probe_kind, probe_base)
# probe_kind: "oai" | "gemini" | "pollinations"
PROVIDERS = [
    ("openrouter", "https://openrouter.ai/api/v1/models", {},
     ["OPENROUTER_API_KEY_1", "OPENROUTER_API_KEY"], "oai",
     "https://openrouter.ai/api/v1"),
    ("nvidia", "https://integrate.api.nvidia.com/v1/models", {},
     ["NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "NIM_PROXY_API_KEY"],
     "oai", "https://integrate.api.nvidia.com/v1"),
    ("mistral", "https://api.mistral.ai/v1/models", {}, ["MISTRAL_API_KEY"],
     "oai", "https://api.mistral.ai/v1"),
    ("deepseek", "https://api.deepseek.com/models", {}, ["DEEPSEEK_API_KEY"],
     "oai", "https://api.deepseek.com"),
    ("moonshot", "https://api.moonshot.ai/v1/models", {},
     ["MOONSHOT_API_KEY"], "oai", "https://api.moonshot.ai/v1"),
    ("gemini", None, {},  # candidates fetched once with first live key
     ["GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2",
      "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "GEMINI_API_KEY_5",
      "GOOGLE_API_KEY"], "gemini", None),
    ("pollinations", "https://text.pollinations.ai/models", {}, [],
     "pollinations", None),
    ("herd", "http://127.0.0.1:25100/v1/models", {}, [], "oai",
     "http://127.0.0.1:25100/v1"),
    ("flock", "http://127.0.0.1:8000/v1/models", {}, [], "oai",
     "http://127.0.0.1:8000/v1"),
]


def bearer_headers(envname):
    return {"Authorization": "Bearer " + K.get(envname, "")}


def main():
    # NVIDIA_API_KEYS multi -> expand into numbered aliases
    nvidia_aliases = list(PROVIDERS[1][3])
    multi = K.get("NVIDIA_API_KEYS", "")
    multi_parts = [p.strip().strip("'\"") for p in multi.split(",") if p.strip()]
    for i, part in enumerate(multi_parts, 1):
        K["__NV%d" % i] = part
        nvidia_aliases.append("__NV%d" % i)

    jobs = []  # (provider, key_alias, model, kind, base, key)
    for (provider, list_url, list_headers, aliases, kind, base) in PROVIDERS:
        if provider == "nvidia":
            aliases = nvidia_aliases
        live_aliases = [(a, K.get(a, "")) for a in aliases
                        if K.get(a, "")]
        if not live_aliases and provider in ("herd", "flock"):
            live_aliases = [("-", "")]  # local routers: no key needed
        if kind == "pollinations":
            cands = list_candidates(list_url, list_headers)
            print("%s: %d candidates (no key)" % (provider, len(cands)),
                  flush=True)
            for m in cands:
                jobs.append((provider, "-", m, kind, base, ""))
            continue
        if kind == "gemini":
            key0 = next((k for _, k in live_aliases if k), "")
            if not key0:
                print("gemini: no live keys, skipped", flush=True)
                continue
            st, body, _ = http(
                "GET",
                "https://generativelanguage.googleapis.com/v1beta/models?key="
                + key0, {}, timeout=30)
            cands = []
            if st == 200:
                try:
                    d = json.loads(body)
                    for m in d.get("models", []):
                        mid = str(m.get("name", "")).replace("models/", "")
                        if mid:
                            cands.append(mid)
                except Exception:
                    pass
            print("gemini: %d candidates" % len(cands), flush=True)
        else:
            if provider in ("herd", "flock"):
                cands = list_candidates(list_url, list_headers)
            else:
                key0 = next((k for _, k in live_aliases if k), "")
                if not key0:
                    print("%s: no live keys, skipped" % provider, flush=True)
                    continue
                hdrs = dict(list_headers)
                hdrs.update(bearer_headers(
                    next(a for a, k in live_aliases if k == key0)))
                cands = list_candidates(list_url, hdrs)
            print("%s: %d candidates" % (provider, len(cands)), flush=True)

        # primary alias -> full list; other aliases -> 5-model live sample
        primary = live_aliases[0][0] if live_aliases else None
        sample = [m for m in cands if "kimi" in m.lower()][:3]
        for m in cands:
            if m not in sample and len(sample) < 5:
                sample.append(m)
        for alias, key in live_aliases:
            models = cands if alias == primary else sample
            for m in models:
                jobs.append((provider, alias, m, kind, base, key))

    print("total probes: %d" % len(jobs), flush=True)
    done = [0]

    def run(job):
        provider, alias, model, kind, base, key = job
        if kind == "oai":
            extra = OR_EXTRA if provider == "openrouter" else None
            r = probe_oai(base, key, model, extra)
        elif kind == "gemini":
            r = probe_gemini(key, model)
        else:
            r = probe_pollinations(model)
        r.update({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "provider": provider, "key_alias": alias, "model": model})
        done[0] += 1
        if done[0] % 50 == 0:
            print("  ...%d/%d" % (done[0], len(jobs)), flush=True)
        return r

    with open(OUT, "a") as f, ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(run, jobs):
            f.write(json.dumps(r) + "\n")
            f.flush()
    print("wrote %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
