#!/usr/bin/env python3
"""Maximal SSE streaming client for NVIDIA NIM (integrate.api.nvidia.com).

Built for the hostile case: the gateway holds the stream open in total
silence for ~150s while a cold NVCF function provisions (kimi-k3), then
emits tokens. This client:

  - parses SSE correctly (data: accumulation, : comments/heartbeats, [DONE])
  - sets NO read timeout below the documented ~300s server silence limit
    (socket timeout 320s: a read timing out there is a real signal)
  - enables TCP keepalive so middleboxes don't kill the silent socket
  - requests stream_options.include_usage for the terminal usage chunk
  - timestamps every chunk: TTFT, per-chunk ITL, kind
    (content / reasoning_content / tool_call / heartbeat)
  - writes NDJSON telemetry (one event per line) + a summary

Usage:
  NIM_KEY=<key> ./nim_stream.py <model> "<prompt>" [--max-tokens N] [--telemetry out.jsonl]
"""
import http.client
import json
import os
import socket
import ssl
import sys
import time

HOST = "integrate.api.nvidia.com"
SOCKET_TIMEOUT = 320   # just above the ~300s server-side silence limit
CONNECT_TIMEOUT = 15


def parse_args(argv):
    model, prompt, max_tokens, tele = None, "Reply with exactly: OK", 64, None
    i = 1
    positional = []
    while i < len(argv):
        a = argv[i]
        if a == "--max-tokens":
            max_tokens = int(argv[i + 1]); i += 2
        elif a == "--telemetry":
            tele = argv[i + 1]; i += 2
        elif a.startswith("--"):
            sys.exit("unknown flag %s" % a)
        else:
            positional.append(a); i += 1
    if positional:
        model = positional[0]
    if len(positional) > 1:
        prompt = positional[1]
    if not model:
        sys.exit("usage: nim_stream.py <model> [prompt] [--max-tokens N] [--telemetry f.jsonl]")
    return model, prompt, max_tokens, tele


def main():
    key = os.environ.get("NIM_KEY") or os.environ.get("NVIDIA_API_KEY")
    if not key:
        sys.exit("set NIM_KEY (or NVIDIA_API_KEY)")
    model, prompt, max_tokens, tele_path = parse_args(sys.argv[1:])
    tele = open(tele_path, "w") if tele_path else None

    def emit(ev):
        ev["t"] = round(time.time() - t0, 3)
        if tele:
            tele.write(json.dumps(ev) + "\n")

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()

    t0 = time.time()
    ctx = ssl.create_default_context()
    sock = socket.create_connection((HOST, 443), timeout=CONNECT_TIMEOUT)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
    tls = ctx.wrap_socket(sock, server_hostname=HOST)
    tls.settimeout(SOCKET_TIMEOUT)
    emit({"ev": "tcp_tls_done"})

    conn = http.client.HTTPSConnection(HOST, context=ctx)
    conn.sock = tls  # reuse our tuned socket
    conn.request("POST", "/v1/chat/completions", body=body, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    })
    try:
        resp = conn.getresponse()
    except socket.timeout:
        emit({"ev": "fatal", "err": "no_response_headers"})
        sys.exit(1)
    emit({"ev": "headers", "http": resp.status,
          "nvcf_reqid": resp.getheader("nvcf-reqid"),
          "date": resp.getheader("date")})
    if resp.status != 200:
        print("HTTP", resp.status, resp.read(500)[:500])
        sys.exit(1)

    buf, n_chunks = "", 0
    first_byte_at = None
    last_chunk_at = None
    content_parts, reasoning_parts = [], []
    finish_reason, usage = None, None

    fp = resp.fp
    while True:
        try:
            line = fp.readline()
        except socket.timeout:
            emit({"ev": "fatal", "err": "read_timeout_320s_silence"})
            break
        if not line:
            emit({"ev": "fatal", "err": "eof"})
            break
        if first_byte_at is None:
            first_byte_at = time.time()
            emit({"ev": "first_byte"})
        line = line.decode("utf-8", "replace").rstrip("\n").rstrip("\r")
        if line == "":
            continue
        if line.startswith(":"):
            emit({"ev": "heartbeat", "data": line[1:].strip()})
            continue
        if not line.startswith("data:"):
            emit({"ev": "weird_line", "line": line[:120]})
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            emit({"ev": "done"})
            break
        try:
            obj = json.loads(data)
        except Exception:
            emit({"ev": "bad_json", "data": data[:120]})
            continue
        n_chunks += 1
        now = time.time()
        itl = round(now - last_chunk_at, 3) if last_chunk_at else 0.0
        last_chunk_at = now
        ttft = round(now - first_byte_at, 3)
        try:
            choice = (obj.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            kinds = []
            if delta.get("content"):
                content_parts.append(delta["content"]); kinds.append("content")
            if delta.get("reasoning_content"):
                reasoning_parts.append(delta["reasoning_content"]); kinds.append("reasoning")
            if delta.get("tool_calls"):
                kinds.append("tool_call")
            if obj.get("usage"):
                usage = obj["usage"]; kinds.append("usage")
            emit({"ev": "chunk", "n": n_chunks, "ttft": ttft, "itl": itl,
                  "kind": "+".join(kinds) or "empty",
                  "chars": sum(len(delta.get(k) or "") for k in ("content", "reasoning_content"))})
        except Exception as e:
            emit({"ev": "bad_chunk", "err": str(e)[:80]})

    total = round(time.time() - t0, 2)
    reply = "".join(content_parts)
    thinking = "".join(reasoning_parts)
    summary = {
        "ev": "summary", "model": model, "total_s": total,
        "ttfb_s": round((first_byte_at or t0) - t0, 2),
        "chunks": n_chunks, "finish_reason": finish_reason,
        "content_chars": len(reply), "reasoning_chars": len(thinking),
        "usage": usage,
    }
    emit(summary)
    if tele:
        tele.close()
    print(json.dumps(summary, indent=1))
    print("--- reply ---")
    print(reply[:500] or "(empty)")
    if thinking:
        print("--- reasoning (first 300) ---")
        print(thinking[:300])


if __name__ == "__main__":
    main()
