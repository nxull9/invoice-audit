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

## The unit-basis enum was measuring the schema, not the extraction

Qwen2.5-7B accepted only 204 of 307 services under v3 while the three hosted models
accepted all 307. The telemetry showed it had **returned all 307** — every rejection was
validation, not generation.

The reasons were almost entirely one field:

```
52  per_item_supplied         contract says "per item supplied"
33  per_day_of_service        contract says "per day of service"
18  per_night_of_occupancy    contract says "per night of occupancy"
 4  bare_list (envelope)
```

103 of 107 rejections were the model transliterating **the contract's own wording**. The
enum required `per_item`, which is the *invoice's* vocabulary and appears in no contract.
By any reasonable reading the model was more faithful to the source document than the
schema was.

This was a defect in the harness, not a finding about model size. `canonical_basis` now
accepts contract wording, invoice wording and the snake-cased form of either.

**What it means for the comparison.** Qwen's apparent shortfall was measuring an
arbitrary abbreviation, not its reading of the contract. The corrected figures are
reported in the notebook; the uncorrected ones are preserved here because the mistake is
instructive: *an extraction benchmark can silently measure its own schema, and the only
reason this surfaced was that the reject reasons were logged per service rather than
counted.*

Constrained decoding would also have prevented it — an enum in the schema makes
`per_item_supplied` unemittable. That remains the stronger fix, and it is available
locally precisely because the sampler is ours.

## contract_extraction_prose_v1 -> prose_v2

**Why.** Hospital 2 is the one contract read by a model, so its extraction cannot be
scored against a regex-built specification the way the tabular hospitals were. It was
checked a different way: hospital 2's clauses use one sentence shape per rule family, so
`evaluation/verify_hospital_2.py` reads each rule back with a pattern and compares it
with what the model returned, service by service.

**What v1 got wrong.** GPT-4o under v1 returned all 76 services with every rate exact,
and 7 rule defects — all one confusion:

```
22.2  contract: premium (exceeds 10 h  -> +25%)   model: cap=10  premium kept
26.1  contract: premium (exceeds 12    -> +40%)   model: cap=12  nbd=+40%  premium=None
26.5  contract: premium (exceeds  8    -> +15%)   model: cap=8   nbd=+15%  premium=None
```

A threshold-premium sentence ("where the aggregate quantity ... exceeds N ... the rate
shall be increased by X%") was filed as a daily cap of N, and twice its percentage was
filed as a non-business-day uplift. Every number is real; only the field is wrong.

**Effect on the audit.** Three phantom caps under-price high-quantity lines, two
phantom uplifts over-price every weekend line on those services, two missed premiums
under-price the lines the premium applies to. Hospital 2 flagged 283 of 1,125 invoices
(25.2%) against 6.4–7.5% on the other four. The weekend subset made the cause visible:
411 weekend lines on "uplift" services, 80 mismatching; with 2 of the 10 uplift services
being phantom, 411 × 2/10 = 82 was the prediction.

DeepSeek under the same v1 prompt made 2 defects (two invented caps, no premium
confusion). The tabular exam had ranked the two models equal; the prose contract did not.

**Change in v2.** One section added before the rules, giving the three sentence shapes
side by side — cap, threshold premium, non-business-day uplift — each with a worked
example and the fields it must and must not populate. One rule added (rule 8): before
returning, re-check every `daily_cap` and `nbd_uplift_pct` against the sentence it came
from. Nothing else in the prompt changed, so any difference in the result is attributable.

**What is being tested.** The 7 defects should go to 0 with rates staying 76/76 exact.
If v2 introduces a defect elsewhere, the section over-steered and the finding changes.

**Not changed, deliberately.** The schema is not enforced at the sampler for the prose
run. Doing so alongside the prompt change would make the two effects inseparable.

**Outcome.** Run live on both models and checked rule by rule against the contract:

| model | prose_v1 | prose_v2 | v2 wall-clock |
|---|---:|---:|---:|
| gpt-4o | 7 defects | **0** | 58 s |
| deepseek | 2 defects | **0** | 173 s |

Rates stayed 76/76 exact on both. No defect was introduced elsewhere. gpt-4o / prose_v2
is the production pin (decision log item 11). Both v2 recordings are in `runs/`.

## contract_qa_v1 -> qa_v2

**Why.** v1 gave the model the four clauses most similar to the question. That answers
"what is the rate for X" and cannot answer "which services have both a discount and a
weekend uplift": the answer is spread over 76 clauses and no four contain it.

**Change.** The model now also receives the hospital's rules table — one row per
service, the same table the engine's spec produces and the verifier checked — and is
told to answer set questions from the table and wording questions from the clauses,
naming what it counted. Arithmetic is allowed as shown steps with a stated deferral to
the engine. The refusal rule is unchanged.

**Risk.** A larger context invites summarising instead of quoting. SOURCE must say
"table" or a clause number, so a reader can tell which it did.

## invoice_explanation_v1

**Purpose.** `explain INV-...` hands the model the deterministic audit result — billed,
expected, categories, evidence lines, line items — and asks for a plain-English
narration under 150 words. It adds no facts; it is the "LLM interprets" half of the
principle applied to the output rather than the input.

## contract_qa_v2 -> qa_v3

**Why.** With the rules table in context, three set questions were put to gpt-4o about
hospital 2. Two-tier discounts: 4 named, correct. Services with a daily cap: it said 5;
there are 8, and it named one holder of the highest cap where two tie at 24. Bundled
services: it listed 4 of 6. Every rate it quoted was right; every count over the 80-row
CSV was unreliable. Counting is arithmetic, and the model was being asked to do it.

**Change.** Python computes a SUMMARY — per rule family, the count and the full list
with values — and places it above the table. The prompt calls those counts authoritative
and tells the model to copy them, never to recount, and to name both services in a tie.

**What is being tested.** The same three questions should now return 8 (two at 24),
6 bundled services in 3 pairs, and 4 two-tier discounts, with SOURCE "summary".

**Arithmetic through `ask`, measured.** Asked what 15 hours of Ambulatory Vascular
Infusion Therapy on a Saturday would cost, gpt-4o found clause 22.2, quoted it, invented
no weekend uplift, and deferred to the engine as instructed — and still got the number
wrong: 10 × 4225 + 5 × 5281.25 = 68,656.25. The clause says the rate *for that Service
Day* rises once the day exceeds ten hours, so all fifteen are priced at 5,281: 79,215
cents. The model applied the rule the way tariffs usually work, not the way this contract
says, and left a fraction of a cent. `price` now answers such questions from the engine
with every step shown; `ask` remains for what the contract *says*.
