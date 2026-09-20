# Solved findings

Three mysteries from the September 2026 endpoint audit, resolved with live
endpoint evidence. Rule of the project: **don't trust providers — only
endpoints.** Every claim below comes from a request we actually sent.

## 1. moonshotai/kimi-k2.6 404 = per-account entitlement gating, not retirement

`POST https://integrate.api.nvidia.com/v1/chat/completions` with
`{"model": "moonshotai/kimi-k2.6", ...}` returns **HTTP 404** with an NVCF
function UUID in the body: `23d4f03a-b8a6-4adb-a183-7daa083a09cc`, and the
message "Not found for account".

What we proved (`scripts/kimi-id-fuzz.py`, `scripts/kimi-final-probe.py`):

- 20 ID variants fuzzed across `/v1/chat/completions` and `/v1/completions`.
  Only the exact ID `moonshotai/kimi-k2.6` reaches NVCF function lookup;
  variants 404 at the routing layer. `/v1/completions` is not a valid NIM
  path — `/v1/chat/completions` is.
- Five working NVIDIA keys return the **same** account-gated function 404.
- A genuinely retired control, `moonshotai/kimi-k2-thinking`, returns
  **HTTP 410** with an explicit end-of-life date (`2026-05-12`).
- The same function UUID appears in NVIDIA forum reports from July–August
  2026 (e.g. forums.developer.nvidia.com, 2026-08-05).

Conclusion: k2.6 is registered, correctly addressed, not retired, not
client-fixable — it is **entitlement-gated for the org**. Fix requires
NVIDIA support enabling function `23d4f03a-b8a6-4adb-a183-7daa083a09cc`
for the account (needs a logged-in NVIDIA account; not filed).
`moonshotai/kimi-k2.5` was never in the catalog (routing-level 404).

Prober verdict: `entitlement_gated`. Dead-UUID registry: a ghost-UUID guard
should block these IDs before route insertion.

## 2. moonshotai/kimi-k3 = CAPACITY_STARVED (not dead, not async)

Observed: 117,970 ms, 159.6 s, 143.7 s to first byte. The instinct is "slow
model". Wrong. Packet-level timing (`scripts/kimi-k3-timing.py`,
`scripts/pcap-analyze.py`) shows:

| phase            | fast control | kimi-k3        |
|------------------|-------------|----------------|
| DNS + TCP + TLS  | ~77 ms      | ~58 ms         |
| server silence   | 0.4–1.1 s   | **143–159 s**  |
| generation       | ~0.5 s      | **~0.2 s**     |

The pcap shows 142.7 s of absolute wire silence after the server ACKs the
POST — no retransmissions, no dup ACKs beyond the first 66 ms. When bytes
finally arrive: 9 chunks, 33 reasoning characters, in 0.2 s. A repeat
request launched one minute after a success still waited ~143 s.

Then the sharper test — live NVCF probes with `NVCF-POLL-SECONDS: 30` and
`: 60` on the chat route returned **HTTP 504 at 32 s / 62 s *with* an
`nvcf-reqid` issued**. That combination is decisive: the control plane
**accepted** the invocation (function exists, key entitled) but no worker
picked it up inside the polling window. Per NVIDIA docs, that is exactly
what 504 means — zero warm capacity. Meanwhile `GET /v2/nvcf/functions`
shows 202 functions visible on the key, 111 ACTIVE, including 5 ACTIVE
kimi-k3 functions. Present in the registry, entitled, and still nobody
home: scale-to-zero with no documented keep-warm guarantee, cold
provisioning (GPU alloc + ~1.4 TB MXFP4 weight load + engine warmup for the
2.8 T-param model) on every invocation.

Killed hypotheses, so nobody re-litigates them:

- **Async/202 is DEAD.** No 202 ever came back on
  `integrate.api.nvidia.com/v1/chat/completions`. The route holds the
  connection (server-side long-poll) instead of returning 202+requestId.
  Do not build a 202+poll flow against the chat route. (The async 202+REQID
  contract belongs to `ai.api.nvidia.com/v1/genai/...`, a different API.)
- **Death is DEAD.** No 404 — the function is registered and entitled.
- **`NVCF-AI-Resource` header = NO-OP** (tested; changes nothing).
- **401 AND 403 both mean auth failure** (live-verified; NIM returns 403
  for auth-scope problems, not just 401).

Conclusion: kimi-k3 is **capacity-starved** (`capacity_starved` verdict).
Do not mix it into ordinary throughput benchmarks without
labeling/excluding the queue time.

Open (not yet wired): a ghost-UUID guard exists (`dead_uuids.json`, 3
entries, incl. the k2.6 function UUID) but is **not yet wired into Herd's
route-insertion path** — the insertion source is still unidentified. This
is a bridge-recovery task; do not claim the guard is live.

## 3. NIM is three APIs — and only one of them is honest

Harvested from 25 repos (ast-grep) plus live probes:

1. `integrate.api.nvidia.com/v1` — the friendly chat route. Lies by
   omission: catalog 404s don't distinguish "never existed" from
   "not entitled for your account".
2. `api.nvcf.nvidia.com/v2/nvcf` — the **honest** API. `/functions` lists
   exactly what *your key* can invoke, per-function status included.
   Authenticated; this is the source of truth for entitlement questions.
3. `ai.api.nvidia.com/v1/genai/...` — the async route (202 + REQID).
   The chat route does not do 202; don't conflate the two.

Other classification notes baked into `scripts/prober.py`:

- NIM auth failure is **403 as well as 401** — map both to `auth`.
- HTTP 200 with empty `content` but non-empty `reasoning_content`,
  `finish_reason: "length"`, and reasoning-token usage is **alive** — the
  old `max_tokens=5` sweep false-negatived reasoning models. Classify on
  content + reasoning_content + finish_reason + usage, never content alone.
- `quota` (429/402/quota-403) ≠ `dead`: reachable but wallet-gated.
- `timeout`/5xx = `flaky` (quarantine, re-probe), not dead.
- "Public API Endpoints" is a **key-creation-time scope** — a scope-less
  key can't be repaired, only replaced. (Observed: two NVIDIA keys list
  models with 200 but 401 on completions.)

## Verdict taxonomy (prober v2)

`alive` · `quota` · `auth` · `dead` · `entitlement_gated` ·
`capacity_starved` (`queue_gated` in older output) · `retired` ·
`bad_request` · `flaky`
