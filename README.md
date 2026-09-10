# Invoice Audit — Meridian Health Assurance Group

Auditing 61,211 hospital invoice line items against five separately negotiated
contracts, and identifying the erroneous invoices.

| | |
|---|---:|
| Detection on the labelled hospital | **precision 1.000 · recall 1.000 · F1 1.000** |
| `expected_total_cents` exact | **909 / 913** |
| Line items reproducing the billed amount | **99.30 – 99.51%** |
| Injected faults detected, zero false positives | **96 / 96** |
| Descriptions left unresolved | **0** |
| Model calls for the whole submission | **under 150** |

---

## Reproducing the submission

```bash
git clone https://github.com/nxull9/invoice-audit
cd invoice-audit
pip install -r requirements.txt
python -m pytest tests -q          # 12 regression tests
jupyter notebook notebooks/invoice_audit.ipynb
```

Run the notebook top to bottom. It writes `submission.csv`.

**No API key or GPU is required.** Every model reply is recorded in `runs/` and replayed,
so inference — the only non-deterministic and non-free step — reproduces exactly. Set
`FORCE_RERUN = True` to call the models live instead.

On Colab the notebook clones the dataset and builds its own `src/` package, so it runs
from the notebook file alone:

<a href="https://colab.research.google.com/github/nxull9/invoice-audit/blob/main/notebooks/invoice_audit.ipynb">Open in Colab</a>

---

## Approach

**A model reads English. Python does arithmetic. No value a model produces is used until
the deterministic engine reproduces the invoice totals from it.**

Four of the five contracts state their rules in tables and are parsed by regex. Hospital
2 states 76 rate clauses as prose across 35 articles and is the only contract requiring
a language model. All five compile into one representation, so the pricing engine is
written once.

### Resolving descriptions to services

108 contracted services appear under 488 distinct billing descriptions — abbreviated
(`Rtn`, `Compr`, `Ent` for Otolaryngologic), reordered, truncated, suffixed with noise
codes. The task description frames this as the central difficulty.

It is not solved lexically. A contract can produce only a small enumerable set of unit
rates: base, bundled, each multiplied by any facility and plan-tier multiplier, any
premium, any volume discount, rounded half-up at each step. Matching a description's
modal `(unit_basis, unit_price_cents)` against that set identifies the service.

**This resolves every description on every hospital.** Text similarity is used only to
break genuine price collisions, and — where it contradicts the price — to identify
services absent from the contract altogether.

### Repricing

A single ordered pass. Cumulative volume discounts depend on utilisation *prior to* each
line, counted across the whole term and all patients, so invoices are not independent and
cannot be parallelised. Adjustment order is taken verbatim from the contracts: bundle
substitution, facility multiplier, plan-tier multiplier, premium, volume discount, with
half-up rounding after each step. All money is integer cents.

---

## Repository

```
notebooks/invoice_audit.ipynb   the analysis; builds src/ and writes submission.csv
src/                            19 modules, importable and tested
prompts/                        3 prompt versions + CHANGELOG explaining each revision
reports/evaluation.md           per-category results and failure analysis
reports/decision_log.md         assumptions, ambiguities, and what was decided
runs/                           recorded model replies, so the submission replays free
tests/                          12 regression tests
submission.csv                  predictions for hospitals 2–5
```

---

## AI assistance

This project was built with AI assistance throughout — architecture discussion, code,
and drafting. It is disclosed in three places:

- `prompts/` holds every prompt sent to a model, versioned, with `CHANGELOG.md`
  recording why each revision was made and what risk it introduced.
- `runs/` holds every raw model reply, so any extraction can be traced to its source.
- `reports/decision_log.md` records which judgements were made by a human reading the
  contracts, and which were derived from data.

The models under evaluation (GPT-4o, Kimi K2, DeepSeek, Qwen2.5-7B) perform exactly one
task: reading hospital 2's prose contract into a structured specification. No model
computes a monetary value, decides whether an invoice is erroneous, or contributes to
`submission.csv` except through a specification the deterministic engine then verifies.

---

## Known limitations

Fully described in `reports/evaluation.md` §6. In brief:

1. `daily_cap_exceeded` expected totals are not recoverable from the contract; the four
   `expected_total_cents` misses are all this category.
2. Four conventions were calibrated on hospital 1's labels, two of them on five and two
   examples respectively.
3. Hospital 2's extraction cannot be checked against a known-correct specification —
   that is why it needs a model — and is validated indirectly.
4. Hospital 2 redefines "Service Day" as 07:00–06:59. The data carries no times, so the
   ambiguity is unresolvable; the reading taken and the test that would falsify it are
   in `decision_log.md` §6.
