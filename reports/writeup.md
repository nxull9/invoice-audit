# Invoice audit — write-up

**Repository:** github.com/nxull9/invoice-audit · **Predictions:** `submission.csv`, 3,942
invoices across hospitals 2–5, 285 flagged (7.2%).

## What I built

A system that reprices every invoice line under the hospital's own contract and
compares. Four contracts are tables; regex reads them. Hospital 2 is forty pages of
prose; a language model reads that into the same structure, and every reply is
validated against the text it came from. From there everything is deterministic Python
in integer cents: the contract's adjustment order, half-up rounding after each step,
cumulative discounts counted in service-date order across the whole term. The model
never sees an invoice and never produces a total or a verdict.

Matching billing descriptions to services turned out not to need a model. A contract
can only produce a small set of unit prices, so a description's most common
`(unit basis, price)` identifies the service; text similarity only breaks the rare
two-way ties, and how decisively it does so sets the confidence. Every description on
every hospital resolves. `python app.py` audits an invoice, a hospital, or answers a
question about a contract; `FINAL_WALKTHROUGH.md` maps every concept to its file.

## How I measured

**On the labelled hospital.** Precision 1.000, recall 1.000 across all 18 categories,
909 of 913 expected totals exact. I do not lead with that number. The system recomputes
rather than predicts, so a correct contract reading gives exact agreement by
construction. The number I trust is that **99.51% of hospital 1's 11,415 line items
reproduce their billed amount to the cent** — a single misread rate would appear there
as hundreds of mismatches. Accuracy is not reported: flagging nothing scores 93.6%.

**Against memorisation.** Four conventions were fitted on hospital 1's labels, some on
two examples. So I injected faults into invoices the labels call clean — errors the
label file does not contain — and measured detection: 96 of 96 caught, 0 false positives
on 759 clean controls, identical on three seeds. The engine generalises; the tie-breaking
conventions are still assertions.

**On the hospitals with no labels.** Three signals, none of them a score. The line
reproduction rate (99.30–99.49%, same band as hospital 1); the flag rate (6.8–7.5%
against hospital 1's true 6.4%); and a text-only clustering of descriptions that
recovers the price-based assignment at homogeneity 0.89 — two methods sharing no
information agreeing.

**On the model.** Hospital 2 is the only contract without an answer key, and it is where
I found the most important problem. Under the first pinned model the flag rate was
25.2%. A weekend-only subset localised it (411 lines, 80 mismatches; the "two phantom
uplifts" hypothesis predicted 82), and because hospital 2's clauses are templated I
could read each rule back with a pattern and compare service by service. GPT-4o had
filed three threshold-premium clauses as daily caps — every number right, the field
wrong, seven defects. DeepSeek under the same prompt made two. I wrote a second prompt
version that only adds one section putting the three look-alike sentence shapes side by
side, ran it on both models, and checked it the same way: **seven to zero, two to zero,
rates still 76/76**. Hospital 2 now reproduces 99.49% and flags 6.8%. The tabular model
exam had ranked the two models equal; it measured table reading and I had taken it as
evidence about prose reading, which it was not. I then put the contract Q&A through 274 generated questions
with known answers; where the model had to count or multiply it failed (88.7% → it named
6 of 7, multiplied 63,221 × 3 as 189,915), so counting and arithmetic moved to Python
and the final configuration answered 137 of 137, including every off-topic trap.

## Where I was uncertain, and why

**The model's reading of hospital 2.** Zero verified defects under the final prompt —
but the verifier is regex over one contract's templated wording, so it is evidence about
this contract, not a promise about the next. Every confidence on hospital 2 is still
multiplied by 0.85, so a reviewer sorting by confidence reaches it first. I ran the
revised prompt on two of the four models, not all.

**`daily_cap_exceeded` totals.** The contract caps quantity; the labels imply a smaller
pre-inflation quantity the contract does not state. I trim to the cap, flag the invoice,
and give this category the lowest confidence. The four expected-total misses are all this.

**Conventions fitted on a handful of examples.** Which of a reused-identifier pair is
the offender (five examples), and whether an out-of-term date is also reported as
post-dating its invoice (two). If hospitals 2–5 differ, nothing in my output would show it.

**Hospital 2's "Service Day"** runs 07:00–06:59 and the data has no times. I read the
recorded date as the commencing date and stated what would falsify that: systematic
weekend mismatches on the eight uplift services. Measured after extraction: 4 of 335
weekend lines, ordinary noise. The reading held, but it was a reading.

**Confidence itself** is composed from evidence — category strength × weakest resolution
× contract source — and is an ordering, not a calibrated probability. There is nothing
to calibrate against beyond hospital 1, where every prediction is right.

## What I would do differently with another week

**Enforce the extraction schema at the sampler** for the prose run — I left it off so
the prompt change would be measurable on its own, and now that it is, it is the next
change. **Run prompt v2 on the remaining models** and keep the verifier as a regression
test for any future prompt edit. **Replace the four
regex compilers with the model** and keep them only as the test oracle, since the next
contract will not be a table. **Calibrate confidence** once there are outcomes beyond
hospital 1 — even a hundred reviewed hospital 2 flags would do. **Sequence
differently:** I built more evaluation machinery than the brief's budget warranted
before the most important check — the model against the text — and found the biggest
error last. The verifier should have existed before the first model call.

## AI assistance

Built with Claude throughout: architecture discussion, code, tests and drafting, from
my direction and with my review. Every prompt is in `prompts/` with a changelog of what
each revision was measured against; every model reply is in `runs/`; the decision log
records what was decided by reading the contracts and what was derived from the data.
