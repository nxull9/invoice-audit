# Decision log

The decisions I had to make where the data or the contract did not settle the answer
on its own. Each one says what I found, what I decided, what it was based on, and what
goes wrong if I am wrong.

## On one page

| # | decision | based on | risk if wrong |
|---|---|---|---|
| 1 | `invoice_id` is reused. The real key is the `line_id` prefix. The later invoice is the wrong one. | 5 pairs | wrong invoice flagged where ids repeat |
| 2 | An out-of-term date is reported as `out_of_window` only, not also `after_invoice_date` | 2 examples | one category's precision drops without warning |
| 3 | `unknown_service` needs two signals: weak text match and no repeat use | 12 examples | a chance price match passes as a real service |
| 4 | Over a daily cap, trim to the cap. The true quantity cannot be recovered. | 4 examples | expected total wrong for that category; the flag is still right |
| 5 | Round half up after each step, as every contract says | H5: 10.8% of rates differ otherwise | a cent out on a tenth of all rates |
| 6 | Hospital 2's 07:00 Service Day: the recorded date is the start date | checked after extraction: 4 of 335 weekend lines mismatch | systematic weekend mispricing (not seen) |
| 7 | Two new categories hospital 1 cannot express: wrong facility or tier multiplier | H5: 18 of 31 mispriced lines | none; more useful than "price mismatch" |
| 8 | Tie-break confidence follows the text margin; below 0.10 report ambiguous and name both | H5: 16 ties | a coin flip presented as an answer |
| 9 | Confidence = category strength x weakest match x contract source; arithmetic facts exempt | design | it is an ordering, not a probability |
| 10 | Not built: retrieval for extraction, a model for matching, a local model in production, concurrency | measured | none; each has a number behind it |
| 11 | Hospital 2 read by gpt-4o with prompt v2 | rule-by-rule check against the text | the checker is regex over one contract's wording |
| 12 | Disallowed lines count toward cumulative utilisation | 0 line totals differ either way | none on this data |

## 1. `invoice_id` is not the invoice key

Five hospital 1 ids are each used by two different invoices: different patient,
different date, different total. Not a duplicated row.

The `line_id` prefix is the real key. `INV-H1-000068` is really invoices `L00068` and
`L00155`, and their lines add up to exactly the two stated totals. Everything downstream
prices an invoice unit, not an id.

Which of the pair is wrong? The label's expected total matches the later one in all
five cases, so I flag the later invoice and treat the first use as fine.

Risk: fitted on five examples. If hospitals 2 to 5 reuse an id three times, or blame the
earlier invoice, this is wrong. The count of reused ids is printed per hospital.

## 2. Out-of-term dates

A service dated 2026-07-24 on an invoice dated 2024-06-02 is both after the invoice
date and outside the contract term. The labels give it `service_date_out_of_window`
only, not both.

I raise `service_date_after_invoice_date` only for dates inside the term. That took the
category from precision 0.714 to 1.000 on hospital 1.

Risk: based on two examples.

## 3. A service that is not in the contract

A description for a service the contract does not list still lands on some derivable
price by chance.

I call it `unknown_service` only when two independent things are both true: the text
does not support the price's choice (similarity under 0.20) and the description has no
established use (appears 2 times or fewer).

On hospital 1 this finds all 12 with no false positives. Each signal alone overlaps
(the fakes score up to 0.123 against a real minimum of 0.095); together they separate.

Risk: this is the most data-fitted decision in the system, tuned on 12 examples. The
margin is printed per hospital. On hospital 5 it widened (0.121 against 0.248), which
suggests it transfers.

## 4. Daily cap: the expected total cannot be recovered

Four hospital 1 invoices exceed a daily cap. I trim the quantity to the cap, which is
what the contract allows. The labels instead use quantities of 3, 9, 3 and 3 against
caps of 4, 12, 12 and 8, with nothing in the data to explain those numbers.

I trim to the cap and say so. The original quantity is not stated anywhere, so I do not
guess it. All four invoices are still flagged. Only their expected total differs, and
always in the direction of allowing the provider the contractual maximum. These are the
four expected-total misses (909 of 913).

## 5. Rounding after every step

All contracts say rounding is applied after each step, not once at the end.

