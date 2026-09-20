#!/usr/bin/env python3
"""Endpoint-liveness prober v2 for NVIDIA NIM (+ OpenAI-compatible gateways).

v1's failures, fixed here:
  - ThreadPoolExecutor + time.sleep pacing            -> asyncio + bounded semaphore, zero sleeps
  - 25s ceiling marked queue-starved models dead      -> per-model timeout policy
      (known queue-gated models like moonshotai/kimi-k3 get 400s; default 90s)
  - verdict "flaky" for HTTP-200-with-empty-content   -> reasoning-aware text
      extraction (content OR reasoning_content); empty-but-200 with a valid
      finish_reason is "alive"
  - 404 treated as dead                              -> NVCF entitlement gating
      ("Function '<uuid>': Not found for account") is its own verdict:
      entitlement_gated. HTTP 410 with an end-of-life message is retired.
  - 60s sweep ceiling -> QUEUE_GATED_TIMEOUT for the starved set

Verdicts: alive | quota | auth | dead | entitlement_gated | queue_gated |
          retired | bad_request | flaky

Usage:
  NIM_KEY=<key> ./prober.py <model-id> [model-id ...] [--timeout 90] [--out results.jsonl]
"""
import argparse
import asyncio
import json
import os
import sys
import time

import urllib.request
import urllib.error

BASE = os.environ.get("NIM_BASE", "https://integrate.api.nvidia.com")
DEFAULT_TIMEOUT = 90
QUEUE_GATED_TIMEOUT = 400
# Models proven to sit behind a zero-warm-worker NVCF function: the whole
# request time is server-side queue, not inference. Give them a real ceiling.
QUEUE_GATED_MODELS = {
    "moonshotai/kimi-k3",
}
CONCURRENCY = 8


def classify(http, body, secs, timeout):
    err = (body.get("detail") or body.get("message") or body.get("error") or "")
    if isinstance(err, dict):
        err = err.get("message", "")
    err_s = str(err)
    if http == 200:
        try:
            ch = (body.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
            if text:
                return "alive", ""
            # 200 with a finish reason but no text: still a live inference
            if ch.get("finish_reason"):
                return "alive", "empty-content:" + str(ch.get("finish_reason"))
            return "flaky", "200-no-text-no-finish"
        except Exception:
            return "flaky", "200-unparseable"
    if http == 401:
        return "auth", err_s[:160]
    if http == 403:
        return "auth", err_s[:160]
    if http == 404:
        if "Not found for account" in err_s or "Function" in err_s:
            return "entitlement_gated", err_s[:200]
        return "dead", err_s[:160]
    if http == 410:
        return "retired", err_s[:200]
    if http == 429 or "quota" in err_s.lower() or "credit" in err_s.lower():
        return "quota", err_s[:160]
    if http in (400, 422):
        return "bad_request", err_s[:160]
    if http and http >= 500:
        return "flaky", "http-%d %s" % (http, err_s[:120])
    if http == 0:
        if secs >= timeout - 1:
            return "queue_gated", "ttfb-timeout (%.0fs ceiling)" % timeout
        return "flaky", err_s[:160]
    return "dead", "http-%s %s" % (http, err_s[:120])


def _probe_sync(model, key, timeout):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 8,
    }).encode()
    req = urllib.request.Request(
        BASE + "/v1/chat/completions", data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        raw = r.read()
        secs = time.time() - t0
        try:
            payload = json.loads(raw)
        except Exception:
            return {"model": model, "http": r.status, "verdict": "flaky",
                    "secs": round(secs, 2), "err": "non-json-200"}
        verdict, note = classify(r.status, payload, secs, timeout)
        ch = {}
        try:
            ch = (payload.get("choices") or [{}])[0].get("message") or {}
        except Exception:
            pass
        return {"model": model, "http": r.status, "verdict": verdict,
                "secs": round(secs, 2),
                "reply": (ch.get("content") or ch.get("reasoning_content") or "")[:120],
                "note": note}
    except urllib.error.HTTPError as e:
        secs = time.time() - t0
        raw = e.read(1500)
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"detail": raw[:300].decode("utf-8", "replace")}
        verdict, note = classify(e.code, payload, secs, timeout)
        return {"model": model, "http": e.code, "verdict": verdict,
                "secs": round(secs, 2), "reply": "", "note": note}
    except Exception as e:
        secs = time.time() - t0
        verdict, note = classify(0, {"detail": "%s: %s" % (type(e).__name__, e)},
                                 secs, timeout)
        return {"model": model, "http": 0, "verdict": verdict,
                "secs": round(secs, 2), "reply": "", "note": note}


async def probe_one(model, key, timeout, sem, out, is_file):
    async with sem:
        res = await asyncio.to_thread(_probe_sync, model, key, timeout)
        res["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        line = json.dumps(res) + "\n"
        if is_file:
            out.write(line)
            out.flush()
        print("%-55s %s %s (%.1fs) %s" % (
            model, res["http"], res["verdict"], res["secs"], res.get("note", "")))
        return res


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY)
    args = ap.parse_args()
    key = os.environ.get("NIM_KEY") or os.environ.get("NVIDIA_API_KEY")
    if not key:
        sys.exit("set NIM_KEY (or NVIDIA_API_KEY)")
    # already-probed set for resumability
    done = set()
    if args.out and os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["model"])
                except Exception:
                    pass
    models = [m for m in args.models if m not in done]
    if done:
        print("resuming: %d already probed, %d to go" % (len(done), len(models)))
    out = open(args.out, "a") if args.out else None
    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*[
        probe_one(m, key, QUEUE_GATED_TIMEOUT if m in QUEUE_GATED_MODELS else args.timeout,
                  sem, out, bool(out))
        for m in models
    ])
    if out:
        out.close()
    from collections import Counter
    print(Counter(r["verdict"] for r in results))


if __name__ == "__main__":
    asyncio.run(main())
