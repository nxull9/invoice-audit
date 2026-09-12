# Invoice Audit

Finds erroneous hospital invoices by repricing every line item under the hospital's own
contract. Five hospitals, five differently written contracts, 61,211 line items.

| | |
|---|---:|
| Detection on the labelled hospital | **precision 1.000 · recall 1.000** (58 of 58) |
| `expected_total_cents` exact | **909 / 913** |
| Line items reproducing the billed amount, all five hospitals | **99.30 – 99.51%** |
| Injected faults caught, zero false positives | **96 / 96** |
| Model calls needed to reproduce the submission | **0** (replayed from `runs/`) |

---

## What it does

For each invoice: read the hospital's contract, work out what every line should have
cost under it, compare with what was billed, name the rule that was broken, and say how
sure it is. `submission.csv` carries one row per invoice for hospitals 2–5.

## Architecture

```
contract (.md / .pdf)
   │  tables → regex            prose → a language model, every reply validated
   ▼
 spec  ── one plain dict per hospital; the only thing the engine reads
   │
invoices ─► resolver ─► pricing ─► checks + classifier ─► confidence ─► submission.csv
            (description   (integer cents,   (which rule       (from evidence)
             → service      ordered steps,    was broken)
             by price)      half-up rounding)
```

**A model reads English. Python does arithmetic.** The model touches two things: reading
hospital 2's prose contract into the spec (13 calls, recorded), and answering questions
you type in the app. It never sees an invoice and never produces a total or a verdict.

## Why a language model, and where

Four contracts are tables and are read by regex, matching columns by header text. The
fifth is forty pages of prose — 76 rate clauses, each with its own caps, premiums,
weekend uplifts, volume discounts and bundles written as sentences. That is a reading
task. The model's output is validated (service name must appear in the text it was
given; rates must be positive integers; unit bases must be known), assembled into the
same spec the regex path produces, and then checked rule by rule against the contract
text (`evaluation/verify_hospital_2.py`). Section 6 of the evaluation report shows what
that check found and what was done about it.

## Why Python for the money

Every contract says: round half-up to the cent *after each step*, in a stated order —
bundle, facility multiplier, plan-tier multiplier, premium or uplift, volume discount.
Cumulative volume discounts count utilisation *before* each line across the whole term,
so invoices are not independent. That is a deterministic procedure and it is written
once, in `src/pricing.py`, with `Decimal` and never `float`. On hospital 5, rounding at
each step versus once at the end differs on 10.8% of rate combinations.

## How descriptions are matched to services

Descriptions are abbreviated and reordered (`THER std HEP inf` → *Standard Hepatic
Infusion Therapy*). Text matching alone is unreliable. But a contract can only produce
a small set of unit prices — base × multipliers, ± premium, − discount, rounded at each
step. Enumerating that set and matching a description's most common `(unit basis,
price)` against it identifies the service exactly. Text similarity only breaks the rare
two-way collisions, and how decisively it breaks them sets the confidence; below a floor
the description is reported **ambiguous** with both candidates named. No model call.
Every description on every hospital resolves.

## Contracts that arrive as PDF

The exercise ships Markdown, but a new provider sends a PDF. `src/ingest.py` reads a
contract by the most trustworthy route available: Markdown or plain text (exact), then a
PDF's embedded text layer (exact), then OCR (not exact — digits are repaired inside
`GBP` amounts only, the route is recorded, and every rate from that contract carries
reduced confidence). A PDF's text layer loses the article headings, so the prose chunker
falls back to grouping clauses by their article number. Hospital 2 loaded from its PDF
alone produces a spec identical to the one from its Markdown (`tests/test_runtime.py`).
OCR needs `pip install -r requirements-optional.txt` plus the `tesseract` and `poppler`
binaries; without them an image-only PDF is reported as unreadable, not silently skipped.

## How an invoice is audited

1. Seven checks that need no contract: line arithmetic, invoice total, reused
   identifier, malformed date, date after invoice, date outside the term, contract number.
2. Every line repriced under the spec. The engine also records what the rate *would*
   have been without the discount, without the premium, at the standalone rate, at each
   other multiplier cell — so when the billed rate matches one of those, the finding
   names that rule (`volume_discount_omitted`, not "price mismatch").
3. Expected invoice total = sum of expected line totals; lines for a service the
   contract does not list keep their billed amount.

## How confidence works

Three factors multiplied: the weakest category's strength (1.00 for arithmetic and
calendar facts, 0.75–0.92 for rule-based findings) × the weakest service resolution on
the invoice × the contract source (1.00 regex, 0.85 model). Arithmetic facts skip the
last two. A clean invoice starts at 0.95, never 1.0. It is an ordering by how much
depends on a judgement, not a calibrated probability.

---

## Running it

```bash
git clone https://github.com/nxull9/invoice-audit
cd invoice-audit
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

No API key is needed for anything below except `ask`.

