#!/usr/bin/env python3
"""Differential test for the freshness fast-path patch.

Two independent processes import the two checkouts (``--run BASE OPT``) and dump
a canonical JSON record per input: the public ``dateparser.parse()`` result plus
the internal ``FreshnessDateDataParser._parse_with_parts()`` tuple.  The dumps
are then compared byte-for-byte per record.  Inputs are sha256-deduplicated and
the report states the number of independent samples, not the loop count.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORPUS = os.path.join(ROOT, "benchmark", "corpus", "dates.json")
REPORT = os.path.join(ROOT, "benchmark", "diff_report.json")

ADVERSARIAL = [
    "", " ", "\t\n", "—", "TBD", "v2.3.1", "Out of stock",
    "2015-06-01", "2015-06-01T13:00:00Z", "2015-06-01T13:00:00+05:30",
    "June 1, 2015", "1st of June 2015", "01/06/2015", "2015/06/01",
    "Mon, 01 Jun 2015 13:00:00 GMT", "2015-06-01 (UTC)",
    "2 hours ago", "in 5 minutes", "1 year, 2 months ago",
    "2 da[y]s ago", "2 [hours] ago", "3 (days) ago", "2 UTC hours ago",
    "2 hours ago UTC", "3 days ago +02:00", "the 1st of last month",
    "999999999999999999999999 days ago", "1" * 200 + " days ago",
    "２０１５-０６-０１", "2014年04月08日", "13 août 2014", "Le 11 Décembre 2014 à 09:00",
    "1 Ноябрь 2014", "hace 2 horas", "vor 3 Tagen", "now", "today", "tomorrow",
    "next week", "last month", "a week ago", "a few seconds ago",
    "2019-11-29 08:08-08", "2015-02-29", "0000-00-00", "+1 day", "-3 hours",
    "1 century ago", "2 fortnights ago", "1 decade", "1,5 hours ago",
]
FIXED = {"RELATIVE_BASE": datetime(2020, 1, 1, 0, 0, 0), "TIMEZONE": "UTC"}


def load_inputs():
    raw = json.load(open(CORPUS, encoding="utf-8"))["strings"]
    seen, out = set(), []
    for s in list(raw) + ADVERSARIAL:
        h = hashlib.sha256(("str:" + s).encode("utf-8")).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append((h, s))
    out.append((hashlib.sha256(b"none").hexdigest(), None))
    out.sort()
    return out


def canonical(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [canonical(v) for v in value]
    return value


def emit(src, path):
    sys.path.insert(0, os.path.abspath(src))
    import dateparser
    from dateparser.conf import settings as default_settings
    from dateparser.freshness_date_parser import freshness_date_parser

    settings = default_settings.replace(**FIXED)
    with open(path, "w", encoding="utf-8") as f:
        for h, s in load_inputs():
            rec = {"h": h}
            try:
                res = dateparser.parse(s, settings=settings)
                rec["parse"] = {"ok": True, "repr": canonical(repr(res))}
            except Exception as exc:  # noqa: BLE001 - exception type is part of the contract
                rec["parse"] = {"ok": False, "exc": type(exc).__name__, "msg": str(exc)}
            try:
                parts = freshness_date_parser._parse_with_parts(s, settings)
                rec["freshness"] = {"ok": True, "value": canonical(parts)}
            except Exception as exc:  # noqa: BLE001
                rec["freshness"] = {"ok": False, "exc": type(exc).__name__, "msg": str(exc)}
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def run(base, opt):
    tmp = tempfile.mkdtemp(prefix="dpdiff-")
    a, b = os.path.join(tmp, "base.jsonl"), os.path.join(tmp, "opt.jsonl")
    for src, out in ((base, a), (opt, b)):
        subprocess.run([sys.executable, __file__, "--emit", src, out], check=True)
    da = {json.loads(line)["h"]: json.loads(line) for line in open(a, encoding="utf-8")}
    db = {json.loads(line)["h"]: json.loads(line) for line in open(b, encoding="utf-8")}
    assert da.keys() == db.keys()
    mismatches = [{"h": h, "baseline": da[h], "optimized": db[h]} for h in sorted(da) if da[h] != db[h]]
    report = {
        "independent_inputs": len(da),
        "dedup": "sha256 over the input text; one record per unique digest",
        "compared_fields": ["parse.result_repr", "parse.exception", "freshness.tuple", "freshness.exception"],
        "mismatches": len(mismatches),
        "first_mismatches": mismatches[:5],
    }
    json.dump(report, open(REPORT, "w"), indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "first_mismatches"}, indent=2))
    if mismatches:
        print(json.dumps(mismatches[0], indent=2)[:2000])
        raise SystemExit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs=2, metavar=("BASE", "OPT"))
    ap.add_argument("--emit", nargs=2, metavar=("SRC", "OUT"))
    args = ap.parse_args()
    if args.emit:
        emit(*args.emit)
    elif args.run:
        run(*args.run)
    else:
        ap.error("use --run BASE OPT")
