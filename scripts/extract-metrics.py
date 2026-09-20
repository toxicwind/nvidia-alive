#!/usr/bin/env python3
"""extract-metrics.py — summarize GuideLLM benchmark result JSONs.

Reads one or more GuideLLM result files (kind=json output from bench.sh)
and emits a compact per-model summary with:

- request counts (successful / errored / incomplete / total)
- benchmark duration (s)
- TTFT mean + p50 (ms), inter-token latency mean + p50 (ms)
- output tokens/s mean + p50, requests/s
- prompt/output token totals + overall throughput
- exact error strings (deduplicated with counts) from errored/incomplete
  requests (requests.*[].info.error), plus observed request statuses

Usage:
    scripts/extract-metrics.py <result.json> [more.json ...]
    scripts/extract-metrics.py --results-dir bench/ --json out.json --csv out.csv --md out.md

Exit 0 even when some files fail to parse; failures are reported on stderr
and recorded in the JSON output as {"file": ..., "parse_error": ...}.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter
from pathlib import Path


def _succ(section: dict) -> dict:
    """Return the 'successful' stats block of a metric section, or {}."""
    if not isinstance(section, dict):
        return {}
    s = section.get("successful")
    return s if isinstance(s, dict) else {}


def _p50(stats: dict):
    pct = stats.get("percentiles") or {}
    if not isinstance(pct, dict):
        return None
    for key in ("p50", "p500", "50", "0.5"):
        if key in pct:
            return pct[key]
    # fall back to median
    return stats.get("median")


def _num(x):
    return x if isinstance(x, (int, float)) else None


def summarize(path: Path) -> dict:
    """Summarize one GuideLLM result JSON. Never raises on bad input."""
    row: dict = {"file": str(path)}
    try:
        doc = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        row["parse_error"] = f"{type(exc).__name__}: {exc}"
        return row

    meta = ((doc.get("config") or {}).get("metadata")) or {}
    row["provider"] = meta.get("provider")
    row["model"] = meta.get("model")
    row["benchmark_name"] = meta.get("name")
    row["description"] = meta.get("description")

    benches = doc.get("benchmarks") or []
    if not benches:
        row["parse_error"] = "no benchmarks[] entries"
        return row
    b = benches[0]
    metrics = b.get("metrics") or {}

    totals = metrics.get("request_totals") or {}
    row["successful"] = totals.get("successful", 0)
    row["errored"] = totals.get("errored", 0)
    row["incomplete"] = totals.get("incomplete", 0)
    row["total"] = totals.get("total", 0)
    row["duration_s"] = _num(b.get("duration"))

    ttft = _succ(metrics.get("time_to_first_token_ms"))
    row["ttft_mean_ms"] = _num(ttft.get("mean"))
    row["ttft_p50_ms"] = _num(_p50(ttft))

    itl = _succ(metrics.get("inter_token_latency_ms"))
    row["itl_mean_ms"] = _num(itl.get("mean"))
    row["itl_p50_ms"] = _num(_p50(itl))

    otps = _succ(metrics.get("output_tokens_per_second"))
    row["out_tps_mean"] = _num(otps.get("mean"))
    row["out_tps_p50"] = _num(_p50(otps))

    rps = _succ(metrics.get("requests_per_second"))
    row["req_per_s"] = _num(rps.get("mean"))

    prompt_tok = _succ(metrics.get("prompt_token_count"))
    output_tok = _succ(metrics.get("output_token_count"))
    row["prompt_tokens_total"] = _num(prompt_tok.get("total_sum"))
    row["output_tokens_total"] = _num(output_tok.get("total_sum"))
    dur = row["duration_s"]
    if dur:
        row["prompt_tps_overall"] = (
            row["prompt_tokens_total"] / dur if row["prompt_tokens_total"] else None
        )
        row["output_tps_overall"] = (
            row["output_tokens_total"] / dur if row["output_tokens_total"] else None
        )
    else:
        row["prompt_tps_overall"] = None
        row["output_tps_overall"] = None

    # Exact errors + statuses from errored/incomplete request lists.
    # Also record raw list lengths: they can disagree with aggregate totals.
    err_counter: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    reqs = b.get("requests") or {}
    list_counts = {}
    for bucket in ("successful", "errored", "incomplete"):
        items = reqs.get(bucket) or []
        list_counts[bucket] = len(items)
    row["list_successful"] = list_counts["successful"]
    row["list_errored"] = list_counts["errored"]
    row["list_incomplete"] = list_counts["incomplete"]
    row["count_mismatch"] = (
        list_counts["successful"] != row["successful"]
        or list_counts["errored"] != row["errored"]
        or list_counts["incomplete"] != row["incomplete"]
    )
    for bucket in ("errored", "incomplete"):
        items = reqs.get(bucket) or []
        for item in items:
            info = (item or {}).get("info") or {}
            st = info.get("status")
            if st:
                statuses[str(st)] += 1
            err = info.get("error")
            if err:
                err_counter[str(err).strip()] += 1
    row["statuses"] = dict(statuses)
    row["errors"] = [
        {"count": c, "error": e} for e, c in err_counter.most_common()
    ]
    return row


def to_markdown(rows: list[dict]) -> str:
    headers = [
        "provider", "model", "ok/err/inc/total", "dur_s",
        "ttft_mean/p50_ms", "itl_mean/p50_ms", "out_tps_mean/p50",
        "req_s", "prompt_tok", "out_tok", "errors",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]

    def f(x, nd=2):
        return "—" if x is None else f"{x:.{nd}f}"

    def pair(a, b, nd=2):
        return "—" if a is None and b is None else f"{f(a, nd)}/{f(b, nd)}"

    for r in rows:
        if r.get("parse_error"):
            lines.append(f"| {r['file']} | PARSE ERROR: {r['parse_error']} |" + " |" * (len(headers) - 2))
            continue
        err_s = "; ".join(
            f"({e['count']}x) {e['error'][:90]}" for e in r.get("errors", [])
        ) or "—"
        counts = f"{r.get('successful')}/{r.get('errored')}/{r.get('incomplete')}/{r.get('total')}"
        list_counts = (
            f"{r.get('list_successful')}/{r.get('list_errored')}/{r.get('list_incomplete')}"
        )
        if r.get("count_mismatch"):
            counts += f" [lists: {list_counts}]"
        lines.append(
            "| " + " | ".join([
                str(r.get("provider") or "—"),
                str(r.get("model") or "—"),
                counts,
                f(r.get("duration_s"), 1),
                pair(r.get("ttft_mean_ms"), r.get("ttft_p50_ms")),
                pair(r.get("itl_mean_ms"), r.get("itl_p50_ms")),
                pair(r.get("out_tps_mean"), r.get("out_tps_p50")),
                f(r.get("req_per_s"), 3),
                str(r.get("prompt_tokens_total") or "—"),
                str(r.get("output_tokens_total") or "—"),
                err_s,
            ]) + " |"
        )
    return "\n".join(lines) + "\n"


CSV_FIELDS = [
    "file", "provider", "model", "benchmark_name",
    "successful", "errored", "incomplete", "total", "duration_s",
    "list_successful", "list_errored", "list_incomplete", "count_mismatch",
    "ttft_mean_ms", "ttft_p50_ms", "itl_mean_ms", "itl_p50_ms",
    "out_tps_mean", "out_tps_p50", "req_per_s",
    "prompt_tokens_total", "output_tokens_total",
    "prompt_tps_overall", "output_tps_overall",
    "statuses", "error_count", "errors", "parse_error",
]


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        flat = dict(r)
        flat["statuses"] = json.dumps(flat.get("statuses", {}))
        flat["error_count"] = len(flat.get("errors", []))
        flat["errors"] = json.dumps(flat.get("errors", []))
        w.writerow(flat)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*", help="GuideLLM result JSON files")
    ap.add_argument("--results-dir", help="directory scanned for *.json")
    ap.add_argument("--json", dest="json_out", help="write JSON summary here")
    ap.add_argument("--csv", dest="csv_out", help="write CSV summary here")
    ap.add_argument("--md", dest="md_out", help="write Markdown table here")
    args = ap.parse_args()

    paths: list[Path] = [Path(f) for f in args.files]
    if args.results_dir:
        paths.extend(sorted(Path(args.results_dir).glob("*.json")))
    if not paths:
        print("no input files", file=sys.stderr)
        return 2

    rows = []
    for p in paths:
        r = summarize(p)
        if r.get("parse_error"):
            print(f"WARN {p}: {r['parse_error']}", file=sys.stderr)
        rows.append(r)

    # markdown always goes to stdout unless --md given
    md = to_markdown(rows)
    if args.md_out:
        Path(args.md_out).write_text(md)
        print(f"wrote {args.md_out}")
    else:
        sys.stdout.write(md)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2))
        print(f"wrote {args.json_out}", file=sys.stderr)
    if args.csv_out:
        Path(args.csv_out).write_text(to_csv(rows))
        print(f"wrote {args.csv_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
