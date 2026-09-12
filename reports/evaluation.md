# Evaluation

Hospital 1 is the only labelled hospital and therefore the only place this system can
be scored. Everything below is either measured there, or measured without labels in a
way that is stated explicitly. Every number comes from a run; `python app.py evaluate`,
`python app.py audit hospital_N` and the scripts in `evaluation/` reproduce them.

---

## 1. Headline

| | |
|---|---|
| Detection, hospital 1 | precision **1.000**, recall **1.000**, F1 **1.000** (58 of 58) |
| `expected_total_cents` exact, hospital 1 | **909 / 913** (99.56%) |
| Line items reproducing the billed amount | **99.30 – 99.51%** on all five hospitals |
| Descriptions left unresolved | **0**, on every hospital |
| Injected faults detected | **96 / 96**, zero false positives on 759 clean controls, three seeds |
| Submission | 3,942 invoices, 285 flagged (7.2%), schema-validated |

**A perfect detection score is a warning, not a result, and section 4 treats it as one.**

---

## 2. Per category, hospital 1

All eighteen categories score 1.000 on precision and recall. Support is printed because
it is the number that qualifies the result: a recall of 1.000 over three examples is
weak evidence, and eleven of the eighteen categories have fewer than six.

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

Accuracy is not reported anywhere. With 58 erroneous invoices in 913, a system that
flags nothing scores 93.6% and finds nothing.

**False positives: 0. False negatives: 0.** The four expected-total misses are all
`daily_cap_exceeded` and are explained in §7.1.

### Why the score is 1.000

The system does not predict, it **recomputes**. It reads the contract, derives what each
line should have cost, and compares integers. There is no decision threshold and no
probability, so a correct contract reading produces exact agreement by construction.

The figure that carries the evidence is therefore not the 1.000 but this:

> **99.51% of hospital 1's 11,415 line items reproduce their billed amount to the cent.**

A single misread rate would surface there as hundreds of mismatches. The detection score
is a consequence of that number, not an independent achievement.

---

## 3. Coverage

| hospital | contract read by | invoices | line items | services | descriptions | by price | text tie-break | unknown | unresolved | reproduced | flagged |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hospital_1 | regex | 913 | 11,415 | 108 | 488 | 476 | 0 | 12 | **0** | 99.51% | 58 (6.4%) |
| hospital_2 | **model** (gpt-4o, prompt v2) | 1,125 | 14,360 | 76 | 506 | 493 | 0 | 13 | **0** | 99.49% | 76 (6.8%) |
| hospital_3 | regex | 932 | 11,655 | 120 | 544 | 525 | 5 | 14 | **0** | 99.36% | 70 (7.5%) |
| hospital_4 | regex | 835 | 10,560 | 98 | 534 | 521 | 0 | 13 | **0** | 99.35% | 63 (7.5%) |
| hospital_5 | regex | 1,050 | 13,221 | 84 | 474 | 446 | 16 | 12 | **0** | 99.30% | 76 (7.2%) |

Flagged rates on the four unlabelled hospitals (6.8–7.5%) sit close to hospital 1's
true rate of 6.4%, which is weak but real evidence that the approach transfers. The
model-read hospital is indistinguishable from the regex-read ones on every column.

---

## 4. Does it generalise, or has it memorised hospital 1?

Four decisions were calibrated against hospital 1's labels, and eleven categories have
fewer than six examples. The perfect score is therefore tested rather than defended.

**Method.** Faults are injected into invoices the labels mark **clean** — errors absent
from the label file, in invoices the labels call correct. Detection is then
generalisation, and any flag on an untouched clean invoice is a true false positive.
(`evaluation/stress_test.py`; the test suite runs one seed on every change.)

**Result**, twelve faults per category, three seeds:

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

**96 detected of 96 injected. 0 false positives against 759 clean controls. Identical on
seeds 0, 1 and 2.**

**What this does not establish.** Injection covers faults that can be synthesised
unambiguously. It cannot cover judgements about intent — which invoice of a
reused-identifier pair is the offender, or whether an out-of-term date should also be
reported as post-dating its invoice. Those remain calibrated on five and two examples
and are the weakest claims in this submission.

> The engine generalises. The tie-breaking conventions are asserted.

---

## 5. Independent validation without labels

The resolver assigns services by price and never reads the description. A sentence
encoder reads the description and never sees a price. Agreement between them is evidence
rather than circularity, and needs no labels — so it applies to the hospitals that have
none. (`evaluation/embeddings.py`, run in the notebook.)

