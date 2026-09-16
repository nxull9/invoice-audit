# Invoice audit: write-up

Repository: github.com/nxull9/invoice-audit
Predictions: `submission.csv`, 3,942 invoices for hospitals 2 to 5, 285 flagged (7.2%)

## What I built

The system re-prices every invoice line under the hospital's contract and compares.

Four of the five contracts are tables; I read those with regex. Hospital 2 is 40 pages of
prose, so a language model reads it one article at a time, and every reply is checked
against the text the model saw before I accept it. From there everything is plain Python
in integer cents: the contract's order of adjustments, rounding half up after each step,
cumulative discounts counted in service date order. The model never sees an invoice and
never produces a total.

Matching descriptions to services did not need a model. A contract can only produce a
small set of unit prices, so a description's usual price identifies the service; text
similarity only breaks ties. Every description in all five hospitals matched this way.

## How I measured

**On the labelled hospital.** Precision and recall 1.000 across all 18 categories, 909 of
913 expected totals exact. I do not treat that as the evidence: the system recomputes
rather than predicts, so a correct contract reading gives exact agreement by
construction. The number I trust is that 99.51% of hospital 1's 11,415 line items reprice
to the billed amount to the cent. I did not report accuracy, because flagging nothing
scores 93.6%.

**Testing that number instead of trusting it.** Services are matched by price, so
reproducing a price could be circular. 13,608 lines across the five hospitals are priced
at a rate the matching never produced, because a bundle, multiplier, premium, uplift,
discount or cap moved them; those reproduce at 98.6% to 99.6%. Fitting the matching on
half the invoices and measuring on the held-out half gives 99.35% to 99.64%. Matching by
text alone drops reproduction to 93.5% to 96.2%, which is the control: the number is not
pinned at 99% by the method.

**Against memorising hospital 1.** Four decisions were fitted on its labels, some on two
examples. So I injected errors into invoices the labels call clean: 96 of 96 caught, no
false positives on 759 controls, same on three seeds. That covers eight categories; it
cannot test the ones that depend on reading a contract rule.

**On the hospitals with no labels.** The reproduction rate above, and a text-only
clustering of descriptions that agrees with the price-based matching at homogeneity 0.89.
Flag rates (6.8% to 7.5% against hospital 1's true 6.4%) I use as an anomaly alarm, not
as proof: a rate can look right while false positives and negatives cancel.

**On the model.** Four models (GPT-4o, DeepSeek V3, Kimi K2, a local 4-bit Qwen2.5-7B)
read the same 22 table batches, scored against the regex specs. All four found 307 of 307
services and invented none, differing in speed (5 to 67 s a call) and cost. My rule, set
before the numbers: the fastest that invents nothing, which was GPT-4o.

Hospital 2 has no answer key and is where the biggest problem was. Under the first prompt
it flagged 25.2% of invoices. The weekend lines localised it, and because its clauses are
templated I could read each rule back with a pattern and compare service by service.
GPT-4o had filed three threshold premiums as daily caps: every number right, the field
wrong. A second prompt version showing the three look-alike sentence types side by side
took GPT-4o from 7 defects to 0 and DeepSeek from 2 to 0; Kimi read it clean. Hospital 2
now reproduces 99.49% and flags 6.8%.

## Four ways it goes wrong

**The amount for a daily cap is not recoverable.** The contract caps the quantity; the
labels imply a smaller original quantity it does not state. All four expected-total misses
are this category, and it carries the lowest confidence.

**A model files a real number in the wrong field.** The seven defects above were true
numbers in wrong fields, which nothing downstream can detect. Only the flag rate and the
rule-by-rule check caught it.

**Conventions fitted on a handful of examples.** Which invoice of a reused id is the wrong
one (five examples); whether an out-of-term date is also reported as post-dated (two).

**A price that matches by chance.** A description for a service not in the contract can
land on a derivable price. Two signals guard it, tuned on twelve examples.

## Where I was uncertain

**Hospital 2's reading.** Zero defects under the final prompt, but the checker is regex
over one contract's wording. It proves this contract was read right, not the next one.
Every confidence on hospital 2 is multiplied by 0.85 for that reason.

**Hospital 2's Service Day.** It runs 07:00 to 06:59 and the data has no times. I read the
recorded date as the start and wrote down what would prove me wrong: systematic weekend
mismatches on the eight uplift services. Measured after extraction, 4 of 335 weekend
lines. The reading held, but it was a reading.

**Confidence.** An ordering, not a probability, with nothing to calibrate it against
beyond hospital 1. So I put two limits in: no flag is reported as certain, since even an
arithmetic finding is a claim about an invoice whose key I reconstructed; and the two
convention-fitted categories are capped at 0.90. Where I am sure an invoice is wrong but
not sure of the amount, the single confidence column carries the weaker claim.

## What I would do differently with another week

Re-read a sample by hand: twenty high-confidence flags and twenty low-confidence clean
invoices, blind, to see whether the ordering matches what a person would say. Cheapest
check left and the one I most want.

Turn on schema enforcement for the prose extraction; I left it off so the prompt change
could be measured alone. Replace the four regex readers with the model and keep regex as
the test, since the next contract will not be a table. Run the question-answering test on
more than one model.

Make it live. It is batch by design: a hospital is priced as a whole in service date
order because cumulative discounts depend on earlier invoices, so a new invoice means
appending rows and re-running (two seconds). A deployed version would stream lines in
that order; the engine would not change.

## Tools

The ideas and the architecture are mine. I discussed them with Claude (Anthropic) and
used it, under my direction and with my review of every change, to write and review code,
run the evaluations and draft the documents. Development and the model runs were done in
Google Colab and on my own machine. Every prompt is in `prompts/` with a changelog of
what each change was measured against; every model reply is in `runs/`; the decision log
records what I decided by reading the contracts and what came from the data.
