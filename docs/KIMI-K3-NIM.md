# kimi-k3 on NVIDIA NIM: investigation, debate, and plan

Date: 2026-09-20. Question from Chris: every NIM model has a specific model
card on build.nvidia.com AND HuggingFace, nobody seems to realize it, we made
kimi-k3 work on herd, and people online think kimi-k3 is broken for NIM — dig
deeper, write it up, run a debate.

## TL;DR

- **kimi-k3 is NOT dead on NVIDIA NIM.** Card live
  (build.nvidia.com/moonshotai/kimi-k3), API reference live, still in the
  `/v1/models` catalog, no 410 retirement signal. kimi-k2.6 IS gone (instant
  404, multiple sources confirm removal).
- **But it IS capacity-starved on the free tier**: documented 1–46s latency
  for the same request, burst 429s (~2 req/min free tier), per-account
  provisioning 404s. Our prober's TimeoutError was very likely a methodology
  artifact (25s ceiling vs 46s documented latency).
- **Chris's model-card thesis checked out (~65% of "broken" reports):** NIM
  id ≠ HF id (`moonshotai/kimi-k3` vs `moonshotai/Kimi-K3` — this is exactly
  what broke our guidellm smoke test), immutable penalties 400 if sent,
  client-side endpoint-path bugs (OpenClaw #8319: direct curl 200s while the
  provider routing 404s), per-account entitlement 404s.
- **Caveat (both directions):** build cards return HTTP 200 even for
  410-retired models. Card = necessary (the request contract), live sweep =
  sufficient (liveness). Neither alone is truth.
- **Operational verdict:** keep kimi-k3 OUT of the automated alive set for
  now (GuideLLM/bench routing) — not because it's dead, but because it can't
  meet a sane fail-fast ceiling. It moves to a **quarantine/flaky** list
  pending the re-probe experiment below.

## The debate

Three debaters, full research context, each allowed 4 extra searches.

| Debater | Position | Verdict | Confidence |
|---|---|---|---|
| kimi-prosecutor | It's operationally dead; the alive filter was right | BROKEN | 85 |
| kimi-defender | Alive but capacity-flaky; our probe misclassified it | ALIVE | 80 |
| kimi-card | The card thesis: ~65% misconfiguration/entitlement, ~35% real capacity pain, ~0% model death | THESIS HOLDS | 80 |

Full positions: `kimi-k3-defense.md`, `kimi-k3-debate-kimi-card.md` (this dir).
The prosecutor filed no separate doc; its argument is folded into this MD.

### Prosecutor's strongest points (steelmanned)
1. Our own prober (82 models, 8 lanes, 25s ceiling): kimi-k3 →
   TimeoutError, kimi-k2.6 → HTTP 404. 11/82 passed. The filter did its job.
2. Independent sweep (tibbee/pi-nvidia-nim-provider, 2026-08-27, README
   current): kimi-k3 "probe-verified" but "near unusable at times", 1–46s
   latency, repeated burst 429s. Two independent filters, same conclusion.
3. Forum arc is months of degradation, not an incident: "Is kimi k3 removed
   AGAIN?" (08-26), "responses degraded" (08-26), "Is Kimi doing this w
   everyone else?" (09-09). kimi-k2.6 walked the same path to removal.
4. Five 410-retired models keep 200 cards — card-exists ≠ alive, and
   kimi-k3 was itself "live on the API but unlisted on the build page" before
   08-28. Cards and endpoints disagree in both directions.
5. Free-tier strangling rounds effective throughput to zero for any automated
   consumer. "Flaky" past a threshold is operationally dead.

### Defender's strongest points (steelmanned)
1. Official listing + live API reference (docs.api.nvidia.com/nim/reference/
   moonshotai-kimi-k3-infer). Retirement on NIM is an explicit 410 with an
   EOL date — kimi-k3 has none.
2. Third-party probe-passed matrix: text/image, 1M context, tools, vision,
   thinking toggle, reasoning_content — all probe-passed 2026-08-27, in the
   "16 curated models verified live as of 2026-09-16" set.
3. Documented 46s latency + our 25s ceiling = our TimeoutError is a ceiling
   artifact, not a death certificate. 8 workers × 1s gate on a 2-req/min
   free tier manufactured the failure.
