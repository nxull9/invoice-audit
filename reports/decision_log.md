# Decision log

Assumptions made, ambiguities found, and what was decided about each. Every entry
states the risk of being wrong, because several of these are readings rather than
facts.

## On one page

| # | decision | fitted on | risk if wrong |
|---|---|---|---|
| 1 | `invoice_id` is reused; the `line_id` prefix is the key; the **later** invoice is the offender | 5 pairs | wrong invoice flagged where ids are reused |
| 2 | An out-of-term date is reported as `out_of_window` alone, not also `after_invoice_date` | 2 examples | one category's precision drops silently |
| 3 | `unknown_service` needs two signals: low text support **and** no repeat usage | 12 examples | a coincidental price match passes as a real service |
| 4 | Over a daily cap, trim to the cap; the true quantity is not recoverable | 4 examples | expected total wrong for that category (flag still right) |
| 5 | Round half-up **after each step**, as every contract says | H5: 10.8% of rates differ | a cent out on a tenth of all rates |
| 6 | Hospital 2's 07:00 "Service Day": the recorded date is the commencing date | verified: 4/335 weekend mismatches | systematic weekend mispricing (not observed) |
| 7 | Two categories hospital 1 cannot express: wrong facility / tier multiplier | H5: 18 of 31 mispriced lines | none; strictly more informative than "price mismatch" |
| 8 | Tie-break confidence follows the text margin; below 0.10 report **ambiguous**, name both | H5: 16 ties | a coin-flip presented as a finding |
| 9 | Confidence = category strength × weakest resolution × contract source; arithmetic exempt | design | it is an ordering, not a calibrated probability |
| 10 | Not built: RAG for extraction, a model for resolution, a local model in production, concurrency | measured | none; each is justified by a measurement |
| 11 | Hospital 2 read by **gpt-4o with prompt v2**: v1 had 7 defects (premiums filed as caps), v2 has 0 on both models | rule-by-rule check vs text | verifier is regex over one contract's wording; 0.85 multiplier kept |
| 12 | Disallowed lines count toward cumulative utilisation | 0 line totals differ either way | none on this data |

The entries below give the evidence for each.

---

## 1. `invoice_id` is not the invoice key

**Found.** Five hospital 1 identifiers are each carried by two genuinely different
invoices — different patient, different date, different total. This is not a
duplicated row.

**Decision.** The `line_id` prefix is the real key. `INV-H1-000068` is really
invoices `L00068` and `L00155`, and their line items sum to exactly the two stated
invoice totals. Everything downstream prices an invoice *unit*.

**Ambiguity.** Which of the pair is the offender? The label's `expected_total_cents`
matches the later-dated one in all five cases, so we flag the later invoice and treat
the first use as legitimate.

**Risk.** Fitted on five examples. If hospitals 2–5 reuse an identifier three times,
or credit the earlier invoice, this is wrong. Reported per hospital so it is visible.

---

## 2. Category precedence for out-of-term dates

**Found.** A service dated `2026-07-24` on an invoice dated `2024-06-02` is both after
the invoice date and outside the contract term. The labels apply
`service_date_out_of_window` **alone**, not both categories.

**Decision.** Raise `service_date_after_invoice_date` only for dates inside the term.

**Effect.** Took that category from precision 0.714 to 1.000 on hospital 1.

**Risk.** Inferred from two examples.

---

## 3. Detecting a service that is not in the contract

**Found.** A description for a service the contract does not list still lands on
*some* derivable price by coincidence.

**Decision.** Require two independent signals before calling it `unknown_service`:
the text does not support the price's choice (similarity < 0.20) **and** the
description has no established usage (appears ≤ 2 times).

**Evidence.** On hospital 1 this recovers all 12 with no false positives. The two
signals overlap individually — the 12 fakes score up to 0.123 against a genuine
minimum of 0.095 — and separate perfectly only in combination.

**Risk.** This is the most data-fitted decision in the system, tuned on 12 examples.
`unknown_margin` is reported per hospital so a collapsed margin is visible rather
than silent. On hospital 5 the margin widened (0.121 vs 0.248), which is mild
evidence it transfers.

