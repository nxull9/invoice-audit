# Evaluation

Hospital 1 is the only hospital with labels, so it is the only place the system can be
scored. Everything else is measured without labels, in ways I state. Every number comes
from a run: `python app.py evaluate`, `python app.py audit hospital_N`, and the scripts
in `evaluation/` reproduce them.

## 1. Headline

| | |
|---|---|
| Detection, hospital 1 | precision 1.000, recall 1.000 (58 of 58), no false positives |
| Expected totals exact, hospital 1 | 909 of 913 |
| Line items repriced to the billed amount | 99.30% to 99.51% on all five hospitals |
| The same, on lines the service match could not have fixed | 98.60% to 99.56% (13,608 lines) |
| Descriptions left unmatched | 0, on every hospital |
| Injected faults detected | 96 of 96, no false positives on 759 clean controls, three seeds |
| Submission | 3,942 invoices, 285 flagged (7.2%), schema validated |

A perfect detection score is a warning, not a result. Section 4 treats it as one, and
section 5 tests the number I put in its place.

## 2. Per category, hospital 1

Support is the number that qualifies the result: a recall of 1.000 over three examples
is weak evidence, and eleven of the eighteen categories have fewer than six. The last
column separates the two claims a flag makes, that the invoice is wrong and what it
should have cost.

| category | labelled invoices | precision | recall | expected total exact |
|---|---:|---:|---:|---:|
| unknown_service | 12 | 1.000 | 1.000 | 12 |
| wrong_unit_basis | 11 | 1.000 | 1.000 | 11 |
| unit_price_mismatch | 10 | 1.000 | 1.000 | 10 |
| invoice_total_mismatch | 6 | 1.000 | 1.000 | 5 |
| line_total_arithmetic | 6 | 1.000 | 1.000 | 6 |
| malformed_service_date | 6 | 1.000 | 1.000 | 6 |
| premium_incorrectly_applied | 6 | 1.000 | 1.000 | 5 |
| bundle_not_applied | 5 | 1.000 | 1.000 | 5 |
| contract_number_mismatch | 5 | 1.000 | 1.000 | 5 |
| duplicate_invoice_id | 5 | 1.000 | 1.000 | 5 |
| service_date_after_invoice_date | 5 | 1.000 | 1.000 | 5 |
| service_date_out_of_window | 5 | 1.000 | 1.000 | 5 |
| cross_invoice_duplicate | 4 | 1.000 | 1.000 | 4 |
| daily_cap_exceeded | 4 | 1.000 | 1.000 | **0** |
| exclusion_window_violation | 4 | 1.000 | 1.000 | 4 |
| volume_discount_incorrectly_applied | 4 | 1.000 | 1.000 | 4 |
| volume_discount_omitted | 4 | 1.000 | 1.000 | 4 |
| premium_omitted | 3 | 1.000 | 1.000 | 3 |

Every expected-total miss is one of the four `daily_cap_exceeded` invoices, off by
14,775, 25,425, 76,275 and 188,000 cents. Two of those invoices also carry another
category, which is why `invoice_total_mismatch` and `premium_incorrectly_applied` each
show a miss as well: it is the same invoice counted twice, not a second problem. Section
8.1 explains why the amount is not recoverable. All 855 clean invoices have their
expected total exact.

Accuracy is not reported. With 58 wrong invoices in 913, a system that flags nothing
scores 93.6% and finds nothing.

Why the score is 1.000: the system recomputes rather than predicts. It reads the
contract, works out what each line should have cost, and compares integers. There is no
threshold and no probability, so a correct contract reading gives exact agreement by
construction. That makes the score a consequence of something else, which is the number
in section 5.

## 3. Coverage

