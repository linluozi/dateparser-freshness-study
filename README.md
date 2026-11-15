# dateparser freshness fast-path study

A measured **negative result** for a plausible `dateparser` optimisation: the
relative-date parser runs on every input and fails on ordinary absolute dates,
so skipping that failure path *looks* free. On 1,859 date strings recorded from
dateparser's own test suite it buys **0.99-1.01x** — no usable speedup — and the
patch is therefore **not** offered as an `-opt-lab`. The repository keeps the
measurement, the 1,901-input byte-identical certificate, and the falsification.

Upstream: https://github.com/scrapinghub/dateparser
Base commit: `1fdf5da3bb96dead01d3ec2777218951a9d1a46b` (2026-11-13)

## What was changed (patch.diff, +6 lines, 1 file)

`FreshnessDateDataParser._parse_with_parts()` now returns early when `PATTERN`
(a number followed by a time unit: year/month/week/day/hour/...) does not match
the string after `strip_braces()` and `pop_tz_offset_from_string()`. `PATTERN`
is the *only* source of quantities for `_parse_date()`: when it does not match,
`get_kwargs()` is empty and the parser provably cannot produce a date. The guard
therefore skips timezone and clock setup without changing any result. This is a
necessary-condition fast path, not a heuristic.

## Measured result (3 warmups + 5 reps, median, same corpus, separate processes)

Workload `all` — 1,859 real strings recorded from upstream tests
(`tests/test_date.py`, `test_search.py`, `test_date_data.py`,
`test_freshness_date_parser.py`), 400-string scale:

| n | baseline median | optimized median | speedup |
|---|---|---|---|
| 50 | 5958.7 us | 5976.7 us | 0.997x |
| 150 | 6384.5 us | 6431.8 us | 0.993x |
| 400 | 5842.3 us | 5839.5 us | 1.000x |

Workload `simple` — ASCII strings of length <= 40 (production-looking dates):

| n | baseline median | optimized median | speedup |
|---|---|---|---|
| 50 | 5088.2 us | 5034.3 us | 1.011x |
| 150 | 6159.0 us | 6127.2 us | 1.005x |
| 400 | 6030.1 us | 5988.0 us | 1.007x |

Median speedup is **0.997x** (`all`) and **1.007x** (`simple`). The
guard removes real work, but on this corpus that work is a negligible share of
`dateparser.parse()`: locale applicability checks and translation dominate.
Conclusion: **do not merge this as a performance fix**; the relative-date failure
path is not where end-to-end parse time goes on realistic mixed inputs.

Workload `simple-en` — the same ASCII corpus with `languages=["en"]` (the
documented production setting that disables autodetection):

| n | baseline median | optimized median | speedup |
|---|---|---|---|
| 50 | 566.9 us | 504.6 us | 1.124x |
| 150 | 561.9 us | 520.2 us | 1.080x |
| 400 | 573.8 us | 531.0 us | 1.081x |

Median speedup is **1.081x**. Disabling autodetection
drops parse cost from ~5842 us to ~574 us per call on the same
ASCII corpus (a 10.2x difference), i.e. **language detection,
not the relative-date failure path, is where the time goes**. The guard's share is
~10% even in the friendliest configuration, and ~1% with autodetection on.

## Differential certificate (G2)

`tests/test_diff.py` runs the two checkouts in two independent processes and
compares, per input, both `dateparser.parse()` (result repr or exception
type+message) and the internal freshness tuple. Inputs are **sha256-deduplicated**
(one record per unique digest), not loop counts.

- independent inputs: **1901**
- mismatches: **0**
- adversarial set included: bracket-inserted units (`2 da[y]s ago`, `2 [hours] ago`,
  `2 UTC hours ago`), empty/whitespace, `None`, long digit runs, non-ASCII dates,
  timezone suffixes, impossible dates.
- command: `python tests/test_diff.py --run <baseline-src> <optimized-src>`

## Gate verdicts

| Gate | Verdict | Evidence / command |
|---|---|---|
| G1 upstream tests | PASS | patched: **25,332 passed, 23 skipped, 4 xfailed, 0 failed** (`python -m pytest tests -q --deselect tests/test_article_dates.py::test_report`; the deselected test forks a process and hits a sandbox `/dev/shm` PermissionError in pristine too) |
| G2 differential | PASS | 1,901 unique inputs, 0 mismatches (above) |
| G3 median speedup | **FAIL** | 0.997x (`all`, autodetect), best configuration 1.081x — both < 1.15x |
| G3b real-corpus speedup | **FAIL** | 1.007x (`simple`), 1.081x (`simple-en`) < 1.15x; hence this repo is not named `-opt-lab` |
| G4 large-scale | PASS | 400-string scale 1.000x (>= 0.95x) |
| G5 RSS | PASS | baseline 75692 KiB vs optimized 75700 KiB (ratio 1.000) |

## Reproduce

```bash
python3 -c "import json;r=json.load(open('benchmark/diff_report.json'));print(r['independent_inputs'],r['mismatches'])"  # 1901 0
python3 -m pytest tests -q                       # artifact checks (needs pytest, no upstream checkout)
git clone --depth=1 https://github.com/scrapinghub/dateparser.git /tmp/dp-base
cp -a /tmp/dp-base /tmp/dp-opt && git -C /tmp/dp-opt apply patch.diff
python3 benchmark/bench.py --src /tmp/dp-base --impl baseline --workload all --out /tmp/b.json --raw-dir /tmp/raw
python3 benchmark/bench.py --src /tmp/dp-opt  --impl optimized --workload all --out /tmp/o.json --raw-dir /tmp/raw
# the language-pinned workload that isolates the guard's share:
python3 benchmark/bench.py --src /tmp/dp-base --impl baseline  --workload simple-en --out /tmp/be.json --raw-dir /tmp/raw
python3 benchmark/bench.py --src /tmp/dp-opt  --impl optimized --workload simple-en --out /tmp/oe.json --raw-dir /tmp/raw
python3 tests/test_diff.py --run /tmp/dp-base /tmp/dp-opt
```

Note: `github.com:443` is blocked on the machine where this was measured; the
checkout was obtained over SSH from a mirror of the same commit. The commands
above use the public URL because that is what a reader has.

## Environment

- CPU: AMD EPYC 7K62 48-Core Processor
- RAM: 3723 MiB; RSS measured with `resource.getrusage`
- Python 3.12.3 (the only interpreter on the measurement host; 3.10/3.11 absent, so no cross-version row is claimed)
- Seed: 20261115; 3 warmups + 5 reps per scale; raw samples in `benchmark/raw/`
- Upstream commit `1fdf5da3bb96dead01d3ec2777218951a9d1a46b`

## 本轮创新

首次用上游自带测试语料给出**优化适用包络 + 否定结论**：该守卫在结构上可证明（`PATTERN` 是 `_parse_date` 唯一的数量来源），1,901 个去重输入逐字节等价；但真实语料上 0.997x，锁定语言后也只有 1.081x。同一语料上关掉语言自动检测把单次解析从 ~5842 us 降到 ~574 us（**10.2x**），首次把"相对日期失败路径"与"语言检测税"放在同一把尺子上量，证明前者不是瓶颈、后者才是——因此正确的动作是显式传 `languages=`，不是合这个补丁。与台账所有 `-opt-lab` 不同，这条交付的是可复现的否定结论 + 语义证书，而不是又一个 1.x 数字。

## License

BSD-3-Clause, copied verbatim from upstream (`LICENSE`). Patch and study code:
same license; upstream copyright retained.
