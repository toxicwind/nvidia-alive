#!/usr/bin/env python3
"""Instrumented streaming timing probe for NVIDIA NIM chat completions.

Decomposes wall time into: DNS, TCP connect, TLS handshake, request send,
time-to-first-SSE-chunk, per-chunk arrivals, completion. Captures
reasoning_content deltas, response headers, TLS version/cipher, and usage
(stream_options include_usage).

Usage: kimi-k3-timing.py <out.jsonl> <model> <label> [runs]
Key: NVIDIA_API_KEY from environment.
"""
import http.client
import json
import os
import socket
import ssl
import sys
import time

HOST = "integrate.api.nvidia.com"
PORT = 443
PATH = "/v1/chat/completions"

PROMPT = "Reply with exactly: OK"


def emit(out_f, base, event, **kw):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "t_rel_ms": round((time.monotonic() - base) * 1000, 1),
           "event": event}
    rec.update(kw)
    out_f.write(json.dumps(rec) + "\n")
    out_f.flush()


def run_once(out_f, model, label, run_idx, key):
    t0 = time.monotonic()
    common = {"label": label, "run": run_idx, "model": model}
    try:
        # --- DNS ---
        t = time.monotonic()
        infos = socket.getaddrinfo(HOST, PORT, type=socket.SOCK_STREAM)
        emit(out_f, t0, "dns_done", **common,
             ms=round((time.monotonic() - t) * 1000, 1),
             addrs=[i[4][0] for i in infos][:3])

        # --- TCP ---
        t = time.monotonic()
        s = socket.create_connection((HOST, PORT), timeout=15)
        emit(out_f, t0, "tcp_done", **common,
             ms=round((time.monotonic() - t) * 1000, 1))

        # --- TLS ---
        t = time.monotonic()
        ctx = ssl.create_default_context()
        ss = ctx.wrap_socket(s, server_hostname=HOST)
        cipher = ss.cipher()
        emit(out_f, t0, "tls_done", **common,
             ms=round((time.monotonic() - t) * 1000, 1),
             tls_version=ss.version(),
             cipher=cipher[0] if cipher else None)
        ss.settimeout(280)

        # --- HTTP request over the measured socket ---
        conn = http.client.HTTPSConnection(HOST, PORT)
        conn.sock = ss  # skip http.client's own connect; use ours
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": 8,
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
        })
        headers = {"Authorization": "Bearer " + key,
                   "Content-Type": "application/json",
                   "Accept": "text/event-stream"}
        t = time.monotonic()
        conn.request("POST", PATH, body=body, headers=headers)
        req_ms = round((time.monotonic() - t) * 1000, 1)
        req_epoch = time.time()
        emit(out_f, t0, "request_sent", **common, ms=req_ms,
             bytes=len(body), epoch=round(req_epoch, 3))

        # --- response headers ---
        t = time.monotonic()
        resp = conn.getresponse()
        emit(out_f, t0, "headers_done", **common,
             ms=round((time.monotonic() - t) * 1000, 1),
             status=resp.status,
             headers={k.lower(): v for k, v in resp.getheaders()})

        # --- SSE stream ---
        first = True
        n_chunks = 0
        content_chars = 0
        reasoning_chars = 0
        finish = None
        usage = None
        first_epoch = None
        server_created = None
        last_t = time.monotonic()
        fp = resp.fp
        while True:
            line = fp.readline()
            if not line:
                break
            now = time.monotonic()
            dt_ms = round((now - last_t) * 1000, 1)
            last_t = now
            s_line = line.decode("utf-8", "replace").strip()
            if not s_line or not s_line.startswith("data:"):
                continue
            payload = s_line[5:].strip()
            if payload == "[DONE]":
                emit(out_f, t0, "stream_done_marker", **common, dt_ms=dt_ms)
                break
            try:
                d = json.loads(payload)
            except Exception:
                continue
            if first:
                first = False
                first_epoch = time.time()
                server_created = d.get("created")
                emit(out_f, t0, "first_data", **common, dt_ms=dt_ms,
                     id=d.get("id"), server_created=server_created,
                     first_epoch=round(first_epoch, 3),
                     model_field=d.get("model"),
                     system_fingerprint=d.get("system_fingerprint"))
            n_chunks += 1
            try:
                delta = d["choices"][0].get("delta", {}) or {}
            except Exception:
                delta = {}
            cc = len(delta.get("content") or "")
            rc = len(delta.get("reasoning_content") or "")
            content_chars += cc
            reasoning_chars += rc
            try:
                fr = d["choices"][0].get("finish_reason")
            except Exception:
                fr = None
            if fr:
                finish = fr
            if d.get("usage"):
                usage = d["usage"]
            emit(out_f, t0, "chunk", **common, i=n_chunks, dt_ms=dt_ms,
                 content_chars=cc, reasoning_chars=rc, finish_reason=fr)

        wall_ms = round((time.monotonic() - t0) * 1000, 1)
        tok_per_s = (round(content_chars / (wall_ms / 1000), 2)
                     if wall_ms > 0 else 0)
        emit(out_f, t0, "done", **common, chunks=n_chunks,
             content_chars=content_chars, reasoning_chars=reasoning_chars,
             finish_reason=finish, usage=usage, wall_ms=wall_ms,
             tok_per_s=tok_per_s)
        print("run %d %-28s wall=%.1fs chunks=%d content=%d reasoning=%d %s"
              % (run_idx, model, wall_ms / 1000, n_chunks, content_chars,
                 reasoning_chars, finish),
              flush=True)
        try:
            conn.close()
        except Exception:
            pass
    except Exception as e:
        emit(out_f, t0, "error", **common, err_type=type(e).__name__,
             err=str(e)[:200], wall_ms=round((time.monotonic() - t0) * 1000, 1))
        print("run %d %-28s ERROR %s: %s"
              % (run_idx, model, type(e).__name__, str(e)[:120]), flush=True)


def main():
    out_path = sys.argv[1]
    model = sys.argv[2]
    label = sys.argv[3]
    runs = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        print("NVIDIA_API_KEY not in env", flush=True)
        sys.exit(2)
    with open(out_path, "a") as out_f:
        for i in range(1, runs + 1):
            run_once(out_f, model, label, i, key)
    print("wrote %s" % out_path, flush=True)


if __name__ == "__main__":
    main()