| hospital | contract read by | invoices | lines | services | descriptions | by price | text tie-break | unknown | unmatched | repriced to billed | flagged |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hospital_1 | regex | 913 | 11,415 | 108 | 488 | 476 | 0 | 12 | 0 | 99.51% | 58 (6.4%) |
| hospital_2 | model (gpt-4o, prompt v2) | 1,125 | 14,360 | 76 | 506 | 493 | 0 | 13 | 0 | 99.49% | 76 (6.8%) |
| hospital_3 | regex | 932 | 11,655 | 120 | 544 | 525 | 5 | 14 | 0 | 99.36% | 70 (7.5%) |
| hospital_4 | regex | 835 | 10,560 | 98 | 534 | 521 | 0 | 13 | 0 | 99.35% | 63 (7.5%) |
| hospital_5 | regex | 1,050 | 13,221 | 84 | 474 | 446 | 16 | 12 | 0 | 99.30% | 76 (7.2%) |

The flag rates on the four unlabelled hospitals (6.8% to 7.5%) sit near hospital 1's
true 6.4%. I use that as an anomaly alarm for monitoring, not as evidence of accuracy: a
rate can land in the right band while false positives and false negatives cancel out.
What it would catch is a contract read badly enough to move the rate, which is exactly
what happened to hospital 2 (section 7).

## 4. Does it generalise, or has it memorised hospital 1?

Four decisions were calibrated on hospital 1's labels, and eleven categories have fewer
than six examples, so the perfect score is tested rather than defended.

I inject faults into invoices the labels mark clean. Those errors are not in the label
file, and the invoices they land in are ones the labels call correct, so detection is
generalisation and any flag on an untouched clean invoice is a true false positive.
(`evaluation/stress_test.py`; the test suite runs one seed on every change.)

Twelve faults per category, three seeds: 96 detected of 96, named correctly in every
case, 0 false positives on 759 clean controls, identical on seeds 0, 1 and 2. The
categories covered are contract_number_mismatch, daily_cap_exceeded,
invoice_total_mismatch, line_total_arithmetic, malformed_service_date,
service_date_out_of_window, unit_price_mismatch and wrong_unit_basis.

This is not general proof. Injection only covers faults I can create without ambiguity,
which is eight of the eighteen categories. It cannot create a judgement about intent,
such as which invoice of a reused-id pair is the wrong one, and it cannot test the
categories that depend on a contract rule being read correctly. Those stay on five and
two labelled examples and are the weakest claims here.

## 5. Is the reproduction rate circular?

The number I lean on is that 99.3% to 99.5% of line items are repriced to exactly the
billed amount. Since services are matched to descriptions *by price*, a reviewer asked
whether that is guaranteed by the matching rather than earned by the engine. It is a
fair question and it is testable. `evaluation/resolution_holdout.py` runs three tests.

**Split the lines by whether the match already fixed the rate.** A line whose expected
unit price equals the modal price that chose its service proves little. The measured set
is the lines whose expected unit price differs from it, because the engine applied a
bundle, a facility or tier multiplier, a premium, a weekend uplift or a volume discount.
A daily cap is not in that list on purpose: it changes the billable quantity, not the
unit price, so it cannot move a line into this set.

| hospital | lines | repriced to billed | priced away from the matched rate | of those, repriced to billed |
|---|---:|---:|---:|---:|
| hospital_1 | 11,415 | 99.51% | 960 | 99.05% |
| hospital_2 | 14,360 | 99.49% | 1,391 | 99.56% |
| hospital_3 | 11,655 | 99.36% | 1,661 | 98.60% |
| hospital_4 | 10,560 | 99.35% | 920 | 99.01% |
| hospital_5 | 13,221 | 99.30% | 8,676 | 99.19% |

13,608 lines are priced at a rate the matching never produced, and they reproduce at the
same rate as everything else. Hospital 5 is the clearest case: two thirds of its lines
carry a facility and plan-tier multiplier, so the matched price is not the answer for any
of them.

**Hold out half the invoices.** Fit the description-to-service mapping on half of them,
then measure only on the other half, whose prices never influenced the mapping: 99.64%,
99.48%, 99.35%, 99.35% and 99.37%. Between 3 and 8 descriptions per hospital appear only
in the held-out half and cannot be matched at all, which is the honest cost of the split.