---

## 4. `daily_cap_exceeded` — expected total is not recoverable

**Found.** Four hospital 1 invoices exceed a daily cap. We trim the quantity to the
cap, which is what the contract entitles the provider to. The labels instead restore
quantities of 3, 9, 3 and 3 against caps of 4, 12, 12 and 8 — with no co-occurring
line item to explain the remainder.

**Decision.** Trim to the cap and say so. The pre-inflation quantity is not stated
anywhere in the contract, so we do not guess it.

**Effect.** All four invoices are still flagged correctly. Only their
`expected_total_cents` is affected, and always in the conservative direction: we
allow the provider the contractual maximum. This is the sole cause of the four
expected-total misses (909/913 exact).

---

## 5. Rounding after every step, not once at the end

**Found.** All contracts state that rounding is applied "after each individual step of
the calculation, not once at the end."

**Measured.** On hospital 1 the two conventions are indistinguishable — 0 of 109 rate
combinations differ, so the development set cannot validate this choice at all. On
hospital 5, which chains four multipliers, **115 of 1,062 combinations differ
(10.83%)**.

**Evidence for the reading.** Under step rounding, 99.30% of hospital 5 line items
reproduce their billed amount. Under the alternative roughly a tenth of all rates
would be a cent out and would surface as spurious `unit_price_mismatch` across the
whole hospital.

---

## 6. Hospital 2's "Service Day" definition

**Found.** Hospital 2 redefines the day, and it is the only convention that differs
between contracts. Every other one — rounding, adjustment order, cumulative
utilisation — is word-for-word identical to hospital 1.

> H1: *"Service Day" means the calendar day recorded as the Service Date.*
> H2: *"Service Day" means the period of twenty-four (24) hours commencing at 07:00
> hours and concluding at 06:59 hours on the following calendar day.*
> H2: *"Business Day" means a Service Day which **commences** on a day other than a
> Saturday or a Sunday.*

**Why it could matter.** A service delivered at 03:00 on a Monday falls in the
Service Day that commenced 07:00 on Sunday, so it would **not** be a Business Day and
would attract the non-business-day uplift. Eight hospital 2 services carry such an
uplift.

**Why it cannot be resolved from the data.** The line items carry dates only. There
are no times anywhere in the dataset, so the 00:00–06:59 window cannot be identified.

**Decision.** Read the recorded `service_date` as the date the Service Day commenced —
identical in effect to hospital 1. The alternative requires assuming every service
began before 07:00, which would shift every date back a day and is implausible.

**Risk and test.** If the reading is wrong, the eight services carrying a
non-business-day uplift will mismatch systematically, and only on dates adjacent to
weekends. That is a specific, checkable prediction rather than an assumption, and it
is verified once hospital 2's rates are extracted.

**Verified.** With hospital 2 extracted (item 11), the eight uplift services reproduce
their billed amounts on 99.46% of 1,289 line items; weekend dates 98.81% (4 of 335
mismatch), weekday 99.69%. Four in 335 is the ordinary error rate, not a systematic
shift. The reading stands.

---

## 7. Two error categories that hospital 1 cannot express

**Found.** On hospital 5, 18 of 31 apparently mispriced lines were the correct
service, correctly adjusted, read off the **wrong column** of the facility or
plan-tier grid.

**Decision.** Report these as `wrong_facility_multiplier` and
`wrong_tier_multiplier`. These extend the hospital 1 label vocabulary, which has no
word for them because hospital 1 has no multipliers at all. The submission format
permits a free-text category.

**Effect.** `unit_price_mismatch` fell from 24 to 12 — and 12 is exactly the number
of lines whose billed rate the contract cannot produce at any setting.

**Alternative rejected.** Reporting them as `unit_price_mismatch` would be true but
would force a reviewer to rediscover the pattern by hand.

---

## 8. What happens when two services share a price *and* a similar abbreviation

**The question.** Resolution matches on the modal `(unit_basis, unit_price_cents)`. If a
future contract prices two services identically and describes them similarly, both
signals fail at once. What then?

**Measured today.** Collisions are rare and never worse than two-way:

| hospital | distinct prices | colliding | worst |
|---|---:|---:|---:|
| hospital_1 | 141 | 0 | — |
| hospital_3 | 185 | 1 (0.5%) | 2-way |
| hospital_4 | 134 | 0 | — |
| hospital_5 | 869 | 7 (0.8%) | 2-way |

Text breaks them. On hospital 5 that happened 16 times, with winning margins from 0.153
to 0.790.

**The flaw this exposed.** Every one of those was reported at confidence 0.85 — a tie won
by 0.79 and one won by 0.15 treated identically. That is exactly the failure the task
singles out: a coin-flip presented as a finding.

**Decision.** Confidence now follows the margin, and below a floor the description is not
resolved at all:

| margin | outcome | confidence |
|---|---|---|
| ≥ 0.30 | resolved, text decided clearly | 0.90 |
| 0.10 – 0.30 | resolved, but narrowly | 0.70 |
| < 0.10 | **reported ambiguous, both candidates named** | 0.40 |

On the current data this moves one hospital 5 description from 0.85 to 0.70
(`SPCLST GASTROINTESTINAL PHARM DISP`, margin 0.153) and produces no ambiguous rows.

**Why it matters for a sixth hospital.** The failure mode is now graceful. A contract that
prices two similarly-named services identically produces a low-confidence row naming both
candidates, which a human resolves in seconds — rather than a confident assignment that
silently misprices every invoice touching that service.

---

## 9. Confidence is composed from evidence, not asserted

**The question.** The submission asks for a confidence per invoice. A single number
invented per category would satisfy the format and mean nothing.

**Decision.** Three kinds of evidence, multiplied (`src/output.py`):

| evidence | value | where it comes from |
|---|---|---|
| category strength | 1.00 for arithmetic and calendar facts; 0.75–0.92 for rule-based categories | a fixed table; `daily_cap_exceeded` lowest because its expected total is unrecoverable (item 4) |
| resolution confidence | the weakest service resolution among the invoice's lines | the resolver's own margin-scaled confidence (item 8) |
| extraction source | 1.00 regex-read, 0.85 model-read | the spec's provenance |

Arithmetic facts are exempt from the last two: `3 × 100 ≠ 350` holds whoever read the
contract and however the description was resolved. A clean invoice is never certain
(0.95 ceiling, because an error type this system does not model would pass unseen), and
is less certain under a model-read contract.

**Effect.** On the shipped submission, clean invoices on the regex-read hospitals sit at
0.89–0.93; on hospital 2 at 0.73. Rule-based flags on hospital 2 sit below 0.70. A
reviewer triaging by confidence looks at hospital 2 first, which is where the risk is.

**What it is not.** It is not calibrated: no curve was fitted to outcomes, because the
only labels are hospital 1's and every hospital 1 prediction is correct. It is an
ordering by how much depends on a judgement, which is the property a reviewer needs.

---

## 10. What was deliberately not built

Each of these was considered, and some were prototyped in the notebook. None is in the
runtime.

- **Retrieval for contract extraction.** Every rate-bearing article is needed, so
  top-k retrieval can only lose some; article selection by heading loses none. Measured
  (`evaluation/`): vector retrieval reaches full recall only at k = 13 — the total number
  of articles — which you would only know if you already had the answer. Retrieval
  *is* used for `ask`, where one question needs a few clauses and the hospital filter is
  applied as a hard mask before scoring.
- **A model for description → service resolution.** The price index resolves 100% of
  descriptions on every hospital with zero calls; text similarity breaks the rare
  two-way collisions. A model would be asked to do a job that is already done exactly.
  The resolver still reports `ambiguous` rows for a human, so the failure mode when a
  future contract defeats it is a low-confidence row, not a silent guess.
- **A local model in production.** Qwen2.5-7B was run and compared. It read 307/307
  services after the harness bugs were fixed, in 1,478 s against GPT-4o's 119 s, and
  its constrained decoding would not load on the runtime available. The comparison is
  kept as evidence in `evaluation/local_model.py`; the pinned production model is hosted.
- **Concurrency.** The whole model workload is thirteen calls. Cumulative volume
  discounts make the pricing pass order-dependent across invoices, so it could not be
  parallelised even if it were slow, and it takes two seconds per hospital.