### The interactive app

```bash
python app.py
```

```
> audit INV-H4-000105          one invoice: billed, expected, flagged, why, confidence
> audit hospital_4             every invoice in a hospital, with the category counts
> contract hospital_2          the rules read from a contract, as a table
> extract hospital_2           read the prose contract with the model (replays the recording)
> ask hospital_4 is there a premium on hepatic infusion therapy?     (needs a key)
> evaluate                     hospital 1 against its labels
> submit                       write submission.csv
```

Any command also runs directly: `python app.py audit INV-H2-000010`.

### Generate the submission

```bash
python app.py submit
```

Audits hospitals 2–5, validates columns, types, ranges and coverage, writes
`submission.csv`. Deterministic: a fresh clone produces a byte-identical file.

### Tests and evaluation

```bash
python -m pytest tests -q            # 30 tests, ~16 s
python app.py evaluate               # precision / recall / F1 per category on hospital 1
python evaluation/regression.py      # current outputs vs the pre-refactor baseline
python evaluation/verify_hospital_2.py [model] [prompt]   # the model's reading vs the text
```

### Asking the contract a question

Put a key in `.env` (`OPENROUTER_API_KEY=...`; the file is git-ignored). `ask` retrieves
the most relevant clauses from **one** hospital's contract — the hospital filter is a
hard mask, not a similarity penalty — and the model answers only from those, quoting the
clause. If the clauses do not contain the answer it says so.

### Re-running the extraction live

```bash
python app.py extract hospital_2 gpt-4o prose_v2      # replays the shipped recording
python app.py extract hospital_2 kimi-k2 prose_v2     # unrecorded: calls live, records
```

Prints the rule-by-rule check against the contract. Prompt v1 → v2 took gpt-4o from 7
rule defects to 0 and deepseek from 2 to 0; `prompts/CHANGELOG.md` has the measurement.

---

## Repository

```
app.py                     interactive entry point
src/                       the runtime — 19 files, nothing notebook-only
  audit.py                 load_spec (regex or model) and the per-hospital pipeline
  pricing.py               the engine
  resolver.py              description → service
  classify.py, checks.py   which rule was broken; contract-free checks
  output.py                confidence, explanation, submission + validation
  extract.py, llm.py       prose contract → spec; the model client and replayer
  compile_contract.py      the four table readers
  ask.py, retrieval.py     contract Q&A over one hospital's clauses
prompts/                   versioned prompts + CHANGELOG with the measured reason for each
runs/                      every model reply, recorded; the submission replays without a key
evaluation/                fault injection, model exam, local model, hospital 2 verifier, baseline
tests/                     26 tests
reports/                   evaluation.md · decision_log.md · requirements_checklist.md · writeup.md
notebooks/                 the research notebook; imports src/, produces nothing src/ does not
FINAL_WALKTHROUGH.md       the system explained for the person presenting it
```

## Key results, hospital 1

Precision 1.000, recall 1.000 across all 18 categories; 909 of 913 expected totals
exact (the four misses are one category whose true quantity the contract does not
state); 99.51% of line items reproduce their billed amount to the cent. Full tables,
per-category support, and the four systematic failure modes: `reports/evaluation.md`.

## Known limitations

1. **Hospital 2 was read by a model.** Its reading is verified rule by rule against the
   contract text (0 defects under prompt v2), but that check is regex over one
   contract's templated wording — evidence about this contract, not a general oracle.
2. **Prompt v2 was run on two of four models.** Kimi K2 and the local Qwen were not
   re-run.
3. `daily_cap_exceeded` expected totals are not recoverable from the contract.
4. Four conventions were calibrated on hospital 1's labels, two of them on five and two
   examples respectively.
5. Confidence is an ordering, not a calibrated probability.
6. Hospital 2's "Service Day" runs 07:00–06:59 and the data carries no times; the
   reading taken made a falsifiable prediction that was tested and held
   (`decision_log.md` item 6).
7. An OCR-read contract is only as good as the OCR. Rates from it are marked inexact
   and their confidence reduced, but a misread digit that survives repair is invisible
   downstream. The exercise's PDFs all carry text layers, so this path was exercised on
   a demo page, not on scored data.

## AI assistance

This project was built with Claude (Anthropic) throughout — architecture discussion,
code, tests, and drafting of every document, working from my direction and with my
review at each step. The record of that is in the repository itself: `prompts/` holds
every prompt sent to a model with a changelog saying what each revision was measured
against; `runs/` holds every raw model reply; `reports/decision_log.md` records which
judgements were made by reading the contracts and which were derived from the data.

The models under evaluation (GPT-4o, Kimi K2, DeepSeek, Qwen2.5-7B) perform one task
in the system: reading hospital 2's prose contract into a structured specification. No
model computes a monetary value, decides whether an invoice is erroneous, or contributes
to `submission.csv` except through a specification the deterministic engine then
verifies.