**Throw the price away.** Match every description by text similarity alone. It agrees
with the price-based match on 92% to 96% of descriptions, and reproduction falls to
93.5% to 96.2%. This is the control that matters: if the number were a property of the
matching method, it would stay near 99% however the matching was done. It does not. It
falls when the mapping is worse and holds when the prices are hidden.

What this does not settle: all three tests use the same invoices. If a description's
modal price were wrong in the same way across a whole hospital, none of them would see
it. The independent checks for that are hospital 1's labels and the injected faults.

## 6. A check that needs no labels

The resolver assigns services by price and never reads the description. A sentence
encoder reads the description and never sees a price. If they agree, that is evidence
rather than circular reasoning, and it works on the hospitals with no labels.
(`evaluation/embeddings.py`, run in the notebook.)

Clustering hospital 1's 488 descriptions on text alone, against the price-based
assignment: homogeneity 0.891, completeness 0.904, adjusted Rand index 0.555. Two
methods with no shared information recover nearly the same grouping.

## 7. Hospital 2: the contract a model read

Hospital 2 is the only contract read by a model and the only one with no answer key. I
checked it three ways.

**By reproduction.** A wrong rate shows up as lines that do not reproduce. Under the
first pinned model and prompt, hospital 2 reproduced 97.77% against 99.3% to 99.5%
elsewhere, and flagged 283 of 1,125 (25.2%). That was the alarm.

**By a subset that could prove the guess wrong.** Weekend lines on services carrying a
weekend uplift: 411 lines, 80 mismatching. If two of the ten uplift services were
phantom, 411 x 2/10 = 82 would mismatch. 80 did.

**Against the text.** Hospital 2's clauses use one sentence shape per rule, so each rule
can be read back with a pattern and compared with the model's output, service by service
(`evaluation/verify_hospital_2.py`):

| model, same prompt | services | rates exact | rule defects | what they were |
|---|---:|---:|---:|---|
| gpt-4o | 76/76 | 76/76 | 7 | three threshold premium clauses filed as daily caps; twice the percentage also filed as a weekend uplift and the premium dropped |
| deepseek | 76/76 | 76/76 | 2 | two invented daily caps |

Every number either model produced is in the contract. The errors were which field a
number went into.

**The prompt change, measured.** `prose_v2` adds one section placing the three look-alike
sentence shapes side by side with an example each, and one self-check rule. Nothing else
changed. On all three hosted models: gpt-4o 7 defects to 0 (58 s), deepseek 2 to 0
(173 s), kimi-k2 0 (one truncated reply, repaired with one call). Rates stayed 76/76
exact on all three. gpt-4o with prose_v2 is the pin (decision log item 11): with all
three clean, the rule I set before seeing any numbers applies, the fastest model that
invents nothing.

After the change: 99.49% of line items reproduce, 76 invoices flagged (6.8%), all 506
descriptions matched, and the extracted rule counts equal the contract's. The Service Day
prediction from decision log item 6 was tested: uplift services reproduce 99.46% of 1,289
lines, weekend 98.81% (4 of 335), weekday 99.69%. That is noise, not the systematic shift
a wrong reading would produce.

**The same model, asked directly.** Through `ask`, gpt-4o was asked about clause 26.1,
the clause it had misfiled. It answered correctly: a threshold premium, +40% for that
Service Day, quoted verbatim. The v1 failure was filing, not understanding. Asked for an
MRI rate, which no clause states, it said the contract does not specify one.

**What the table exam did not predict.** On hospitals 3, 4 and 5, all four models read
307 of 307 services with no hallucinations. Prose was a different task. The exam measured
table reading and I took it as evidence about prose reading. It was not.

## 8. Four ways it goes wrong

### 8.1 Daily cap: the expected total is not recoverable

The engine trims a quantity to the contractual cap. The labels restore quantities of 3,
9, 3 and 3 against caps of 4, 12, 12 and 8, with no other line to explain the remainder.

Example: `INV-H1-000015`, Advanced Rheumatologic Laboratory Panel, 9 units billed against
a cap of 4. I expect 4 x 14775. The label implies 3.