On hospital 1 the two ways give the same answer on all 109 rate combinations, so the
labelled data cannot check this. On hospital 5, which chains four multipliers, 115 of
1,062 combinations differ (10.83%). With step rounding, 99.30% of hospital 5's lines
reproduce the billed amount. The other way, about a tenth of all rates would be a cent
out and show up as false `unit_price_mismatch` across the hospital.

## 6. Hospital 2's Service Day

Hospital 2 is the only contract that defines the day differently:

> H1: "Service Day" means the calendar day recorded as the Service Date.
> H2: "Service Day" means the period of twenty-four (24) hours commencing at 07:00
> hours and concluding at 06:59 hours on the following calendar day.
> H2: "Business Day" means a Service Day which commences on a day other than a
> Saturday or a Sunday.

A service at 03:00 on Monday falls in the Service Day that began at 07:00 on Sunday,
so it would get the weekend uplift. Eight hospital 2 services carry one.

The data has dates only, no times, so this cannot be resolved from the data. I read the
recorded date as the day the Service Day began, which matches hospital 1 in effect. The
other reading would need every service to have started before 07:00.

What would prove me wrong: systematic mismatches on the eight uplift services, only on
dates next to weekends. Checked after extraction: those services reproduce 99.46% of
1,289 lines, weekend dates 98.81% (4 of 335), weekday 99.69%. Four in 335 is normal
noise. The reading stands.

## 7. Two categories hospital 1 cannot express

On hospital 5, 18 of 31 mispriced lines were the right service, correctly adjusted, but
read off the wrong column of the facility or plan tier grid.

I report these as `wrong_facility_multiplier` and `wrong_tier_multiplier`. Hospital 1 has
no multipliers, so its label set has no word for them. The submission format allows a
free-text category. `unit_price_mismatch` fell from 24 to 12, and 12 is exactly the
number of lines whose billed rate the contract cannot produce at any setting.

## 8. Two services with the same price and a similar name

Matching uses the most common (unit basis, unit price) of each description. If a future
contract prices two services the same and names them alike, both signals fail at once.

Today, collisions are rare and never worse than two-way:

| hospital | distinct prices | colliding | worst |
|---|---:|---:|---:|
| hospital_1 | 141 | 0 | none |
| hospital_3 | 185 | 1 (0.5%) | 2-way |
| hospital_4 | 134 | 0 | none |
| hospital_5 | 869 | 7 (0.8%) | 2-way |

Text breaks them. On hospital 5 this happened 16 times, with winning margins from 0.153
to 0.790.

The flaw this exposed: every one of those was reported at confidence 0.85. A tie won by
0.79 and one won by 0.15 looked the same. That is the exact failure the task warns
about.

Now confidence follows the margin: 0.30 or more gives 0.90, 0.10 to 0.30 gives 0.70,
below 0.10 the description is reported as ambiguous with both candidates named. On the
current data this moves one hospital 5 description from 0.85 to 0.70 and produces no
ambiguous rows. For a new hospital that prices two similar services the same, the
output is a low-confidence row naming both, which a person resolves in seconds.

## 9. Confidence comes from evidence

The submission asks for a confidence per invoice. A fixed number per category would
satisfy the format and mean nothing.

Three things, multiplied (`src/output.py`):

| evidence | value | source |
|---|---|---|
| category strength | 1.00 for arithmetic and calendar facts; 0.75 to 0.92 for rule-based categories | a fixed table; daily cap lowest because its total is unrecoverable (item 4) |
| match confidence | the weakest service match among the invoice's lines | the resolver (item 8) |
| contract source | 1.00 regex, 0.85 model | the spec's provenance |

Arithmetic facts skip the last two: 3 x 100 is not 350 whoever read the contract. A
clean invoice is never certain (0.95 ceiling), and is less certain under a model-read
contract.

On the submission, clean invoices on the regex hospitals sit at 0.89 to 0.93; on
hospital 2 at 0.73. A reviewer sorting by confidence looks at hospital 2 first, which is
where the risk is.

This is not calibrated. No curve was fitted to outcomes, because the only labels are
hospital 1's and every hospital 1 prediction is right. It is an ordering by how much
depends on a judgement.

