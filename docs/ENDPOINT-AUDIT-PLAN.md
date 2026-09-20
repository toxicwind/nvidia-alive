# Endpoint-Only Audit Plan

**Doctrine:** catalogs are claims, completions are truth. No `/v1/models`
verdicts, no model cards, no provider docs. A model is alive only if a live
request to a completions endpoint returns real tokens. Everything else is
a candidate list, never a verdict.

## Probe spec (applies to every provider)

- One minimal chat completion per model: `messages=[{role:user,
  content:"Reply with exactly: OK"}]`, `max_tokens=8`, `temperature=0`.
- Record per attempt: provider, key alias, model, HTTP status, latency,
  error type/message (truncated), or `ok` + reply snippet.
- Bounded concurrency (6 workers), per-request timeout 60s, **no sleeps,
  no retries, no polling**. Fail fast.
- Output: JSONL, one line per attempt, atomic append. Summary table
  generated from JSONL only.
- Cost guard: 8 max tokens keeps paid probes to pennies; stop a provider
  after its first hard auth failure (401/402) rather than burning the list.

## Classification (from endpoint behavior only)

| verdict | signal |
|---|---|
| `alive` | 200 + non-empty choices |
| `quota` | 402 / 403 / 429 with quota/balance message — reachable, not dead |
| `dead` | 404 / 410, or explicit "model not found / retired" |
| `auth` | 401 on a key that lists fine — key problem, not model problem |
| `flaky` | timeouts or 5xx across attempts — quarantine, re-probe later |
| `unsupported` | 400 on params the model rejects (e.g. penalties on Kimi) — retry with bare params before calling it dead |

## Provider matrix (keys from `.secrets`, endpoints to hit)

- **openrouter** (`OPENROUTER_API_KEY_1`, `OPENROUTER_API_KEY`) —
  `https://openrouter.ai/api/v1/chat/completions`
- **nvidia** (`NVIDIA_API_KEY`, `NIM_PROXY_API_KEY`, `NVIDIA_NIM_API_KEY`) —
  `https://integrate.api.nvidia.com/v1/chat/completions`
- **moonshot** (`MOONSHOT_API_KEY`) — `https://api.moonshot.ai/v1/chat/completions`
- **deepseek** (`DEEPSEEK_API_KEY`) — `https://api.deepseek.com/chat/completions`
- **mistral** (`MISTRAL_API_KEY`) — `https://api.mistral.ai/v1/chat/completions`
- **groq** (`GROQ_API_KEY`) — `https://api.groq.com/openai/v1/chat/completions`
- **cerebras** (`CEREBRAS_API_KEY`) — `https://api.cerebras.ai/v1/chat/completions`
- **anthropic** (`ANTHROPIC_API_KEY`) — `https://api.anthropic.com/v1/messages`
  (Messages API shape, not chat/completions)
- **gemini** (7 keys) — `generativelanguage.googleapis.com/v1beta/models/{m}:generateContent`
- **herd** — `http://127.0.0.1:25100/v1/chat/completions` (peer routing under test)
- **flock** — `http://127.0.0.1:8000/v1/chat/completions` (upstream adverts under test)
- **pollinations** — `https://text.pollinations.ai/{prompt}?model={m}` (GET shape)
- **hf-router** — dead token, skip unless key rotates
- **scout** — not an LLM provider, excluded

## Phases

1. **Kimi sweep (tool ready: `kimi-live-probe.py`).** All 9 OpenRouter kimi IDs ×
   2 keys, both NVIDIA kimi IDs × 3 keys. Live sends only.
   - Already established by re-probe: `moonshotai/kimi-k3` → **alive**,
     118s latency (far past the old 25s prober ceiling — the ceiling was the
     bug, not the model). `moonshotai/kimi-k2.6` → **dead** (HTTP 404).
2. **NIM endpoint-live 11.** The 11 models that returned 200-with-choices in
   the first audit, re-verified via completions; split into general-chat vs
   specialized (safety/parser/translation/vision/diffusion) lists.
3. **Full provider sweeps.** Candidate IDs from each provider's models
   listing, every one verified by a live completion. Nothing marked alive
   without tokens on the wire.

## Notes

- OpenRouter's catalog lists 9 kimi IDs while the account returns 402 on
  spend — the listing is the "obtuse" part; only phase 1 answers it.
- NVIDIA's catalog lists `kimi-k2.6` as available while completions 404 —
  same lesson.
- `ANTHROPIC_BASE_URL=http://127.0.0.1:8000/v1` routes anthropic clients at
  flock; the audit hits api.anthropic.com direct to test the key itself.

## Prober v2 update (2026-09-20) — supersedes stale notes above

`scripts/prober.py` was rewritten: asyncio + bounded semaphore (no thread
pool, no sleeps), reasoning-aware success detection, resumable JSONL,
dedup on provider/key-alias/model, endpoint/model-aware ceilings
(kimi-k3: 400 s, default: 90 s).

Verdict taxonomy: `alive` · `quota` · `auth` · `dead` ·
`entitlement_gated` · `capacity_starved` (`queue_gated` in older output) ·
`retired` · `bad_request` · `flaky`.

Corrections to the phase notes above, from live endpoint evidence
(see `docs/FINDINGS.md`):

- `moonshotai/kimi-k2.6` → `entitlement_gated`, NOT dead. HTTP 404 with
  NVCF function UUID `23d4f03a-b8a6-4adb-a183-7daa083a09cc`,
  "Not found for account". Retired is signaled by 410
  (cf. `moonshotai/kimi-k2-thinking`, EOL 2026-05-12).
- `moonshotai/kimi-k3` → `capacity_starved`, NOT plain alive. The 118–159 s
  is silent NVCF server-side queue wait (cold provisioning), not inference:
  pcap shows 142.7 s of wire silence, then 0.2 s of generation. Live NVCF
  probes (`NVCF-POLL-SECONDS: 30/60`) returned HTTP 504 *with* an
  `nvcf-reqid`: control plane accepted the invocation, no worker picked it
  up — zero warm capacity per NVIDIA docs. No 202 ever on the chat route
  (async hypothesis dead; do not build 202+poll against it), no 404 (death
  hypothesis dead), `NVCF-AI-Resource` header is a no-op. The old 25 s
  prober ceiling false-killed it; the fixed ceiling is 400 s.
- HTTP 200 with empty `content` but non-empty `reasoning_content`,
  `finish_reason: "length"`, and reasoning-token usage = `alive`. The old
  `max_tokens=5` sweep false-negatived reasoning models — classify on
  content + reasoning_content + finish_reason + usage, never content alone.
- NIM auth failure is 403 as well as 401 → `auth`. 429/402/quota-403 →
  `quota` (reachable, wallet-gated). Timeout/5xx → `flaky` (quarantine,
  re-probe), never `dead`.
