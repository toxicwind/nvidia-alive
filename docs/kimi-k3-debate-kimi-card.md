# Kimi-K3 / NIM debate — kimi-card position (pro-thesis)

**Thesis (Chris):** every NIM model has a specific model card on build.nvidia.com AND a
HuggingFace repo; "kimi-k3 is broken" reports are mostly people missing this — wrong IDs,
wrong params, wrong endpoints — not a dead model.

## Verdict

**Thesis is substantially correct: ~65% misconfiguration/entitlement/client-bug,
~35% genuine free-tier capacity pain, ~0% model death.**

- The model is NOT dead, deprecated, or removed. Card live:
  https://build.nvidia.com/moonshotai/kimi-k3 — still listed available (exa, 2026-09-20).
- Our own prober (2026-09-20): `moonshotai/kimi-k3` → transport TimeoutError
  (overloaded/throttled), NOT 404/410. `moonshotai/kimi-k2.6` → 404, matching the
  forum "Account Entitlement Issue with Prototype Endpoint" thread — entitlement, not death.
- Real pain exists: Sept 2026 forums show persistent 429s/timeouts on the free tier.
  429 = "slow down", not "gone". The thesis is about *misdiagnosis*, not denying pain.

**Confidence: 80/100** (card facts 95+; the 65/35 split is judgment from report typology).

## 5 strongest evidence bullets

1. **OpenClaw discussion #8319** — direct curl to `integrate.api.nvidia.com` with the SAME
   key returns HTTP 200 while OpenClaw's provider routing 404s. A client-side endpoint-path
   bug, reported as "NVIDIA broken". Textbook wrong-endpoint misdiagnosis.
2. **bauka0's changelog** — Kimi K3 400s because `presence_penalty`/`frequency_penalty`
   are IMMUTABLE (card: fixed at 0, not exposed). Clients send defaults → 400 → "broken".
   Exa-confirmed against the API reference: passing them errors.
3. **Card is the source of truth, folklore is not** — tibbee's repo scrapes card metadata
   (`tools/fetch_nim_metadata.ts` → `models/metadata.json`) for context sizes, thinking
   toggles, `reasoning_effort` levels. Exa-confirmed card facts: 1,048,576 context,
   `reasoning_effort` ∈ {low, high, max} (default max), thinking always-on, no toggle.
4. **NIM id ≠ HF repo id (our own guidellm smoke)** — smoke failed loading tokenizer
   `meta/muse-glimmer-30b` from HF. Verified: NIM `moonshotai/kimi-k3` (lowercase) vs HF
   `moonshotai/Kimi-K3` (capital K). Any tooling assuming id equality breaks — and the
   breakage looks like "model broken".
5. **Not deprecated, still catalog-listed** — exa (2026-09-20): card live, API reference
   live (`docs.api.nvidia.com/nim/reference/moonshotai-kimi-k3-infer`), no deprecation
   notice. "Dead model" claims are false on the face of the card.

## 2 strongest counterarguments + rebuttals

1. **Counter:** Sept 2026 forums (degraded-responses, 381947, 382533, 382757 threads) show
   real persistent 429s/400s/timeouts even for correct configs — the free endpoint is
   genuinely flaky.
   **Rebuttal:** conceded in part — that's capacity/rate-limiting on the free tier, not
   model death. Mitigation is card-driven: `reasoning_effort=low`, backoff/retry, paid key.
2. **Counter:** "we made kimi k3 work on herd" is overstated — no verified working Kimi
   completion was ever recorded; route names were honest but credentials were dead
   (401s), and kimi-auto reports no healthy candidate to this day.
   **Rebuttal:** conceded and sharpened — the honest claim is narrower: every Kimi failure
   we logged was in the credential/routing layer (dead OpenRouter/Moonshot keys,
   mispointed routes like the 87be3f27 incident), never a model-side 410/deprecation.
   Absence of a working demo ≠ evidence of death.

## Card-driven config checklist (the build)

- **Model ID (NIM API):** `moonshotai/kimi-k3` — lowercase, exact.
- **Endpoint:** `POST https://integrate.api.nvidia.com/v1/chat/completions`
- **Card:** https://build.nvidia.com/moonshotai/kimi-k3
- **API ref:** https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k3-infer
- **NEVER send:** `presence_penalty`, `frequency_penalty` (immutable, fixed 0 → 400 if sent)
- **DO use:** `reasoning_effort`: `low` | `high` | `max` (default `max`); `low` reduces
  load/latency when throttled
- **Thinking:** always on, no toggle — don't hunt for one
- **Context:** 1,048,576 tokens
- **NIM-id → HF-repo mapping (for tooling):** `moonshotai/kimi-k3` → `moonshotai/Kimi-K3`
  (case differs!). GuideLLM tokenizers / transformers / any HF lookup MUST use the HF
  repo id, never the NIM id.
- **404?** Check (a) endpoint path — the OpenClaw bug; direct-curl the same key to isolate;
  (b) account entitlement — prototype endpoints are entitlement-gated (kimi-k2.6 thread).
- **429/timeout?** Free-tier capacity: exponential backoff, `reasoning_effort=low`,
  smaller `max_tokens`, or a paid key. Not a dead model.
- **401?** Key/entitlement problem, never a model problem.
