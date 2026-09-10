# Prompt revisions

## contract_extraction_table_v1 -> v2

**Why.** v1 specified a single `rate_cents` per service. Hospital 3's Appendix B,
as amended, prices seven services with two dated columns — "Rate to 31 December 2024"
and "Rate from 1 January 2025" — and no single-rate schema can represent that.

**How it showed up.** Not as a model failure. Three of the four models returned exactly
what v1 asked for and scored 0.980 on rate exact-match; the fourth scored 0.973. The
ceiling for a single-rate prompt on this exam is

    (113/120 + 98/98 + 84/84) / 3 = 0.980

so the frontier models were already at the maximum the prompt allowed. The 2% shortfall
was a schema defect, not an extraction error, and it was only visible because the exam
scores against a specification built independently of the prompt.

**Change.** `rate_cents` becomes a `rates` list carrying `valid_from` and `valid_to`,
with an explicit worked example of a two-column dated rate, and an instruction to read
the bounds from the column headers rather than infer them.

**Risk introduced.** A list invites a model to emit two rates where the contract states
one. Measured directly: v2's score on hospitals 4 and 5, which have no dated rates, must
stay at 1.000. A drop there means the schema has taught the model to hallucinate periods.

## contract_extraction_v1 (prose)

Unchanged. Hospital 2 states one rate per clause with no dated variants, so the
single-rate schema is correct there. Applying v2's list schema would introduce the risk
above with nothing to gain.
