# Pre-refactor baseline

Outputs of the system as it stood on 12 September 2026, before `src/` was split from
the research code, frozen so the refactor can be shown to change nothing.

One file per hospital for findings (`invoice_id, category, n_lines`), expected totals
(`source_seq, invoice_total_cents, expected_total_cents`) and description resolution
(`description, service, method, confidence`).

Hospital 2 was frozen under **gpt-4o / prose_v1**, the model pinned at the time.
`evaluation/regression.py` reads it under that model so the comparison stays about
the engine; the production pin has since moved to deepseek (decision log item 11).

    python evaluation/regression.py
