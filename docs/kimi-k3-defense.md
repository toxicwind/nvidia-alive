# kimi-defender: moonshotai/kimi-k3 is ALIVE on NVIDIA NIM

**Verdict: ALIVE** (capacity-flaky, not dead) — confidence **80/100**

The "kimi-k3 is broken on NIM" narrative is a misdiagnosis. The model is
officially listed, probe-verified by third parties, and exhibits the exact
failure signature of a capacity-constrained endpoint — not a dead one.
Our own prober's TimeoutError is best explained as a methodology artifact:
a 25s per-lane ceiling applied to a model with documented 1–46s latency.

## 5 strongest evidence bullets

1. **Official listing + live API reference.** build.nvidia.com/moonshotai/kimi-k3
   model card officially listed 2026-08-28; docs.api.nvidia.com/nim/reference/moonshotai-kimi-k3
   API reference live. (exa search, 2026-09-20)

2. **Third-party probe-passed matrix (Tibbee/pi-nvidia-nim-provider).**
   kimi-k3 probe-verified 2026-08-27: text/image input, 1,048,576-token context,
   OpenAI-format tool calls, `chat_template_kwargs.thinking` on/off,
   `reasoning_content`, streaming, vision — ALL probe-passed. In the
   "16 curated models verified live against hosted NIM as of 2026-09-16" set.
   (https://github.com/Tibbee/pi-nvidia-nim-provider/ README)

3. **Documented 1–46s latency explains our TimeoutError.** The same README warns:
   kimi-k3 "is near unusable at times — probe latency ranged from 1 s to 46 s
   for the same request and the free-tier endpoint repeatedly rate-limits (429)
   in bursts... treat it as a capacity-constrained endpoint." Our prober used a
   25s per-lane ceiling + 1s provider rate gate. A timeout under a 25s ceiling
   on a model whose observed latency reaches 46s is not a death certificate —
   it is a ceiling artifact.

4. **404s are a NIM account/provisioning artifact, not model death.** NVIDIA
   forums: "Access to Kimi-K2.6 restricted for my account", "Request to enable
   Public API Endpoints for my account", "404 Function not found for account".
   GLM-5.3 Flash answered 404 "Function ...: Not found for account" on ~1 in 3
   requests during rollout — then the 404s stopped reproducing on 2026-09-17.
   (Tibbee README; forums.developer.nvidia.com threads 377223/377225/379578/378046)

5. **NIM's retirement signal is explicit 410 Gone — kimi-k3 has none.**
   Retired models (Step-3.7 Flash 2026-08-28, Nemotron 3 Nano 2026-09-01,
   GPT-OSS 120B 2026-09-03, MiniMax M3 2026-09-09, DeepSeek V4 Pro 0813
   2026-09-14) answer 410 with an explicit end-of-life date. kimi-k3 answers
   neither 410 nor instant-404; our probe timed out instead — the signature of
   queueing/capacity, and the /v1/models catalog still lists it among the 82
   entitled models. (Tibbee README "Retired on the hosted endpoint" section;
   our prober run 2026-09-20)

## 2 strongest counterarguments + rebuttals

**C1: Our own prober — purpose-built, 82 models, 105s — classified kimi-k3 dead
(TimeoutError) and kimi-k2.6 dead (404). Empirical, our own key.**
→ Rebuttal: the prober's parameters defeat it for this model class. 25s ceiling
vs documented 46s latency; 8 workers × 1s gate on a free tier that burst-429s
(40 req/min nominal per Tibbee, but repeated burst 429s documented; one
reporter describes 24h soft-locks after draining daily quota). The prober got
instant 200s from other models (197ms–1.2s), proving our lane was healthy —
kimi-k3's timeout is endpoint-specific slowness, not our network. And the
k2.6 instant-404 vs k3 timeout is itself informative: instant 404 = routing/
entitlement rejection; timeout = the request was accepted and queued.

**C2: Forums + our herd history say Kimi has been dead for weeks
(401 "User not found", "people online think kimi k3 is broken").**
→ Rebuttal: conflates three separate failures. (a) The 401 saga was
OpenRouter/Moonshot credentials — a different provider, irrelevant to NIM.
(b) kimi-k2.6 is the older prototype; its 404s are documented per-account
entitlement issues and it appears in NO probe-passed matrix — conceded as
gone/gated. (c) For kimi-k3, "broken" reports describe capacity flakiness
(429s, multi-minute turns) misread as death — exactly what Tibbee warns about.
Flaky ≠ dead; the dated probe matrix (thinking/tools/streaming/vision all
probe-passed) is ground truth.

## kimi-k2.6 concession (per brief)

Concede: k2.6 is not a useful target — instant 404, no probe-passed evidence
anywhere, older prototype superseded by k3. Whether removed or permanently
account-gated, it is out of scope. k3 is the live flagship.

## Decisive re-probe experiment

Run on yote (`/home/toxic/nvidia-alive/`), NVIDIA_API_KEY from ~/.secrets
(names only in logs, never values):

- **Target:** POST https://integrate.api.nvidia.com/v1/chat/completions
- **Payload:** {"model":"moonshotai/kimi-k3","messages":[{"role":"user","content":"ping"}],"max_tokens":1,"temperature":0}
- **Timeout:** 180s per attempt (covers documented 46s + queueing headroom;
  peers have stalled 150s+)
- **Attempts:** 5, exponential backoff 5s→10s→20s→40s→80s + jitter
- **429 handling:** honor Retry-After header (cap 300s); a 429 counts as
  "endpoint alive, quota-hit" — NOT failure
- **Rate discipline:** sequential, single worker, ≥30s between attempts
  (stay clear of burst-429 territory)
- **Schedule:** once during US daytime peak, once off-peak; record both
- **Contrast probe:** moonshotai/kimi-k2.6 once with identical rig
  (expect instant 404 — confirms the 404-vs-timeout distinction)

**Verdict criteria:**
- ≥1 attempt → HTTP 200 + non-empty choices[] → **ALIVE** (record latency)
- All attempts → 410 Gone → **DEAD** (retired)
- Persistent 404 "Function not found for account" while other models 200 →
  **account-gated**, not model-dead (escalate: enable Public API Endpoints)
- All attempts timeout at 180s → **capacity-starved** (inconclusive-degraded;
  extend window, do not declare dead)

**Log:** append JSONL to ~/.local/share/nvidia-alive/kimi-k3-reprobe.jsonl:
{ts, attempt, status, latency_ms, reason}

## Note on the model-card point

Chris is right that every model has a NIM model card AND a HuggingFace card
and the confusion is rampant — but with a caveat from Tibbee's README: build
cards return HTTP 200 even for 410-retired models, so "the live aliveness
sweep — not the card — is the liveness signal." Card = necessary (official
listing, request contract, effort ladders), sweep with sane ceilings =
sufficient. Our sweep just needs the ceiling fix above.