4. 404s are per-account provisioning ("enable Public API Endpoints for my
   account", "restricted for my account") — GLM-5.3 Flash 404'd "not found
   for account" on ~1/3 requests during rollout, then the 404s stopped
   reproducing. Account problem, not model problem.
5. k2.6's *instant* 404 vs k3's *timeout* is itself informative: 404 =
   routing/entitlement rejection; timeout = request accepted and queued.

### Card debater's strongest points (steelmanned)
1. OpenClaw #8319: same key, direct curl → 200; OpenClaw provider routing →
   404. Client-side endpoint-path bug reported as "NVIDIA broken".
2. bauka0 changelog: Kimi K3 400s because presence_penalty/frequency_penalty
   are IMMUTABLE (card-fixed at 0). Clients send defaults → 400 → "broken".
3. tibbee scrapes card metadata (tools/fetch_nim_metadata.ts →
   models/metadata.json) because the card is the request contract: 1,048,576
   context, reasoning_effort ∈ {low, high, max} (default max), thinking
   always-on.
4. NIM id ≠ HF id broke OUR OWN tooling: guidellm smoke failed loading
   tokenizer `meta/muse-glimmer-30b` from HF. Verified: NIM
   `moonshotai/kimi-k3` → HF `moonshotai/Kimi-K3` (case differs).
5. "We made kimi k3 work on herd" — sharpened honestly: every Kimi failure
   we logged was credential/routing-layer (401s, mispointed routes), never a
   model-side 410/deprecation. Absence of a working demo ≠ evidence of death.

## Synthesis: what actually happened

kimi-k3 is officially listed, not retired, but **capacity-starved on the
free tier**. The "it's broken" narrative is three confusions stacked on top
of real pain:

1. **Real capacity pain** (the ~35%): 1–46s latency for the same request,
   burst 429s on a ~2 req/min free tier, intermittent timeouts. September
   2026 forum threads show this persisting for weeks.
2. **Per-account entitlement 404s** (part of the ~65%): "404 Function not
   found for account" hits some accounts and not others; "enable Public API
   Endpoints for my account" threads. An account problem wearing a model
   problem's clothes.
3. **Client/config errors** (the rest of the ~65%): immutable penalties sent
   → HTTP 400; OpenClaw-class endpoint-path bugs → 404 with a good key;
   NIM id used where the HF id belongs → tokenizer/model-load failures
   (this exact bug killed our guidellm smoke test ten minutes before the
   debate started).

Plus our own contribution: the prober's 25s ceiling + 1s rate gate vs a
46s-latency model manufactured a TimeoutError we reported as signal.

**The card thesis, refined:** Chris is right that every model has a NIM card
and an HF card and nobody checks. The debate added the other half: **the
card is the request contract, the live sweep is the liveness signal, and
neither is sufficient alone** — five 410-retired models keep 200 cards, and
kimi-k3 itself was live-but-unlisted before 2026-08-28. Card-driven config
prevents misdiagnosis; only real requests establish aliveness.

**"We made kimi k3 work on herd," honest version:** we fixed the
routing/credential layer (restored the honest moonshotai/kimi-k3 mapping,
diagnosed the dead OpenRouter key). No verified working Kimi completion
exists anywhere right now: OpenRouter 402/404, HF 401, Pollinations
key-required for all Kimi IDs, no Moonshot key. Every Kimi failure logged was
credential/routing-layer, never a model-side 410. That's evidence the model
isn't dead — not evidence it works.

## The plan

1. **Re-probe kimi-k3 (running now, off-peak; peak-hours run later).** The
   defender's decisive experiment: 5 sequential attempts, 180s ceiling,
   429-aware backoff honoring Retry-After, ≥30s spacing (provider's measured
   2 req/min limit), k2.6 contrast probe. Verdict: ≥1 attempt → 200 with
   choices = ALIVE; all 410 = DEAD; "not found for account" 404s while other
   models 200 = account-gated; all timeouts = capacity-starved (extend, don't
   declare dead). Logs to
   `/home/toxic/.local/share/nvidia-alive/kimi-k3-reprobe.jsonl` on yote.
2. **Refactor the prober** (`prober.py`): remove the `time.sleep` rate gate
   (violates the no-artificial-sleeps doctrine) → event-driven bounded
   asyncio; 429 counts as alive-quota-hit, never dead; tri-state output
   (`alive` / `flaky-quarantine` / `dead`); per-model ceiling tiers instead
   of one global 25s.
3. **Card metadata layer**: scrape per-model build.nvidia.com cards into a
   metadata JSON — exact API IDs, param allowlists (immutable penalties!),
   context sizes, thinking toggles, reasoning_effort levels. This drives
   guidellm request building and bench.sh routing. Borrow the pattern from
   tibbee's `tools/fetch_nim_metadata.ts`; don't reinvent it.
4. **NIM-id → HF-repo mapping** for tooling: fixes guidellm tokenizers
   (the muse-glimmer smoke failure). Build it for the 11 alive models from
   their cards. Verified example: NIM `moonshotai/kimi-k3` → HF
   `moonshotai/Kimi-K3`.
5. **Quarantine semantics**: bench.sh consumes only the general-chat *alive*
   list. kimi-k3 sits in `flaky/` until it passes 3 consecutive daily probes
   or a 10-req smoke completes with <5% errors and p99 < 30s.
6. **GuideLLM smoke re-run** once the tokenizer mapping lands (step 4).

## Sources

- Exa answer 2026-09-20: card https://build.nvidia.com/moonshotai/kimi-k3,
  API ref https://docs.api.nvidia.com/nim/re/reference/moonshotai-kimi-k3,
  forum threads 381249, 382533, 382757, 377305
- tibbee/pi-nvidia-nim-provider README + commit 804b5ccc1536b0f2abb02405af48670e5ef61b68
  (independent aliveness sweep; "the live aliveness sweep — not the card —
  is the liveness signal")
- bauka0/nvidia-nim-provider CHANGELOG + CHANGELOG.dev.md (immutable
  penalties; Kimi K2.6 removal; 404/410 troubleshooting)
- NVIDIA Developer Forums: 381335 ("removed again"), 381947 ("Kimi K3
  Error"), 377225 (K2.6 account restriction), 379578 (404 enable request)
- OpenClaw discussion #8319 (endpoint-path 404 with working key)
- Our prober run 2026-09-20: 82 catalog / 11 alive / kimi-k3 TimeoutError /
  kimi-k2.6 HTTP 404
