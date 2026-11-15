"""Artifact integrity checks; runs without an upstream checkout."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    with open(os.path.join(ROOT, "benchmark", name), encoding="utf-8") as f:
        return json.load(f)


def test_corpus_is_unique_and_real():
    data = load("corpus/dates.json")
    assert len(data["strings"]) == 1859
    assert len(set(data["strings"])) == 1859


def test_both_workloads_cover_three_scales():
    for impl in ("baseline", "optimized"):
        for workload in ("all", "simple"):
            payload = load(f"{impl}-{workload}.json")
            assert [r["scale"] for r in payload["results"]] == [50, 150, 400]
            for r in payload["results"]:
                assert r["p25_us"] <= r["median_us"] <= r["p75_us"]
                for i in range(5):
                    raw = load(os.path.join("raw", f"{impl}-{workload}-{r['scale']}-{i}.json"))
                    assert raw["n"] == r["scale"]


def test_diff_report_has_no_mismatch():
    report = load("diff_report.json")
    assert report["independent_inputs"] >= 1000
    assert report["mismatches"] == 0


def test_patch_is_one_small_hunk():
    text = open(os.path.join(ROOT, "patch.diff"), encoding="utf-8").read()
    assert sum(1 for l in text.splitlines() if l.startswith("@@")) == 1
    added = sum(1 for line in text.splitlines() if line.startswith("+") and not line.startswith("+++"))
    assert added <= 10
