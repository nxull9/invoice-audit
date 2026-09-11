"""Summaries for the model exam: four models reading the same contracts, scored against
the regex-built specifications. Runtime uses one model; this is how it was chosen.
"""


def telemetry_summary(telemetry, model_name):
    """One row per model for the comparison table, from `extract_contract` telemetry."""
    def total(col):
        return int(telemetry[col].sum()) if col in telemetry else 0
    return {
        "model": model_name,
        "calls": len(telemetry),
        "clauses_expected": total("clauses_expected"),
        "services_accepted": total("services_accepted"),
        "parse_failures": int(telemetry.parse_error.notna().sum()),
        "schema_deviations": int(telemetry.schema_deviation.notna().sum())
                             if "schema_deviation" in telemetry else 0,
        "quotes_unverified": total("quotes_unverified"),
        "schema_enforced": bool(telemetry.schema_enforced.all())
                           if "schema_enforced" in telemetry else False,
        "retries": total("retries"),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "seconds": round(float(telemetry.seconds.sum()), 1),
    }
