# Evaluation

Hospital 1 is the only hospital with labels, so it is the only place the system can be
scored. Everything below is either measured there or measured without labels in a way I
say explicitly. Every number comes from a run. `python app.py evaluate`,
`python app.py audit hospital_N` and the scripts in `evaluation/` reproduce them.

## 1. Headline

| | |
|---|---|
| Detection, hospital 1 | precision 1.000, recall 1.000, F1 1.000 (58 of 58) |
| Expected totals exact, hospital 1 | 909 of 913 (99.56%) |
| Line items reproducing the billed amount | 99.30% to 99.51% on all five hospitals |
| Descriptions left unmatched | 0, on every hospital |
| Injected faults detected | 96 of 96, zero false positives on 759 clean controls, three seeds |
| Submission | 3,942 invoices, 285 flagged (7.2%), schema validated |

A perfect detection score is a warning, not a result. Section 4 treats it as one.

## 2. Per category, hospital 1

All eighteen categories score 1.000 on precision and recall. Support is shown because it
is what the result is worth: a recall of 1.000 over three examples is weak evidence, and
eleven of the eighteen categories have fewer than six.

| category | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| unknown_service | 12 | 1.000 | 1.000 | 1.000 |
| wrong_unit_basis | 11 | 1.000 | 1.000 | 1.000 |
| unit_price_mismatch | 10 | 1.000 | 1.000 | 1.000 |
| invoice_total_mismatch | 6 | 1.000 | 1.000 | 1.000 |
| line_total_arithmetic | 6 | 1.000 | 1.000 | 1.000 |
| malformed_service_date | 6 | 1.000 | 1.000 | 1.000 |
| premium_incorrectly_applied | 6 | 1.000 | 1.000 | 1.000 |
| bundle_not_applied | 5 | 1.000 | 1.000 | 1.000 |
| contract_number_mismatch | 5 | 1.000 | 1.000 | 1.000 |
| duplicate_invoice_id | 5 | 1.000 | 1.000 | 1.000 |
| service_date_after_invoice_date | 5 | 1.000 | 1.000 | 1.000 |
| service_date_out_of_window | 5 | 1.000 | 1.000 | 1.000 |
| cross_invoice_duplicate | 4 | 1.000 | 1.000 | 1.000 |
| daily_cap_exceeded | 4 | 1.000 | 1.000 | 1.000 |
| exclusion_window_violation | 4 | 1.000 | 1.000 | 1.000 |
| volume_discount_incorrectly_applied | 4 | 1.000 | 1.000 | 1.000 |
| volume_discount_omitted | 4 | 1.000 | 1.000 | 1.000 |
| premium_omitted | 3 | 1.000 | 1.000 | 1.000 |

Accuracy is not reported. With 58 wrong invoices in 913, a system that flags nothing
scores 93.6% and finds nothing.

False positives: 0. False negatives: 0. The four expected-total misses are all
`daily_cap_exceeded`, explained in 7.1.

Why the score is 1.000: the system recomputes rather than predicts. It reads the
contract, works out what each line should have cost, and compares integers. There is no
threshold and no probability, so a correct contract reading gives exact agreement by
construction. The number that carries the evidence is this one: 99.51% of hospital 1's
11,415 line items reproduce their billed amount to the cent. A single misread rate would
show up there as hundreds of mismatches.

## 3. Coverage

| hospital | contract read by | invoices | lines | services | descriptions | by price | text tie-break | unknown | unmatched | reproduced | flagged |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hospital_1 | regex | 913 | 11,415 | 108 | 488 | 476 | 0 | 12 | 0 | 99.51% | 58 (6.4%) |
| hospital_2 | model (gpt-4o, prompt v2) | 1,125 | 14,360 | 76 | 506 | 493 | 0 | 13 | 0 | 99.49% | 76 (6.8%) |
| hospital_3 | regex | 932 | 11,655 | 120 | 544 | 525 | 5 | 14 | 0 | 99.36% | 70 (7.5%) |
| hospital_4 | regex | 835 | 10,560 | 98 | 534 | 521 | 0 | 13 | 0 | 99.35% | 63 (7.5%) |
| hospital_5 | regex | 1,050 | 13,221 | 84 | 474 | 446 | 16 | 12 | 0 | 99.30% | 76 (7.2%) |

Flag rates on the four unlabelled hospitals (6.8% to 7.5%) sit close to hospital 1's
true rate of 6.4%. That is weak but real evidence the approach transfers. The
model-read hospital looks like the regex-read ones on every column.

## 4. Does it generalise, or has it memorised hospital 1?

Four decisions were calibrated on hospital 1's labels, and eleven categories have fewer
than six examples. So the perfect score is tested rather than defended.

Method: I inject faults into invoices the labels mark clean. Those errors are not in the
label file, and the invoices they land in are ones the labels call correct. Detection is
then generalisation, and any flag on an untouched clean invoice is a true false
positive. (`evaluation/stress_test.py`; the test suite runs one seed on every change.)

