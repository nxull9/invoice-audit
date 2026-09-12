# Tests

```bash
python -m pytest tests -q          # 36 tests, about 18 seconds
```

`test_pipeline.py` pins the results a change must not move: hospital 1 at precision
and recall 1.000, expected totals exact on 909 of 913, seven amended services carrying
127 priced periods, 96 injected faults detected with zero false positives, every tabular
contract compiling without a warning, and rounding after each step.

`test_runtime.py` covers the entry points: loading a spec (hospital 2 replays its
recording with no key), writing and validating a submission, the later invoice winning a
reused identifier, confidence composed from evidence, and a model that misbehaves:
prose instead of JSON, a number where a name belongs, an invented service, a bundle
partner that was never extracted, HTTP 429/503/401 and a timeout. The last test replays
every hospital and compares with a frozen baseline of earlier outputs
(`evaluation/baseline/`).

Most of these were failures that happened at least once during development.