## 10. What I did not build

Each was considered, some were tried in the notebook, none is in the runtime.

- Retrieval for contract extraction. Every rate article is needed, so top-k retrieval can
  only lose some. Measured: vector retrieval reaches full recall only at k = 13, the
  total number of articles. Retrieval is used for `ask`, where a question needs a few
  clauses and the hospital filter is applied as a hard mask before scoring.
- A model for matching descriptions. The price method matches 100% of descriptions on
  every hospital with zero calls. A model would be asked to do a job that is already
  done exactly.
- A local model in production. Qwen2.5-7B was run and compared. It read 307 of 307
  services after the harness bugs were fixed, in 1,478 s against GPT-4o's 119 s, and its
  constrained decoding would not load on the runtime available. The comparison is kept
  in `evaluation/local_model.py`; the production model is hosted.
- Concurrency. The whole model workload is thirteen calls. The pricing pass is
  order-dependent across invoices, so it could not be parallelised anyway, and it takes
  two seconds per hospital.
- A regex reader for hospital 2. `evaluation/verify_hospital_2.py` shows one is possible
  for this contract's wording. I use it to check the model, not to replace it. The point
  of the model is the next prose contract, whose wording will differ.

## 11. Which model and prompt read hospital 2

Hospital 2 is the only contract read by a model and the only one with no answer key.
With the first pinned model and prompt it reproduced 97.8% of line items against
99.3% to 99.5% elsewhere and flagged 283 invoices (25.2%) against 6.4% to 7.5%.

Finding the cause without labels: weekend lines on services with a weekend uplift, 411
lines, 80 mismatching. If two of the ten "uplift" services were phantom, 411 x 2/10 =
82 would mismatch. 80 did.

A direct check: hospital 2's clauses use one sentence shape per rule, so each rule can be
read back with a pattern and compared with the model's output service by service
(`evaluation/verify_hospital_2.py`). Under prompt `prose_v1`:

| model | services | rates exact | rule defects | what they were |
|---|---:|---:|---:|---|
| gpt-4o | 76/76 | 76/76 | 7 | three threshold premiums filed as daily caps; twice the percentage also filed as a weekend uplift and the premium dropped |
| deepseek | 76/76 | 76/76 | 2 | two invented daily caps |

Every number was in the contract. The errors were which field a number went into, and
gpt-4o's were all one confusion.

Prompt `prose_v2` adds one section placing the three look-alike sentence shapes side by
side with an example each, and one self-check rule. Nothing else changed. Run on all
three hosted models:

| model | prose_v1 defects | prose_v2 defects | v2 time |
|---|---:|---:|---:|
| gpt-4o | 7 | 0 | 58 s |
| deepseek | 2 | 0 | 173 s |
| kimi-k2 | not run | 0 | one truncated reply, repaired with one call |

Decision: gpt-4o with prose_v2. With all three clean, the rule I set before seeing any
numbers applies: the fastest model that invents nothing.

Result: 99.49% of hospital 2's lines reproduce, 76 invoices flagged (6.8%), every one of
506 descriptions matched, and the rule counts (9 premiums, 8 uplifts, 8 discounted
services, 3 bundle pairs, 8 caps) equal the contract's.

What the table exam did not predict: on hospitals 3, 4 and 5 both models scored the
same. Reading a table and reading a prose clause are different tasks, and a test on one
does not transfer to the other. That is why the checker exists.

Risk: the checker is regex over one contract's wording. It is evidence about this
contract, not a general tool. A sixth prose contract would need the model checked
another way, most likely the reproduction rate, which is what caught this in the first
place. The 0.85 confidence multiplier on model-read contracts stays for the same reason.

## 12. Do disallowed lines count toward cumulative utilisation?

Volume discounts depend on "cumulative utilisation of the Service prior to that line
item". A line the engine disallows (a duplicate billing, or one inside an exclusion
window) is billed but arguably not utilisation.

Pricing every hospital both ways changes the expected total of zero line items on
hospitals 1, 3, 4 and 5. The disallowed lines are too few, and too far from any
threshold, to matter.

I keep the simpler reading (every billed quantity counts) and record that it is a
reading. A dataset with many duplicates near a discount threshold would force the
question. This one does not.
