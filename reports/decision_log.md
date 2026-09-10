# Decision log

Assumptions made, ambiguities found, and what was decided about each. Every entry
states the risk of being wrong, because several of these are readings rather than
facts.

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