All four invoices are still flagged, and the error is always in the direction of allowing
the provider the contractual maximum. This is the one category where I am confident the
invoice is wrong and not confident about the amount. The submission has a single
confidence column, so it carries the weaker of the two claims: 0.75, the lowest in the
system.

### 8.2 Conventions read from a handful of examples

Where the labels encode a convention rather than an arithmetic fact, I inferred it from
very few cases. A service dated 2026-07-24 on an invoice dated 2024-06-02 is both out of
term and post-dated; the labels report `service_date_out_of_window` alone, and two
examples set that rule. Which invoice of a reused-id pair is the offender came from five.
If hospitals 2 to 5 differ, nothing in my output would show it, so both categories are
capped at 0.90 confidence (decision log items 1, 2 and 9).

### 8.3 A price that matches by chance

A description for a service not in the contract still lands on some derivable price by
chance. Two independent signals guard this, weak text similarity and no repeat use, and
both are required. On hospital 1 they find all twelve with no false positives, but each
alone overlaps: the fakes reach 0.123 against a real minimum of 0.095. This is the most
data-fitted decision in the system, tuned on twelve examples. The separation margin is
printed per hospital; on hospital 5 it widened to 0.121 against 0.248.

### 8.4 A model files a rule under the wrong field

A language model reading prose gets the numbers right and the kind of rule wrong. "Where
the aggregate quantity ... exceeds twelve (12) nights, the rate ... shall be increased by
forty percent (40%)" became `daily_cap: 12, nbd_uplift_pct: 40, threshold_premium: null`.
Three true numbers in two wrong fields, for a service that then mispriced every weekend
line and every high-quantity day.

Example: clause 26.1, Ambulatory Haematology Nutritional Support, under gpt-4o with
prompt v1. Seven such defects took hospital 2 from 6.8% to 25.2% flagged.

Why it is dangerous: every number is real, so nothing downstream can tell. It was caught
because the flag rate is compared across hospitals and the extraction is checked against
the text. One prompt section separating the three look-alike sentence shapes took all
three models to zero defects. Every confidence on the model-read hospital is still
multiplied by 0.85, because the check covers this contract's wording, not the next one's.

## 9. Confidence

Composed from evidence (`src/output.py`, decision log item 9): the weakest category's
strength, times the weakest service match on the invoice, times the contract source
(1.00 regex, 0.85 model). Arithmetic findings keep their certainty through the last two,
because neither was involved in finding them.

Two limits are built in. No flag is reported at 1.000; the ceiling is 0.98, because even
an arithmetic finding is a claim about an invoice whose key I reconstructed. And the two
categories whose attribution rests on a fitted convention are capped at 0.90. Before
these caps, 53 flagged rows carried 1.000. None do now.

| hospital | mean confidence, flagged | mean, clean |
|---|---:|---:|
| hospital_2 (model) | 0.738 | 0.765 |
| hospital_3 | 0.832 | 0.893 |
| hospital_4 | 0.840 | 0.905 |
| hospital_5 | 0.816 | 0.891 |

A reviewer sorting by confidence reaches the model-read hospital first, which is where
the risk is. It is an ordering, not a calibrated probability: no curve was fitted,
because the only labels are hospital 1's and every hospital 1 prediction is right.

## 10. What I did not do

- No confidence calibration curve, for the reason above.
- No blind manual re-read of a sample of high-confidence flags and low-confidence clean
  invoices. That is the cheapest next check and it needs a person, not code.
- Prompt v2 was run on the three hosted models, not on the local Qwen.
- The extraction schema is not enforced at the sampler for the prose run. It is for the
  table exam. Turning it on alongside the prompt change would have mixed the two effects.
- No cross-hospital check of the fitted conventions. They cannot be checked without
  labels and are listed as assumptions in the decision log.
- A schema-complexity finding from the exam is in `prompts/CHANGELOG.md`: the local 7B
  model dropped 40% of rows under a nested schema the hosted models handled fine. It
  shaped prompt v3 for tables and is why the prose schema is flat.
