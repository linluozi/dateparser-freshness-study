#!/usr/bin/env python3
"""Measure dateparser.parse() on a corpus of real date strings.

Each implementation runs in its own process with its own checkout on PYTHONPATH,
so the baseline and the patched tree can never shadow each other.
"""
import argparse
import json
import os
import platform
import random
import resource
import statistics
import sys
import time

SEED = 20261115
UPSTREAM_COMMIT = "1fdf5da3bb96dead01d3ec2777218951a9d1a46b"


def cpu_model():
    try:
        for line in open("/proc/cpuinfo", encoding="utf-8"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="checkout of dateparser to import")
    ap.add_argument("--impl", required=True, choices=["baseline", "optimized"])
    ap.add_argument("--workload", default="all", choices=["all", "simple"])
    ap.add_argument("--corpus", default=os.path.join(os.path.dirname(__file__), "corpus", "dates.json"))
    ap.add_argument("--scales", default="50,150,400")
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw-dir", required=True)
    args = ap.parse_args()

    sys.path.insert(0, os.path.abspath(args.src))
    import dateparser

    corpus = json.load(open(args.corpus, encoding="utf-8"))["strings"]
    if args.workload == "simple":
        corpus = [s for s in corpus if s.isascii() and len(s) <= 40]
    random.Random(SEED).shuffle(corpus)
    os.makedirs(args.raw_dir, exist_ok=True)

    # One untimed call so lazy locale imports are not charged to the first sample.
    dateparser.parse("2015-06-01")

    results = []
    for scale in [int(x) for x in args.scales.split(",")]:
        texts = corpus[:scale]
        for _ in range(args.warmup):
            for s in texts:
                dateparser.parse(s)
        samples = []
        for i in range(args.reps):
            t0 = time.perf_counter()
            for s in texts:
                dateparser.parse(s)
            elapsed = time.perf_counter() - t0
            rec = {
                "impl": args.impl,
                "workload": args.workload,
                "scale": scale,
                "n": len(texts),
                "rep": i,
                "elapsed_s": elapsed,
                "us_per_call": elapsed / len(texts) * 1e6,
            }
            with open(os.path.join(args.raw_dir, f"{args.impl}-{args.workload}-{scale}-{i}.json"), "w") as f:
                json.dump(rec, f)
            samples.append(rec["us_per_call"])
        ordered = sorted(samples)
        results.append({
            "scale": scale,
            "n": len(texts),
            "median_us": statistics.median(samples),
            "p25_us": ordered[len(ordered) // 4],
            "p75_us": ordered[(3 * len(ordered)) // 4],
            "rsd_pct": (statistics.stdev(samples) / statistics.mean(samples) * 100) if len(samples) > 1 else 0.0,
            "samples_us": samples,
        })
        print(f"{args.impl:9s} {args.workload:6s} n={len(texts):4d} median={results[-1]['median_us']:.1f} us/call")

    payload = {
        "impl": args.impl,
        "workload": args.workload,
        "upstream_commit": UPSTREAM_COMMIT,
        "seed": SEED,
        "corpus_size": len(corpus),
        "command": " ".join([sys.executable] + sys.argv),
        "python": sys.version.split()[0],
        "cpu": cpu_model(),
        "mem_kb": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 1024,
        "rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "warmup": args.warmup,
        "reps": args.reps,
        "results": results,
    }
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
