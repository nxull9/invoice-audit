# Invoice audit: write-up

Repository: github.com/nxull9/invoice-audit
Predictions: `submission.csv`, 3,942 invoices for hospitals 2 to 5, 285 flagged (7.2%)

## What I built

The system re-prices every invoice line under the hospital's contract and compares.

Four of the five contracts are tables. I read those with regex. Hospital 2 is 40 pages
of prose, so a language model reads it, one article at a time, and every reply is
checked against the text the model was shown before I accept it. From that point on
everything is plain Python in integer cents: the contract's order of adjustments,
rounding half up after each step, cumulative discounts counted in service date order
across the whole term. The model never sees an invoice and never produces a total.

Matching invoice descriptions to services turned out not to need a model. A contract
can only produce a small set of unit prices, so a description's usual price identifies
the service. Text similarity only breaks ties. Every description in all five hospitals
matched this way.

## How I measured the results

**On the labelled hospital.** Precision 1.000 and recall 1.000 across all 18
categories, and 909 of 913 expected totals exact. I do not take that score as the
evidence. The system recomputes instead of predicting, so a correct contract reading
gives exact agreement by construction. The number I trust is that 99.51% of hospital
1's 11,415 line items reproduce the billed amount to the cent. One misread rate would
show up there as hundreds of mismatches. I did not report accuracy: flagging nothing
scores 93.6%.

**Against memorising hospital 1.** Four decisions were fitted on its labels, some on
two examples. So I injected errors into invoices the labels call clean and checked
detection: 96 of 96 caught, 0 false positives on 759 clean controls, same on three
random seeds.

**On the hospitals with no labels.** Three signals. The line reproduction rate
(99.30% to 99.49%, the same band as hospital 1). The flag rate (6.8% to 7.5% against
hospital 1's true 6.4%). And a text-only clustering of descriptions that agrees with the
price-based matching at homogeneity 0.89, which is two methods with no shared
information giving the same answer.

**On the model.** I gave four models (GPT-4o, DeepSeek V3, Kimi K2, a local 4-bit
Qwen2.5-7B) the same 22 table batches, scored against the regex specs. All four found
307 of 307 services and invented none; they differed in speed (5 to 67 s a call) and
cost. My rule, set before the numbers: the fastest model that invents nothing, which was
GPT-4o.

Hospital 2 is the only contract without an answer key, and it is where the biggest
problem was. With the first prompt it flagged 25.2% of invoices. The weekend lines
pointed at the cause (411 lines, 80 mismatching; two phantom weekend uplifts would
predict 82). Because hospital 2's clauses are templated, I could read each rule back
with a pattern and compare service by service. GPT-4o had filed three threshold premiums
as daily caps: every number right, the field wrong. A second prompt version showing the
three look-alike sentence types side by side took GPT-4o from 7 defects to 0 and
DeepSeek from 2 to 0; Kimi K2 also read it clean. Hospital 2 now reproduces 99.49% of
its lines and flags 6.8%.

I also tested the question-answering command with 274 generated questions with known
answers. Where the model had to count or multiply it failed (6 of 7 services listed;
63,221 x 3 given as 189,915), so counting and arithmetic moved to Python. The final
version answered 137 of 137, including every off-topic and injection question.

## Where I was uncertain, and why

**The model's reading of hospital 2.** Zero defects under the final prompt, but the
checker is regex over one contract's wording. It proves this contract was read right,
not that the next one would be. Every confidence on hospital 2 is multiplied by 0.85
for that reason, so a reviewer sorting by confidence gets to it first.

**Daily cap totals.** The contract caps the quantity. The labels imply a smaller
original quantity that the contract does not state. I trim to the cap, flag the
invoice, and give this category the lowest confidence. All four expected total misses
are this.

**Conventions from a handful of examples.** Which invoice of a reused id is the wrong
one (five examples). Whether an out-of-term date is also reported as after the invoice
date (two). If hospitals 2 to 5 differ, nothing in my output would show it.

**Hospital 2's Service Day.** It runs 07:00 to 06:59 and the data has no times. I read
the recorded date as the start of the Service Day and wrote down what would prove me
wrong: systematic weekend mismatches on the eight uplift services. Measured after
extraction: 4 of 335 weekend lines, normal noise. The reading held, but it was a reading.

**Confidence.** It is built from evidence (category strength times service match
strength times contract source) and it is an ordering, not a probability. There is
nothing to calibrate it against beyond hospital 1, where everything is right.

## What I would do differently with another week

Turn on schema enforcement for the prose extraction; I left it off so the prompt change
could be measured alone. Replace the four regex readers with the model and keep the
regex only as the test, because the next contract will not be a table. Run the
question-answering test on DeepSeek and Kimi too. Calibrate confidence once there are
reviewed outcomes beyond hospital 1.

Make it live. Today it is batch by design: a hospital is priced as a whole in service
date order, because cumulative discounts depend on earlier invoices, so a new invoice
means appending its rows and re-running (two seconds per hospital). There is no queue
or live feed. A deployed version would stream lines from the billing database in that
order per hospital; the engine would not change. A new hospital already works from a
PDF (text layer, or OCR for a scan) as long as its contract is written like hospital
2's; a very different style would need the article splitter and prompt examples
adapted, and the line reproduction rate is the alarm that would tell me.

Scope it the way the brief says. This repository does more than eight hours allow, and
I built the most important check, the model against the text, last. Given the exercise
again I would ship the engine, the submission, that check and this write-up, and stop.
What an audit team would need next (flag states with history, monitoring of the two
label-free health numbers, a web page over the same modules) I would list rather than
build.

## Tools

The ideas and the architecture are mine. I discussed them with Claude (Anthropic) and
used it, under my direction and with my review of every change, to write and review
code, run the evaluations and draft the documents. Development and the model runs were
done in Google Colab and on my own machine. Every prompt is in `prompts/` with a
changelog of what each change was measured against. Every model reply is in `runs/`.
The decision log records what I decided by reading the contracts and what came from
the data.
