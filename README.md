# nvidia-alive

Live endpoint auditing for NVIDIA NIM (and friends). Don't trust providers —
**only endpoints**: every availability verdict here comes from a real request
sent to a real completions endpoint, never from a catalog listing.

## What this is

- `scripts/prober.py` — the endpoint prober (v2). asyncio + bounded
  semaphore, no thread pool, no sleeps. Probes every provider × key × model
  combination against the real completions endpoint for that provider
  (OpenAI chat, Anthropic Messages, Gemini `generateContent`, Pollinations
  text route, HF router). Reasoning-aware success detection, resumable
  JSONL output, dedup on provider/key-alias/model, endpoint/model-aware
  ceilings (kimi-k3 gets 400 s, default 90 s). Verdicts: `alive` · `quota` ·
  `auth` · `dead` · `entitlement_gated` · `capacity_starved` · `retired` ·
  `bad_request` · `flaky`. Keys come from the environment — never committed.
- `scripts/nim_stream.py` — maximal SSE streaming client for NIM:
  TCP keepalive, 320 s socket ceiling, correct `data:`/heartbeat/`[DONE]`
  parsing, captures TTFT, per-chunk inter-token latency, reasoning vs
  content vs tool calls, usage, request id, NDJSON telemetry.
- `scripts/full-sweep.py` — the original sweep (thread pool, 60 s ceiling).
  Superseded by `prober.py`; kept for the historical record. Its 60 s
  ceiling false-killed kimi-k3 — do not reuse that ceiling.
- `scripts/kimi-id-fuzz.py`, `scripts/kimi-final-probe.py` — the
  kimi-k2.6 investigation (20 ID variants; proved entitlement gating).
- `scripts/kimi-k3-timing.py`, `scripts/k3-runner.sh`,
  `scripts/pcap-analyze.py` — the packet-level latency investigation that
  proved the 118–159 s "latency" is server-side queue wait.
- `scripts/kimi-live-probe.py`, `scripts/kimi-k3-reprobe.py`,
  `scripts/kimi-provider-audit.py`, `scripts/provider-audit.py` —
  earlier per-provider audit passes.
- `bench.sh`, `scenario-smoke.json` — GuideLLM sweep over the alive list.
  Data-driven: `bench/models-bench.json` (general-chat model set, provider
  backends, NIM-ID → HF tokenizer map — the explicit `--tokenizer` that
  fixed the smoke-test failure), `bench/tokenizer-map.json` (sourced
  tokenizer provenance), `bench/scenarios/` (per-model scenarios generated
  by `scripts/gen-scenarios.py` from the model set + `context-map.json`).
  `./bench.sh --all` runs every verified-tokenizer model unattended;
  `--dry-run`, `--list`, `--provider`, `--long` (8k/1k long-context
  variant), `--include-provisional` also available. kimi-k3 is excluded
  (capacity-starved — see `alive/queue-gated.txt`).

## Solved findings

See [`docs/FINDINGS.md`](docs/FINDINGS.md):

1. **kimi-k2.6 404 = per-account entitlement gating** (NVCF function
   `23d4f03a-b8a6-4adb-a183-7daa083a09cc`, "Not found for account") —
   not retirement (retired = 410). Fix needs NVIDIA support, not client code.
2. **kimi-k3 118–159 s = CAPACITY_STARVED, not latency.** Live NVCF probes
   (`NVCF-POLL-SECONDS: 30/60`) returned HTTP 504 *with* an `nvcf-reqid`:
   the control plane accepted the invocation but no worker picked it up —
   zero warm capacity. No 202 ever (async hypothesis dead), no 404 (death
   hypothesis dead), `NVCF-AI-Resource` header is a no-op, 401 and 403 both
   mean auth failure. Exclude its queue time from throughput benchmarks.
3. **NIM is three APIs**: `integrate.api.nvidia.com/v1` (chat, lies by
   omission), `api.nvcf.nvidia.com/v2/nvcf` (the honest one — `/functions`
   lists exactly what your key can invoke), `ai.api.nvidia.com/v1/genai`
   (async 202+REQID).

## Layout

```
├── bench.sh, scenario-smoke.json   # GuideLLM benchmark entry points
├── bench/                          # models-bench.json, tokenizer-map.json,
│                                   # generated per-model scenarios/
├── context-map.json                # per-model max context (ctx-mapper)
├── scripts/                        # all probers, clients, fuzzers
├── docs/                           # FINDINGS.md, audit plan, kimi research
├── results/                        # local evidence (k3 timing JSONL)
└── alive/                          # endpoint-alive model lists by provider
```

## Running

```bash
set -a; . ~/.secrets; set +a   # keys from env, never from files here
python3 scripts/prober.py      # full provider x key x model sweep
python3 scripts/nim_stream.py  # maximal SSE probe of one NIM model
```

No secrets are stored in this repo — the pre-push scan (`grep` for
key-shaped assignments) is clean. Anything under `results/` is local
evidence; the raw full-sweep JSONL lives alongside the sweep runner.
