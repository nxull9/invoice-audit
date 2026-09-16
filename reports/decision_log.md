# Decision log

Every decision where the data or the contract did not settle the answer on its own,
what it rests on, and what goes wrong if I am wrong. The evidence for each is in
`decision_log_appendix.md`.

| # | decision | rests on | risk if wrong |
|---|---|---|---|
| 1 | `invoice_id` is reused. The real key is the `line_id` prefix, and the later invoice of a pair is the wrong one. | 5 pairs | wrong invoice flagged where ids repeat. Confidence for this category is capped at 0.90. |
| 2 | An out-of-term date is reported as `out_of_window` only, not also `after_invoice_date`. | 2 examples | one category's precision drops without warning. Capped at 0.90. |
| 3 | `unknown_service` needs two signals: weak text match and no repeat use. | 12 examples | a chance price match passes as a real service. |
| 4 | Over a daily cap, trim to the cap. The original quantity cannot be recovered. | 4 examples | the flag is right, the expected total is not. Lowest confidence, 0.75. |
| 5 | Round half up after each step, as every contract states. | H5: 10.8% of rates differ otherwise | a cent out on a tenth of all rates. |
| 6 | Hospital 2's 07:00 Service Day: the recorded date is the day it started. | tested after extraction: 4 of 335 weekend lines mismatch | systematic weekend mispricing. Not observed. |
| 7 | Two categories hospital 1 cannot express: wrong facility or tier multiplier. | H5: 18 of 31 mispriced lines | none. More useful than "price mismatch". |
| 8 | Tie-break confidence follows the text margin; below 0.10 report ambiguous and name both candidates. | H5: 16 ties | a coin flip presented as an answer. |
| 9 | Confidence is composed: weakest category strength x service match x contract source, capped at 0.98, lowered further for the two fitted conventions. | design | it is an ordering, not a calibrated probability. |
| 10 | Not built: retrieval for extraction, a model for matching, a local model in production, concurrency. | each measured | none. Each has a number behind it. |
| 11 | Hospital 2 is read by gpt-4o with prompt v2. | rule-by-rule check against the contract text | the checker is regex over one contract's wording. |
| 12 | Disallowed lines count toward cumulative utilisation. | 0 line totals differ either way | none on this data. |
| 13 | The line reproduction rate is reported as evidence after testing it for circularity three ways. | 13,608 lines priced away from the matched rate; held-out halves; text-only matching | it would be a property of the matching method rather than the engine. Tested; it is not. |

Two things this table does not contain, on purpose. Anything the contract states plainly
was not a decision, so it is not here. And nothing here is a preference: each row is
either forced by the contract or fitted to labelled examples, and the count of examples
is in the "rests on" column so the weak rows are visible.