Clustering hospital 1's 488 descriptions on text alone, against the price-based
assignment:

| | |
|---|---|
| homogeneity | **0.891** |
| completeness | **0.904** |
| adjusted Rand index | 0.555 |

Two methods sharing no information recover nearly the same partition.

---

## 6. Hospital 2: the contract a model read

Hospital 2 is the only contract read by a model and the only one with no known-correct
specification. It was checked three ways.

**6.1 Indirectly, by reproduction.** A wrong rate shows up as line items that fail to
reproduce their billed amount. Under the first pinned model (gpt-4o, prompt `prose_v1`)
hospital 2 reproduced **97.77%** against 99.3–99.5% elsewhere and flagged **283 of
1,125 (25.2%)**. That was an alarm, not a diagnosis.

**6.2 By a falsifiable subset.** Weekend lines on services carrying a non-business-day
uplift: 411 lines, 80 mismatching. If two of the ten "uplift" services were phantom,
411 × 2/10 ≈ 82 would mismatch. 80 did.

**6.3 Directly, against the text.** Hospital 2's clauses use one sentence shape per rule
family, so each rule can be read back with a pattern and compared with the model's
reading, service by service (`evaluation/verify_hospital_2.py`):

| model, same prompt | services | rates exact | rule defects | nature |
|---|---:|---:|---:|---|
| gpt-4o | 76/76 | 76/76 | **7** | three threshold-premium clauses filed as daily caps; twice the percentage also filed as a weekend uplift and the premium dropped |
| deepseek | 76/76 | 76/76 | **2** | two invented daily caps (16 and 6 units) |

Every number either model produced is in the contract. The errors are which *field* a
number went into.

**6.4 The prompt revision, measured.** `prose_v2` adds one section placing the three
look-alike sentence shapes side by side with an example each, and one self-check rule;
nothing else changed. Run live on both models:

| model | prose_v1 defects | prose_v2 defects | rates | v2 wall-clock |
|---|---:|---:|---:|---:|
| gpt-4o | 7 | **0** | 76/76 | 58 s |
| deepseek | 2 | **0** | 76/76 | 173 s |

**Decision.** Pin gpt-4o with prose_v2 (decision log item 11): with both models clean,
the pre-stated rule — the faster of the models that invented nothing — applies.

**Result.** 99.49% of line items reproduce; 76 invoices flagged (6.8%); all 506
descriptions resolve (493 by price, 13 unknown to the contract, 0 unresolved); the
extracted rule counts equal the contract's. The category distribution matches
hospital 1's. The Service Day prediction from decision
log item 6 was tested: uplift services reproduce 99.46% of 1,289 lines, weekend 98.81%
(4 of 335), weekday 99.69% — ordinary noise, not the systematic shift a wrong reading
would produce.

**What the model exam did not predict.** On hospitals 3, 4 and 5 — tables, scored
against the regex specs — all four models read 307/307 services with no hallucinations;
gpt-4o was fastest (119 s) and was chosen by that rule. Prose was a different task. The
exam measured table reading and was taken as evidence about prose reading; it was not.

---

**6.5 The same model, asked directly.** Through `ask`, GPT-4o was asked about clause
26.1 — the clause it had mis-filed under prompt v1. It answered correctly: a threshold
premium, +40% for that Service Day, quoted verbatim. The v1 failure was therefore not
comprehension but filing: the model understood the sentence and put its numbers in the
wrong fields while producing 76 records in a row, which is why one section naming the
three fields fixed it. Asked for an MRI rate, which no clause states, it answered that
the contract does not specify one, with no clause and no quote.

**6.6 The model at arithmetic, measured.** Asked what 15 hours of a service on a
Saturday would cost, the model found the right clause, quoted it, correctly declined to
invent a weekend uplift, deferred to the engine as its prompt requires — and computed
68,656.25 cents. The clause raises the rate *for that Service Day* once ten hours are
exceeded, so all fifteen hours are priced at the higher rate: 79,215. The model applied a
marginal, tax-bracket reading that contracts usually use and this one does not, and left
a fraction of a cent. Asked to count capped services from an 80-row table it said 5 of
8, and listed 4 of 6 bundled services. Rates it quoted were right every time. Counting
and arithmetic now happen in Python (`ask` receives computed counts; `price` computes
costs) and the model is left with what it is good at: reading and explaining.

## 7. Systematic failure modes

