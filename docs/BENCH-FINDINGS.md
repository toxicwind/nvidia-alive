# GuideLLM benchmark findings

Standard command only: `./bench.sh --all` (never `--long`).
Results live in `~/.local/share/nvidia-alive/bench/<provider>__<model>.json`.

## Run 3 (2026-09-20, `./bench.sh --all`)

Final: `ran=9 failed=15 skipped_no_key=0 skipped_tokenizer=0`.
`skipped_tokenizer=0` proves all 24 configured entries resolved tokenizers.

| Model | ok/err/inc/total | dur_s | TTFT mean/p50 ms | ITL mean/p50 ms | out tok/s mean/p50 | req/s | prompt/out tok |
|---|---|---|---|---|---|---|---|---|
| nvidia/nemotron-3-super-120b-a12b | 47/3/0/50 | 375.5 | 564.46/427.23 | 14.51/11.45 | 64.08/59.47 | 0.125 | 48,880/24,064 |
| nvidia/nemotron-3-ultra-550b-a55b | 49/1/0/50 | 1316.2 | 8945.02/1613.86 | 35.04/19.90 | 19.06/9.39 | 0.037 | 50,960/25,088 |
| nvidia/nemotron-3.5-lightning-30b-a3b | 25/0/1/26 | 1800.0 | 27801.89/7786.51 | 74.71/25.80 | 7.11/2.12 | 0.014 | 26,000/12,800 |
| mistralai/mistral-nemotron | 11/10/0/21 | 737.6 | 11438.40/395.98 | 26.15/22.83 | 7.22/0.00 | 0.015 | 11,286/5,327 |

Exact errors:
- Super: 3 × `Service temporarily overloaded`; Ultra: 1 × same.
- Lightning's missing request is in `requests.incomplete`: `Request was cancelled`
  (timeout wall at 1800 s, not a model failure).
- mistral-nemotron: 9 × HTTP 500 + 1 × `EngineCore encountered an issue`
  + a cancelled request in the list data.

## Aggregate totals vs request-list lengths

GuideLLM's aggregate `request_totals` can disagree with actual list lengths.
Observed: old colon-form Herd q4km had `request_totals.errored = 10` but
`len(requests.errored) = 11` (10 HTTP errors + 1 cancelled). The extractor
(`scripts/extract-metrics.py`) reports both — never silently pick one.

## The 15 original no-JSON failures

Startup failures, all the same cause: `validate_backend` defaulted to
`/health`, which returns **404** on Mistral (×10), Gemini (×1), and
OpenRouter (×4) while their `/v1/models` routes return 200. Fixed by
per-provider `validate_backend` routes in `bench/models-bench.json`.

## Mistral HTTP 422 — root-caused 2026-09-20

All 10 Mistral models failed every request with 422 from
`https://api.mistral.ai/v1/chat/completions`. Direct endpoint probes with
the exact GuideLLM payload proved two fields are the cause:

- `stream_options.continuous_usage_stats: true` → 422 `extra_forbidden`
- `ignore_eos: true` → 422 `extra_forbidden`

(`stream_options: {include_usage: true}` alone and `stop: null` are fine.)

Fix (GuideLLM fork, toxicwind/guidellm): `openai_strict_compat` on
`OpenAIHTTPBackendArgs`. When true, the chat handler omits both fields.
`bench.sh` reads `strict_compat` from the provider row in
`models-bench.json`; Mistral sets it. Direct probe of the strict body
returns **200** — fix verified at the endpoint level before any rerun.

## Gemini doubled `/v1` — root-caused 2026-09-20

The harness built
`https://generativelanguage.googleapis.com/v1beta/openai/v1/chat/completions`
(extra `/v1`; the `/v1beta/openai` prefix is already the version root) → 400.
Fix: per-provider `request_path` in `models-bench.json`
(gemini = `/chat/completions`), passed as `request_format` by `bench.sh`.
Gemini also rejects `continuous_usage_stats`/`ignore_eos` (400 "Unknown
name"), so it sets `strict_compat` too.

Gemini billing state (observed 2026-09-20): the key's prepayment credits are
**depleted** (HTTP 402). The corrected config validates at the endpoint but
benchmarks will 402 until credits are added — provider-side, not a harness bug.

## Herd corrected-ID reruns (2026-09-20)

Dash-form IDs (`-iq4xs`, `-q4km`) after the colon-form 404s:

- iq4xs: 43/7/0/50, 173.2 s, TTFT 304.58/73.60 ms, ITL 6.93/3.09 ms,
  127.08/39.47 out tok/s, 7 × HTTP 502
- q4km: 44/6/0/50, 91.0 s, TTFT 98.66/88.97 ms, ITL 3.71/3.29 ms,
  247.47/299.64 out tok/s, 6 × HTTP 502

The 502s are server-side (herd router backend), not request errors.

## OpenRouter free-tier reruns (2026-09-20)

`nex-agi/nex-n2.5-mini:free`: 2 successful, 10 × HTTP 429 — free-tier rate
limiting, not a harness bug. The 2 successes prove the request body is valid.

## Tokenizer load_kwargs (fix_mistral_regex)

The Ministral tokenizer warned that `fix_mistral_regex=True` should be used.
Verified against transformers 5.17.0: the flag only affects
`MistralCommonBackend` (Tekken) loads; `mistral_common` is not installed in
the benchmark venv so all loads resolve to `TokenizersBackend` and the flag
is benign — all 5 `mistralai/*` tokenizers load fine with or without it.
`bench.sh` passes per-model `tokenizer_load_kwargs` from `models-bench.json`
through GuideLLM's dot-notation arg string
(`load_kwargs.fix_mistral_regex=true`); the 6 Ministral entries set it.
End-to-end verified: arg string → schema validation → registry → tokenizer
load. Tests: `scripts/tests/test_bench_sh.py`.

## Metric extractor

`scripts/extract-metrics.py` reads nested GuideLLM JSON and emits Markdown,
JSON, or CSV: ok/errored/incomplete/total, duration, TTFT/ITL mean+p50,
output tok/s mean+p50, request rate, prompt/output token totals, overall
token throughput, deduplicated exact errors, observed request statuses.

```bash
python3 scripts/extract-metrics.py <result.json>            # markdown
python3 scripts/extract-metrics.py <result.json> --json     # json
python3 scripts/extract-metrics.py <dir>/*.json --csv       # csv
python3 scripts/tests/test_extract_metrics.py               # 5 tests
```

## Credential hygiene note

`bench.sh` passes provider keys as `api_key=<key>` inside the `guidellm`
command line, so raw keys are visible to any local user via `ps` while a
benchmark runs. Keys must move to an env-var/file reference instead of
command-line embedding. (Flagged 2026-09-20; not changed yet — credential
handling is Chris's call.)
