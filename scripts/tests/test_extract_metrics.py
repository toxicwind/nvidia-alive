"""Fixture-based tests for scripts/extract-metrics.py (nested GuideLLM metrics)."""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve()
SCRIPT = HERE.parent.parent / "extract-metrics.py"

spec = importlib.util.spec_from_file_location("extract_metrics", SCRIPT)
em = importlib.util.module_from_spec(spec)
spec.loader.exec_module(em)


def _metric(mean, median, p50, total_sum, count):
    return {
        "successful": {
            "mean": mean,
            "median": median,
            "std_dev": 1.0,
            "min": 0.5,
            "max": 9.9,
            "count": count,
            "total_sum": total_sum,
            "percentiles": {"p50": p50, "p99": 9.9},
        }
    }


def _req(status, error=None):
    return {"info": {"status": status, "error": error, "request_id": "r1"}}


def make_doc(tmp_path: Path, name="res.json", **over):
    doc = {
        "config": {
            "metadata": {
                "provider": "herd",
                "model": "beellama/exaone-4-0-1-2b-q4km",
                "name": "general-chat-test",
            }
        },
        "benchmarks": [
            {
                "duration": 91.0,
                "metrics": {
                    "request_totals": {
                        "successful": 44,
                        "errored": 5,
                        "incomplete": 1,
                        "total": 50,
                    },
                    "time_to_first_token_ms": _metric(98.6, 88.9, 88.9, 4341.0, 44),
                    "inter_token_latency_ms": _metric(3.7, 3.2, 3.2, 83527.0, 22484),
                    "output_tokens_per_second": _metric(247.4, 299.6, 299.6, 5574947.0, 22528),
                    "requests_per_second": _metric(0.48, 0.48, 0.48, 24.0, 50),
                    "prompt_token_count": _metric(1036.0, 1036.0, 1036.0, 45584.0, 44),
                    "output_token_count": _metric(512.0, 512.0, 512.0, 22528.0, 44),
                },
                "requests": {
                    "successful": [_req("successful") for _ in range(2)],
                    "errored": [
                        _req("errored", "HTTPStatusError(\"Server error '502 Bad Gateway'\")"),
                        _req("errored", "HTTPStatusError(\"Server error '502 Bad Gateway'\")"),
                        _req("errored", "TimeoutError()"),
                    ],
                    "incomplete": [_req("incomplete", "CancelledError()")],
                    "total": 50,
                },
            }
        ],
    }
    doc.update(over)
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


def test_full_row(tmp_path):
    row = em.summarize(make_doc(tmp_path))
    assert row["provider"] == "herd"
    assert row["model"] == "beellama/exaone-4-0-1-2b-q4km"
    assert (row["successful"], row["errored"], row["incomplete"], row["total"]) == (44, 5, 1, 50)
    assert row["duration_s"] == 91.0
    assert row["ttft_mean_ms"] == 98.6
    assert row["ttft_p50_ms"] == 88.9
    assert row["itl_mean_ms"] == 3.7
    assert row["out_tps_mean"] == 247.4
    assert row["req_per_s"] == 0.48
    assert row["prompt_tokens_total"] == 45584.0
    assert row["output_tokens_total"] == 22528.0
    assert row["prompt_tps_overall"] == 45584.0 / 91.0
    assert row["statuses"] == {"errored": 3, "incomplete": 1}
    errs = {e["error"]: e["count"] for e in row["errors"]}
    assert errs["HTTPStatusError(\"Server error '502 Bad Gateway'\")"] == 2
    assert errs["TimeoutError()"] == 1
    assert errs["CancelledError()"] == 1


def test_missing_sections_tolerated(tmp_path):
    row = em.summarize(make_doc(tmp_path, metrics_missing=True))
    # benchmarks[0] has no metrics/requests keys at all
    doc = json.loads((tmp_path / "res.json").read_text())
    del doc["benchmarks"][0]["metrics"]
    del doc["benchmarks"][0]["requests"]
    p = tmp_path / "bare.json"
    p.write_text(json.dumps(doc))
    row = em.summarize(p)
    assert row["successful"] == 0
    assert row["ttft_mean_ms"] is None
    assert row["errors"] == []
    assert "parse_error" not in row


def test_no_benchmarks_is_parse_error(tmp_path):
    p = make_doc(tmp_path, benchmarks=[])
    row = em.summarize(p)
    assert "parse_error" in row


def test_malformed_json_is_parse_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    row = em.summarize(p)
    assert "parse_error" in row


def test_markdown_and_csv_render(tmp_path):
    rows = [em.summarize(make_doc(tmp_path))]
    md = em.to_markdown(rows)
    assert "| herd | beellama/exaone-4-0-1-2b-q4km |" in md
    assert "44/5/1/50" in md
    csv_text = em.to_csv(rows)
    assert "ttft_mean_ms" in csv_text.splitlines()[0]
    assert "beellama/exaone-4-0-1-2b-q4km" in csv_text


def test_list_counts_and_mismatch_flag(tmp_path):
    # fixture: aggregates (44/5/1/50) disagree with list lengths (2/3/1)
    row = em.summarize(make_doc(tmp_path))
    assert (row["list_successful"], row["list_errored"], row["list_incomplete"]) == (2, 3, 1)
    assert row["count_mismatch"] is True
    md = em.to_markdown([row])
    assert "[lists: 2/3/1]" in md


def test_matching_counts_no_mismatch(tmp_path):
    p = make_doc(tmp_path)
    doc = json.loads(p.read_text())
    b = doc["benchmarks"][0]
    b["requests"] = {
        "successful": [_req("successful") for _ in range(44)],
        "errored": [_req("errored") for _ in range(5)],
        "incomplete": [_req("incomplete")],
    }
    p.write_text(json.dumps(doc))
    row = em.summarize(p)
    assert row["count_mismatch"] is False
    assert "[lists:" not in em.to_markdown([row])