Four ways this system goes wrong, each with an example.

### 7.1 `daily_cap_exceeded` — expected totals are not recoverable

The four `expected_total_cents` misses on hospital 1 are all this category, and they
are irreducible. The engine trims a quantity to the contractual cap, which is what the
contract entitles the provider to. The labels restore quantities of 3, 9, 3 and 3
against caps of 4, 12, 12 and 8, with no co-occurring line item to explain the
remainder. The pre-inflation quantity is stated nowhere in the contract.

*Example.* `INV-H1-000015`, Advanced Rheumatologic Laboratory Panel, 9 units billed
against a cap of 4. We expect 4 × 14775. The label implies 3.

All four invoices are still flagged correctly, and the error is always conservative — we
allow the provider the contractual maximum. This category carries the lowest confidence
(0.75).

### 7.2 Conventions read from a handful of examples

Where the labels encode a convention rather than an arithmetic fact, it was inferred
from very few instances.

*Example.* A service dated `2026-07-24` on an invoice dated `2024-06-02` is both
out-of-term and post-dated. The labels report `service_date_out_of_window` **alone**.
Two examples established that precedence. If hospitals 2–5 label such cases
differently, that category's precision drops and nothing in our output would show it.

### 7.3 Coincidental price matches

Resolution matches on the modal `(unit_basis, unit_price_cents)`. A description for a
service absent from the contract still lands on *some* derivable price by chance.

Two independent signals guard this — low text similarity to the price's choice, and no
established repeat usage — and both are required. On hospital 1 they recover all twelve
with no false positives, but individually they overlap (fakes reach 0.123 against a
genuine minimum of 0.095). This is the most data-fitted decision in the system, tuned
on twelve examples.

*Mitigation.* The separation margin is reported per hospital. On hospital 5 it widened
to 0.121 against 0.248, which is evidence it transfers.

### 7.4 A model files a rule under the wrong field

A language model reading prose gets the numbers right and the *kind* of rule wrong.
"Where the aggregate quantity … exceeds twelve (12) nights, the rate … shall be
increased by forty percent (40%)" became `daily_cap: 12, nbd_uplift_pct: 40,
threshold_premium: null` — three true numbers in two wrong fields, for a service that
then mispriced every weekend line and every high-quantity day.

*Example.* Clause 26.1, Ambulatory Haematology Nutritional Support, under gpt-4o /
prose_v1. Seven such defects took hospital 2 from 6.8% to 25.2% flagged.

*Why it is dangerous.* Every number is real, so nothing downstream can tell. It was
caught only because the flag rate is compared across hospitals and the extraction is
checked against the text. *Mitigation:* one prompt section separating the three
look-alike sentence shapes took both models to zero defects (§6.4); every confidence on
the model-read hospital is still multiplied by 0.85, because the check covers this
contract's wording, not the next one's.

---

## 8. Confidence

Composed from evidence (`src/output.py`, decision log item 9): the weakest category's
strength (1.00 arithmetic; 0.75–0.92 rule-based) × the weakest service resolution on
the invoice × the contract source (1.00 regex, 0.85 model). Arithmetic facts skip the
last two. A clean invoice starts at 0.95.

| hospital | mean confidence | clean | flagged |
|---|---:|---:|---:|
| hospital_2 (model) | 0.764 | 0.765 | 0.745 |
| hospital_3 | 0.889 | | |
| hospital_4 | 0.901 | | |
| hospital_5 | 0.887 | | |

A reviewer sorting by confidence reaches the model-read hospital first, which is where
the risk is. It is an ordering, not a calibrated probability: no curve was fitted,
because the only labels are hospital 1's and every hospital 1 prediction is correct.

---

## 9. What was not attempted

- **Prompt v2 was run on two of the four models** (gpt-4o, deepseek). Kimi K2 and the
  local Qwen were not re-run under v2.
- **The extraction schema is not enforced at the sampler for the prose run.** It is for
  the tabular exam. Adding it alongside the prompt change would have confounded the two;
  now that the prompt effect is measured, it is the next change to make.
- **No confidence calibration curve.** Stated above.
- **Cross-hospital validation of the fitted conventions.** They cannot be checked
  without labels, and are reported as assumptions in `decision_log.md`.
- **A schema-complexity finding from the exam** is recorded in `prompts/CHANGELOG.md`:
  the local 7B model dropped 40% of rows under a nested schema that the hosted models
  absorbed. It shaped prompt v3 for tables and is why the prose schema is flat.