- **A regex compiler for hospital 2.** `evaluation/verify_hospital_2.py` proves one is
  possible for *this* contract's templated wording. It is used to check the model, not
  to replace it: the point of the model is the next prose contract, whose wording will
  differ.

---

## 11. Which model and which prompt read hospital 2, and how that was checked

**The problem.** Hospital 2 is the only contract read by a model and the only one with
no known-correct specification to score against. It had been validated indirectly —
does the extracted contract reproduce billed amounts at the rate the regex-read
hospitals do — and under the first pinned model and prompt it did not: 97.8% of line
items against 99.3–99.5% elsewhere, and 283 invoices flagged (25.2%) against 6.4–7.5%.

**Locating the cause without labels.** The flag rate was an alarm, not a diagnosis. The
subset that pointed at the cause was weekend lines on services carrying a
non-business-day uplift: 411 lines, 80 mismatching. If two of the ten "uplift" services
were phantom, 411 × 2/10 = 82 lines would mismatch. 80 observed.

**A direct check.** Hospital 2's clauses use one sentence shape per rule family, so each
rule can be read back with a pattern and compared with the model's reading service by
service (`evaluation/verify_hospital_2.py`). Under prompt `prose_v1`:

| model | services | rates exact | rule defects | what they were |
|---|---:|---:|---:|---|
| gpt-4o | 76/76 | 76/76 | **7** | three threshold premiums filed as daily caps; twice the percentage also filed as a weekend uplift and the premium dropped |
| deepseek | 76/76 | 76/76 | **2** | two invented daily caps |

Every number either model produced is in the contract. The errors are in which field a
number was filed under, and gpt-4o's were all one confusion.

**The prompt revision.** `prompts/contract_extraction_prose_v2.txt` adds one section
placing the three look-alike sentence shapes — cap, threshold premium, non-business-day
uplift — side by side with a worked example each, and one self-check rule. Nothing else
changed. Run live on both models and checked the same way:

| model | prose_v1 defects | prose_v2 defects | v2 wall-clock |
|---|---:|---:|---:|
| gpt-4o | 7 | **0** | 58 s |
| deepseek | 2 | **0** | 173 s |

**Decision.** Pin gpt-4o with prose_v2. With both models clean, the rule stated before
any numbers were seen applies again — the faster of the models that invented nothing.

**Result.** 99.49% of hospital 2's line items reproduce their billed amount; 76 invoices
flagged (6.8%); every one of the 506 billing descriptions resolves; the extracted rule
counts (9 premiums, 8 uplifts, 8 discounted services, 3 bundle pairs, 8 caps) equal the
contract's. The category distribution matches hospital 1's.

**What the tabular exam did not predict.** On hospitals 3, 4 and 5 both models scored
identically, and the selection rule chose gpt-4o as the faster. A structured table and a
prose clause are different reading tasks, and a model exam on one does not transfer to
the other. That is the finding, and it is the reason the verifier exists.

**Risk.** The verifier is regex over one contract's templated wording. It is evidence
about this contract, not a general oracle, and a sixth prose contract would need the
model checked some other way — most likely the reproduction rate, which is what caught
this in the first place. The 0.85 confidence multiplier on model-read contracts stays for
that reason: the verifier shows the rules were read right here, not that they would be
next time.
---

## 12. Does a disallowed line count toward cumulative utilisation?

**The question.** Volume discounts turn on "cumulative utilisation of the Service prior
to that line item". A line the engine disallows — a duplicate billing of the same
patient, service and date, or one inside an exclusion window — is billed but arguably not
*utilisation*: nothing extra was delivered.

**Measured.** Pricing every hospital both ways — disallowed lines counting, and not —
changes the expected total of **zero** line items on hospitals 1, 3, 4 and 5. The
disallowed lines are too few, and too far from any discount threshold, for the two
readings to differ on this data.

**Decision.** Keep the simpler reading (every billed quantity counts) because nothing
distinguishes them, and record that it is a reading. A dataset with many duplicates
clustered around a discount threshold would force the question; this one does not.
