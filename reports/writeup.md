# Invoice audit: write-up

Repository: github.com/nxull9/invoice-audit
Predictions: `submission.csv`, 3,942 invoices for hospitals 2 to 5, 285 flagged (7.2%)

## What I tried first

The hardest looking part was matching invoice descriptions to contract services.
Descriptions arrive like `THER std HEP inf` and the contract calls it Standard Hepatic
Infusion Therapy, so my first instinct was text similarity. I built it. It got most of
them, it confused services that share words, and worst of all it had no way to say "I am
not sure".

Then I noticed something about the contracts. A contract can only produce a small set of
unit prices: the base rate, times any multiplier, plus a premium, minus a discount,
rounded after each step. That set is short enough to list. So instead of comparing words
I compared each description's usual price against every price the contract can generate.
That matched every description in all five hospitals with no model call, and text
similarity was left with one small job, breaking the rare ties where two services cost
the same. I kept it rather than deleting it, which mattered later.

The rest follows the same split. A model reads hospital 2's contract, because it is 40
pages of prose and nothing else will. Everything to do with money is plain Python in
integer cents, in the contract's order of adjustments, rounding half up after each step.
The model never sees an invoice and never produces a total.

## What I measured, and what worried me

Hospital 1 comes out at precision and recall 1.000 across all 18 categories, 909 of 913
expected totals exact. That made me suspicious rather than pleased. The system does not
predict, it recomputes, so a correct contract reading gives exact agreement by
construction. The score is a consequence of something else, so I went looking for it.

The number I actually trust is that 99.51% of hospital 1's 11,415 line items reprice to
the billed amount, to the cent. One misread rate would show up there as hundreds of
mismatches. I never report accuracy, because flagging nothing scores 93.6%.

Then I realised that number might be rigged: I match services by price, so of course
prices reproduce. I tested it three ways. First I separated the lines where a bundle, a
multiplier, a premium, an uplift or a discount had moved the rate away from the price
that did the matching. There are 13,608 of them and they reproduce at 98.6% to 99.6%, the
same as everything else. Second, I fitted the matching on half the invoices and measured
only on the other half, whose prices had never been seen: 99.35% to 99.64%. Third I threw
the price away and matched by text alone, the method from my first attempt, which dropped
reproduction to 93.5% to 96.2%. That last one is the answer I wanted. If the number were
an artefact of the method it would sit at 99% however I matched, and it does not.

Four of my decisions were fitted on hospital 1's labels, some on two examples, so I also
injected errors into invoices the labels call clean: 96 of 96 caught, no false positives
on 759 controls, same on three seeds. That covers eight of eighteen categories, so it is
evidence rather than proof.

## The four models, and what my comparison missed

I did not want to pick a model by reputation, so I gave four the same job: read the same
22 table batches, scored against the contracts I had already read with regex. All four
(GPT-4o, DeepSeek V3, Kimi K2, and a local 4-bit Qwen2.5-7B) found 307 of 307 services and
invented nothing. They differed only in speed and cost, from 5 seconds a call for GPT-4o
to 67 for Qwen on a Colab T4. My rule, written down before I looked: the fastest model
that invents nothing. That was GPT-4o.

Funnily enough, the exam told me almost nothing about the job that mattered. On hospital
2's prose, GPT-4o made seven mistakes and DeepSeek only two. Reading a table and reading
a clause are different skills, and I had tested the wrong one.

## The mistake that nearly shipped

Hospital 2 flagged 25.2% of its invoices while every other hospital sat near 7%. Nothing
crashed and no single number looked strange. I noticed only because I compare flag rates
across hospitals.

To find it I picked the subset that could prove me wrong: weekend lines on services with
a weekend uplift. There were 411, and 80 mismatched, and if two of the ten uplift
services were invented the arithmetic predicted 82. Then, because hospital 2's clauses
all follow one sentence shape, I could read each rule back with a pattern and compare it
with the model's answer service by service. GPT-4o had filed three threshold premiums as
daily caps. Every number was right; the field was wrong.

That is the failure I would warn anyone about. A wrong value that is well formed looks
exactly like a right one, so nothing downstream catches it. The fix was one added section
in the prompt showing the three look-alike sentence types side by side, which took GPT-4o
from seven defects to zero and DeepSeek from two to zero, and Kimi read it clean. Hospital
2 now reproduces 99.49% and flags 6.8%.

I hit the same pattern testing the question-answering command with 274 generated
questions. The model would quote the right clause and then multiply wrong (63,221 times 3
came back as 189,915), or count five when the answer was eight. So counting and arithmetic
moved into Python and the model only reads the question. It then answered 137 of 137.

## Where else it goes wrong, and where I am unsure

The daily cap category is the one I could not solve. The contract caps the quantity, the
labels imply a smaller original quantity it never states, and all four expected-total
misses are this. The flag is right and the amount is not, so it carries my lowest
confidence.

Two conventions rest on almost nothing: which invoice of a reused id is the wrong one
(five examples), and whether an out-of-term date is also reported as post-dated (two). A
description for a service not in the contract can also hit a real price by chance, which
two signals guard, tuned on twelve examples.

Hospital 2 defines a Service Day as 07:00 to 06:59 and the data has no times. I read the
recorded date as the start and wrote down what would prove me wrong. Measured afterwards,
4 of 335 weekend lines mismatched, which is noise. The reading held, but it was a reading.

Confidence is an ordering for review, not a probability, since there is nothing to
calibrate against beyond hospital 1. So I put two limits in: no flag is reported as
certain, because even an arithmetic finding is a claim about an invoice whose key I
reconstructed, and the two convention-fitted categories are capped at 0.90.

## What I left out, and what I would do next

The order was the table contracts, the engine and the matching, hospital 1, then hospital
2 with a model, then the model comparison, the question evaluation, and the checks above.
The submission was finished before most of the evaluation started.

I left out what an audit team needs around the audit, such as flag states with a history
and monitoring of the two label-free numbers. I would list those rather than build them
inside a take-home. I also did not calibrate confidence, which needs outcomes beyond
hospital 1.

Next I would re-read a sample by hand, twenty high-confidence flags and twenty
low-confidence clean invoices, blind, to see whether my ordering matches a person's. Then
turn on schema enforcement for the prose extraction, which I left off so the prompt change
could be measured alone, and replace the regex readers with the model, keeping regex only
as the test, because the next contract will not be a table.

## Tools

The ideas and the architecture are mine. I worked through them in discussion with Claude
(Anthropic) and used it, under my direction and with my review of every change, to write
and review code, run the evaluations and draft the documents. Development and the model
runs were in Google Colab and on my machine. Every prompt is in `prompts/` with a
changelog of what it was measured against, and every model reply is in `runs/`.
