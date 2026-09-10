# Tests

```bash
python tests/test_pipeline.py       # or: python -m pytest tests -q
```

Twelve regression tests. Each one covers a failure that occurred at least once during
development, most of them in code paths that are awkward to reach by hand — replaying a
recording, tolerating an unexpected output shape from a model, reading two prompt
schemas. Those paths now run on every change rather than being exercised for the first
time in a live session.

The suite also pins the headline results, so a refactor that quietly changes them fails
here rather than in the report: hospital 1 at precision and recall 1.000, expected
totals exact on 909 of 913, seven amended services carrying 127 priced periods across
120 services, and 96 injected faults detected with zero false positives.
