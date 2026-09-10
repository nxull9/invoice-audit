# Evaluation

Hospital 1 is the only labelled hospital and therefore the only place this system can
be measured. Everything below is either measured there, or measured without labels in a
way that is stated explicitly.

---

## 1. Headline

| | |
|---|---|
| Detection, hospital 1 | precision **1.000**, recall **1.000**, F1 **1.000** (58 of 58) |
| `expected_total_cents` exact | **909 / 913** (99.56%) |
| Line items reproducing the billed amount | **99.30 – 99.51%** across four hospitals |
| Descriptions left unresolved | **0**, on every hospital |
| Injected faults detected | **96 / 96**, zero false positives, three seeds |

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

| hospital | invoices | line items | services | descriptions | resolved by price | text tie-break | unknown | unresolved | reproduced | flagged |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hospital_1 | 913 | 11,415 | 108 | 488 | 476 | 0 | 12 | **0** | 99.51% | 58 (6.4%) |
| hospital_3 | 932 | 11,655 | 120 | 544 | 525 | 5 | 14 | **0** | 99.36% | 70 (7.5%) |
| hospital_4 | 835 | 10,560 | 98 | 534 | 521 | 0 | 13 | **0** | 99.35% | 63 (7.5%) |
| hospital_5 | 1,050 | 13,221 | 84 | 474 | 446 | 16 | 12 | **0** | 99.30% | 76 (7.2%) |

Flagged rates on the three unlabelled hospitals (7.2–7.5%) sit close to hospital 1's
true rate of 6.4%, which is weak but real evidence that the approach transfers.

---

## 4. Does it generalise, or has it memorised hospital 1?

Four decisions were calibrated against hospital 1's labels, and eleven categories have
fewer than six examples. The perfect score is therefore tested rather than defended.

**Method.** Faults are injected into invoices the labels mark **clean** — errors absent
from the label file, in invoices the labels call correct. Detection is then
generalisation, and any flag on an untouched clean invoice is a true false positive.

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
none.

Clustering hospital 1's 488 descriptions on text alone, against the price-based
assignment:

| | |
|---|---|
| homogeneity | **0.891** |
| completeness | **0.904** |
| adjusted Rand index | 0.555 |

Two methods sharing no information recover nearly the same partition.

---

## 6. Systematic failure modes

Four ways this system goes wrong, each with an example.

### 6.1 `daily_cap_exceeded` — expected totals are not recoverable

The four `expected_total_cents` misses are all this category, and they are irreducible.

The engine trims a quantity to the contractual cap, which is what the contract entitles
the provider to. The labels restore quantities of 3, 9, 3 and 3 against caps of 4, 12,
12 and 8, with no co-occurring line item to explain the remainder. The pre-inflation
quantity is stated nowhere in the contract.

*Example.* `INV-H1-000015`, Advanced Rheumatologic Laboratory Panel, 9 units billed
against a cap of 4. We expect 4 × 14775. The label implies 3.

All four invoices are still flagged correctly, and the error is always conservative — we
allow the provider the contractual maximum. Confidence on this category is set to 0.75,
the lowest of any.

### 6.2 Conventions read from a handful of examples

Where the labels encode a convention rather than an arithmetic fact, it was inferred
from very few instances.

*Example.* A service dated `2026-07-24` on an invoice dated `2024-06-02` is both
out-of-term and post-dated. The labels report `service_date_out_of_window` **alone**.
Two examples established that precedence. If hospitals 2–5 label such cases differently,
that category's precision drops and nothing in our output would indicate it.

### 6.3 Coincidental price matches

Resolution matches on the modal `(unit_basis, unit_price_cents)`. A description for a
service absent from the contract still lands on *some* derivable price by chance.

Two independent signals guard this — low text similarity to the price's choice, and no
established repeat usage — and both are required. On hospital 1 they recover all twelve
with no false positives, but individually they overlap (fakes reach 0.123 against a
genuine minimum of 0.095). This is the most data-fitted decision in the system, tuned on
twelve examples.

*Mitigation.* The separation margin is reported per hospital. On hospital 5 it widened
to 0.121 against 0.248, which is evidence it transfers.

### 6.4 Schema complexity falls on the smallest model

Prompt v2 nested a list of dated rates inside each service. The three hosted models were
unaffected. Qwen2.5-7B, which returned 15 of 15 rows on every batch under the flat v1
schema, dropped roughly 40%:

```
expected  7  accepted  6      expected 15  accepted  6
expected 15  accepted  8      expected 15  accepted 13
expected 15  accepted  9      expected 15  accepted 10
```

Token counts were normal, so nothing truncated. The model produced fewer usable objects
once each service contained a list rather than scalars.

*Mitigation.* v3 returns to flat scalars and rebuilds the two-period structure in code.
Separately, the output schema is now enforced at the sampler — declared to the API for
hosted models, applied with a logits processor locally — which removes this class of
failure rather than mitigating it.

---

## 7. What was not attempted

- **Hospital 2 is the only contract requiring a model**, and the only one whose
  extraction cannot be checked against a known-correct specification. It is validated
  indirectly, by whether the extracted rates reproduce billed amounts at the rate the
  four verified hospitals achieve.
- **Constrained decoding was added but not tuned.** Enforcement is on; whether it fully
  recovers the local model's row acceptance is measured in the notebook, not assumed.
- **No confidence calibration curve.** Confidence is composed from evidence quality
  rather than fitted, and its calibration against outcomes is not measured.
- **Cross-hospital validation of the fitted conventions.** They cannot be checked
  without labels, and are reported as assumptions in `decision_log.md`.
