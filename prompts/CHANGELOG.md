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

## contract_extraction_table_v2 -> v3

**Why.** v2 solved the wrong half of the problem. It expressed hospital 3's dated rates
correctly, and the three hosted models handled it without losing a row — but
Qwen2.5-7B, which returned 15 of 15 on every batch under v1's flat schema, dropped
roughly 40% of rows under v2's nested one:

    expected  7  accepted  6
    expected 15  accepted  8
    expected 15  accepted  9
    expected 15  accepted  6
    expected 15  accepted 13
    expected 15  accepted 10

Token counts were normal, so nothing was truncated. The model simply produced fewer
usable objects once each service contained a list of objects rather than scalars.

**The general point.** Schema complexity is a cost, and it falls almost entirely on the
smallest model in a lineup. A nested structure that a frontier model absorbs without
noticing is what breaks a 7B. Designing the output format for the weakest model in the
comparison is not a compromise — it is what makes a local deployment viable at all.

**Change.** v3 returns to flat scalars and expresses the dated case with two extra
optional fields — `rate_cents_after` and `rate_change_date` — instead of a nested list.
No service contains an object or an array. The two-period structure is reconstructed in
`_read_rates` from those scalars, which is code's job rather than the model's.

**What is being tested.** v3 should match v2 on hospitals 3, 4 and 5 for the hosted
models, and recover Qwen's acceptance rate to v1 levels. If Qwen still drops rows, the
cause is not schema depth and the finding changes.

**Not implemented, and worth an explicit note.** Constrained decoding — restricting the
sampler so only tokens forming schema-valid JSON can be emitted — removes this class of
failure entirely, and is available *because* the model is local. A hosted API's sampler
cannot be constrained this way. That is an advantage of local inference this comparison
does not currently credit.
