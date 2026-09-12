"""Compare the current system with the outputs frozen before the refactor.

The baseline was captured on 12 September 2026, one file
per hospital for findings, expected totals and description resolution. A refactor
must reproduce them exactly; any difference is investigated, not accepted.

    python evaluation/regression.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src import audit, config

BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline")

# The baseline froze hospital 2 under the model pinned at the time. The pin later moved
# to deepseek by decision (decision log item 11); this check is about the engine, so it
# reads hospital 2 the way the baseline did.
FROZEN_UNDER = {"hospital_2": {"model_name": "gpt-4o", "prompt_version": "prose_v1"}}


def compare(name, old, new, keys):
    # None and NaN are the same absence; a CSV round-trip turns one into the other
    old = old.sort_values(keys).reset_index(drop=True).fillna("")
    new = new[old.columns].sort_values(keys).reset_index(drop=True).fillna("")
    merged = old.merge(new, on=keys, how="outer", suffixes=("_old", "_new"), indicator=True)
    only_old = (merged["_merge"] == "left_only").sum()
    only_new = (merged["_merge"] == "right_only").sum()
    both = merged[merged["_merge"] == "both"]
    changed = 0
    for col in [c for c in old.columns if c not in keys]:
        changed += (both[f"{col}_old"].astype(str) != both[f"{col}_new"].astype(str)).sum()
    if not (only_old or only_new or changed):
        return f"  {name:12} identical ({len(new)} rows)"
    return (f"  {name:12} DIFFERS: {only_old} rows only in baseline, {only_new} only now, "
            f"{changed} values changed")


def run(hospitals=None):
    exit_code = 0
    for h in hospitals or config.HOSPITALS:
        r = audit.audit_hospital(str(config.DATA), h, **FROZEN_UNDER.get(h, {}))
        print(h)
        checks = [
            ("findings", pd.read_csv(f"{BASELINE}/{h}_findings.csv"),
             r["findings"][["invoice_id", "category", "n_lines"]], ["invoice_id", "category"]),
            ("totals", pd.read_csv(f"{BASELINE}/{h}_totals.csv"),
             r["totals"][["invoice_id", "source_seq", "invoice_total_cents", "expected_total_cents"]],
             ["source_seq"]),
            ("resolution", pd.read_csv(f"{BASELINE}/{h}_resolution.csv"),
             r["resolution"][["description", "service", "method", "confidence"]], ["description"]),
        ]
        for name, old, new, keys in checks:
            line = compare(name, old, new, keys)
            print(line)
            if "DIFFERS" in line:
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or None))