Result, twelve faults per category, three seeds:

| injected category | n | detected | named correctly |
|---|---:|---:|---:|
| contract_number_mismatch | 12 | 12 | 12 |
| daily_cap_exceeded | 12 | 12 | 12 |
| invoice_total_mismatch | 12 | 12 | 12 |
| line_total_arithmetic | 12 | 12 | 12 |
| malformed_service_date | 12 | 12 | 12 |
| service_date_out_of_window | 12 | 12 | 12 |
| unit_price_mismatch | 12 | 12 | 12 |
| wrong_unit_basis | 12 | 12 | 12 |

96 detected of 96. 0 false positives on 759 clean controls. Same on seeds 0, 1 and 2.

What this does not show: injection covers faults that can be created without ambiguity.
It cannot cover judgements about intent, such as which invoice of a reused-id pair is
the wrong one, or whether an out-of-term date should also be reported as after the
invoice date. Those stay calibrated on five and two examples and are the weakest claims
here.

## 5. A check that needs no labels

The resolver assigns services by price and never reads the description. A sentence
encoder reads the description and never sees a price. If they agree, that is evidence,
not circular reasoning, and it works on the hospitals with no labels too.
(`evaluation/embeddings.py`, run in the notebook.)

Clustering hospital 1's 488 descriptions on text alone, against the price-based
assignment: homogeneity 0.891, completeness 0.904, adjusted Rand index 0.555. Two
methods with no shared information recover nearly the same grouping.

## 6. Hospital 2: the contract a model read

Hospital 2 is the only contract read by a model and the only one with no answer key. I
checked it three ways.

**6.1 By reproduction.** A wrong rate shows up as lines that do not reproduce their
billed amount. Under the first pinned model (gpt-4o, prompt `prose_v1`) hospital 2
reproduced 97.77% against 99.3% to 99.5% elsewhere, and flagged 283 of 1,125 (25.2%).
That was the alarm.

**6.2 By a subset that could prove the guess wrong.** Weekend lines on services carrying
a weekend uplift: 411 lines, 80 mismatching. If two of the ten "uplift" services were
phantom, 411 x 2/10 = 82 would mismatch. 80 did.

**6.3 Against the text.** Hospital 2's clauses use one sentence shape per rule, so each
rule can be read back with a pattern and compared with the model's output, service by
service (`evaluation/verify_hospital_2.py`):

| model, same prompt | services | rates exact | rule defects | what they were |
|---|---:|---:|---:|---|
| gpt-4o | 76/76 | 76/76 | 7 | three threshold premium clauses filed as daily caps; twice the percentage also filed as a weekend uplift and the premium dropped |
| deepseek | 76/76 | 76/76 | 2 | two invented daily caps |

Every number either model produced is in the contract. The errors were which field a
number went into.

**6.4 The prompt change, measured.** `prose_v2` adds one section placing the three
look-alike sentence shapes side by side with an example each, and one self-check rule.
Nothing else changed. Run on all three hosted models:

| model | prose_v1 defects | prose_v2 defects | rates | v2 time |
|---|---:|---:|---:|---:|
| gpt-4o | 7 | 0 | 76/76 | 58 s |
| deepseek | 2 | 0 | 76/76 | 173 s |
| kimi-k2 | not run | 0 | 76/76 | one truncated reply, repaired with one call |

Decision: gpt-4o with prose_v2 (decision log item 11). With all three clean, the rule
set before any numbers were seen applies: the fastest model that invents nothing.

Result: 99.49% of line items reproduce, 76 invoices flagged (6.8%), all 506
descriptions matched (493 by price, 13 unknown to the contract, 0 unmatched), and the
extracted rule counts equal the contract's. The category distribution matches hospital
1's. The Service Day prediction from decision log item 6 was tested: uplift services
reproduce 99.46% of 1,289 lines, weekend 98.81% (4 of 335), weekday 99.69%. That is
noise, not the systematic shift a wrong reading would produce.

**6.5 The same model, asked directly.** Through `ask`, GPT-4o was asked about clause
26.1, the clause it had misfiled under prompt v1. It answered correctly: a threshold
premium, +40% for that Service Day, quoted verbatim. So the v1 failure was filing, not
understanding: the model understood the sentence and put its numbers in the wrong
fields while producing 76 records in a row. That is why one section naming the three
fields fixed it. Asked for an MRI rate, which no clause states, it said the contract
does not specify one.

**6.6 The model at arithmetic.** Asked what 15 hours of a service on a Saturday would
cost, the model found the right clause, quoted it, correctly did not invent a weekend
uplift, deferred to the engine as its prompt says, and computed 68,656.25 cents. The
clause raises the rate for the whole Service Day once ten hours are exceeded, so all
fifteen hours are at the higher rate: 79,215. The model applied a tax-bracket reading
that contracts usually use and this one does not, and left a fraction of a cent. Asked
to count capped services from an 80-row table it said 5 of 8, and listed 4 of 6 bundled
services. Rates it quoted were right every time. Counting and arithmetic now happen in
Python (`ask` receives computed counts; costs are computed by the engine) and the model
is left with reading and explaining.

**6.7 The Q&A, evaluated.** `ask` was put through 274 generated questions with known
answers across three prompt revisions and one code change (the model classifies a cost
or comparison question; the engine answers it). Final configuration: 137 of 137 across
all five hospitals. `reports/qa_evaluation.md`.

**What the table exam did not predict.** On hospitals 3, 4 and 5, all four models read
307 of 307 services with no hallucinations, scored against the regex specs. gpt-4o was
fastest (119 s) and was chosen by that rule. Prose was a different task. The exam
measured table reading and I took it as evidence about prose reading. It was not.

## 7. Four ways it goes wrong

### 7.1 Daily cap: the expected total cannot be recovered

The four expected-total misses on hospital 1 are all this category, and they cannot be
fixed from the data. The engine trims a quantity to the contractual cap. The labels
restore quantities of 3, 9, 3 and 3 against caps of 4, 12, 12 and 8, with no other line
to explain the remainder.

Example: `INV-H1-000015`, Advanced Rheumatologic Laboratory Panel, 9 units billed
against a cap of 4. I expect 4 x 14775. The label implies 3.

All four invoices are still flagged. The error is always in the direction of allowing
the provider the contractual maximum. This category has the lowest confidence (0.75).

### 7.2 Conventions read from a handful of examples

Where the labels encode a convention rather than an arithmetic fact, I inferred it from
very few cases.

Example: a service dated 2026-07-24 on an invoice dated 2024-06-02 is both out of term
and post-dated. The labels report `service_date_out_of_window` alone. Two examples set
that rule. If hospitals 2 to 5 label such cases differently, that category's precision
drops and nothing in my output would show it.

### 7.3 A price that matches by chance

Matching uses the most common (unit basis, price) of a description. A description for a
service that is not in the contract still lands on some derivable price by chance.

Two independent signals guard this, weak text similarity and no repeat use, and both are
required. On hospital 1 they find all twelve with no false positives, but each alone
overlaps (fakes reach 0.123 against a real minimum of 0.095). This is the most
data-fitted decision in the system, tuned on twelve examples. The separation margin is
printed per hospital; on hospital 5 it widened to 0.121 against 0.248.

### 7.4 A model files a rule under the wrong field

A language model reading prose gets the numbers right and the kind of rule wrong.
"Where the aggregate quantity ... exceeds twelve (12) nights, the rate ... shall be
increased by forty percent (40%)" became `daily_cap: 12, nbd_uplift_pct: 40,
threshold_premium: null`. Three true numbers in two wrong fields, for a service that
then mispriced every weekend line and every high-quantity day.

Example: clause 26.1, Ambulatory Haematology Nutritional Support, under gpt-4o /
prose_v1. Seven such defects took hospital 2 from 6.8% to 25.2% flagged.

Why it is dangerous: every number is real, so nothing downstream can tell. It was
caught only because the flag rate is compared across hospitals and the extraction is
checked against the text. Fix: one prompt section separating the three look-alike
sentence shapes took all three models to zero defects (6.4). Every confidence on the
model-read hospital is still multiplied by 0.85, because the check covers this
contract's wording, not the next one's.

## 8. Confidence

Built from evidence (`src/output.py`, decision log item 9): the weakest category's
strength (1.00 arithmetic; 0.75 to 0.92 rule-based) x the weakest service match on the
invoice x the contract source (1.00 regex, 0.85 model). Arithmetic facts skip the last
two. A clean invoice starts at 0.95.

| hospital | mean confidence |
|---|---:|
| hospital_2 (model) | 0.764 |
| hospital_3 | 0.889 |
| hospital_4 | 0.901 |
| hospital_5 | 0.887 |

A reviewer sorting by confidence reaches the model-read hospital first, which is where
the risk is. It is an ordering, not a calibrated probability: no curve was fitted,
because the only labels are hospital 1's and every hospital 1 prediction is right.

## 9. What I did not do

- Prompt v2 was run on the three hosted models, not on the local Qwen.
- The extraction schema is not enforced at the sampler for the prose run. It is for the
  table exam. Turning it on alongside the prompt change would have mixed the two
  effects; now that the prompt effect is measured, it is the next change.
- No confidence calibration curve (see above).
- No cross-hospital check of the fitted conventions. They cannot be checked without
  labels and are listed as assumptions in the decision log.
- A schema-complexity finding from the exam is in `prompts/CHANGELOG.md`: the local 7B
  model dropped 40% of rows under a nested schema the hosted models handled fine. It
  shaped prompt v3 for tables and is why the prose schema is flat.
