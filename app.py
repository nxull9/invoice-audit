"""Interactive invoice audit.

    python app.py                       start a prompt
    python app.py audit INV-H3-000142   run one command and exit

Contracts are read once per hospital and cached for the session. The only commands
that call a model are `ask` (always) and `audit`/`submit` on a prose hospital whose
extraction has not been recorded (never, for the shipped recordings).
"""

import os
import sys
import textwrap

import pandas as pd

from src import ask as ask_mod
from src import audit, config, output, scoring
from src.compile_contract import COMPILERS
from src.contract_table import spec_to_table
from src.contracts import summarise
from src.data import load_invoices, load_labels
from src.llm import ApiModel

DATA = str(config.DATA)
HELP = """
  audit INV-H3-000142        audit one invoice and explain the result
  audit hospital_4           audit every invoice in a hospital
  ask hospital_4 <question>  answer from that hospital's contract only (h4 also works)
  ask <question>             ask every contract; each answers from its own clauses
  explain INV-H4-000105      the model narrates the audit result in plain English
  contract hospital_2        show the rules read from a contract
  extract hospital_2 [model] [prompt]   read a prose contract with a model (live if unrecorded)
  evaluate                   score hospital 1 against its labels
  submit                     write submission.csv for hospitals 2-5
  help / quit
"""

_results = {}       # hospital -> audit result, computed on first use
_indexes = {}       # hospital -> clause index for `ask`, embedded once per session


def load_env(path=".env"):
    """KEY=value lines into the environment, without a dependency."""
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def result_for(hospital):
    if hospital not in _results:
        print(f"  reading {hospital} ...", end="", flush=True)
        _results[hospital] = audit.audit_hospital(DATA, hospital)
        print(" done")
    return _results[hospital]


def money(cents):
    return f"{cents:,} cents  (GBP {cents / 100:,.2f})"


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_audit(target):
    if target in config.HOSPITALS:
        return audit_whole_hospital(target)
    hospital = audit.hospital_of(target)
    if hospital not in config.HOSPITALS:
        print(f"  '{target}' is not an invoice id like INV-H3-000142 or a hospital like hospital_3")
        return
    explanation = output.explain_invoice(result_for(hospital), target)
    if explanation is None:
        print(f"  {target} is not in {hospital}'s invoice file")
        return
    show_invoice(explanation)


def show_invoice(e):
    print()
    print(f"  hospital       {e['hospital']}")
    print(f"  invoice        {e['invoice_id']}   dated {e['invoice_date']}   patient {e['patient_id']}"
          + ("   (identifier reused; this is the later invoice)" if e["reused_id"] else ""))
    print(f"  contract       {e['contract_number']}   read from {e['contract_source']}")
    print(f"  billed         {money(e['billed_total_cents'])}")
    print(f"  expected       {money(e['expected_total_cents'])}")
    diff = e["billed_total_cents"] - e["expected_total_cents"]
    if diff:
        print(f"  difference     {'+' if diff > 0 else ''}{diff:,} cents")
    print(f"  flagged        {'YES' if e['flagged'] else 'no'}"
          + (f"   {' | '.join(e['categories'])}" if e["categories"] else ""))
    print(f"  confidence     {e['confidence']}")
    if e["evidence"]:
        print("  why")
        for line in e["evidence"]:
            print(textwrap.fill(line, 100, initial_indent="    - ", subsequent_indent="      "))
    changed = [l for l in e["lines"] if l["billed_total"] != l["expected_total"]]
    shown = changed or e["lines"][:5]
    print(f"  lines          {len(e['lines'])} total, showing {len(shown)}"
          + (" that differ" if changed else " (all reproduce the billed amount)"))
    for l in shown:
        exp = "?" if l["expected_rate"] is None else l["expected_rate"]
        print(f"    {l['line_id']}  {l['service_date']}  {l['description'][:34]:34}  "
              f"-> {l['service'][:34]:34}  {l['qty']:>3} x {l['billed_rate']:>7} "
              f"(expected {exp:>7})  {l['adjustments']}")
    print()


def audit_whole_hospital(hospital):
    r = result_for(hospital)
    rows = output.submission_rows(r)
    flagged = rows[rows.flagged == 1]
    print()
    print(f"  {hospital}: {len(rows)} invoices, {len(flagged)} flagged ({len(flagged) / len(rows):.1%})")
    print(f"  line items reproducing the billed amount: "
          f"{(r['priced'].expected_line_total == r['priced'].line_total_cents).mean():.2%}")
    counts = r["findings"].groupby("category").invoice_id.nunique().sort_values(ascending=False)
    for cat, n in counts.items():
        print(f"    {n:>4}  {cat}")
    unresolved = (r["resolution"].method == "unresolved").sum()
    ambiguous = (r["resolution"].method == "ambiguous").sum()
    if unresolved or ambiguous:
        print(f"  descriptions unresolved {unresolved}, ambiguous {ambiguous} -- review before trusting")
    if r["spec"]["warnings"]:
        print(f"  contract warnings: {len(r['spec']['warnings'])} (see `contract {hospital}`)")
    print()


def cmd_contract(hospital):
    if hospital not in config.HOSPITALS:
        print(f"  unknown hospital '{hospital}'"); return
    spec = result_for(hospital)["spec"]
    print()
    for k, v in summarise(spec).items():
        print(f"  {k:20} {v}")
    prov = {k: v for k, v in spec["provenance"].items()}
    print(f"  provenance           {prov}")
    for w in spec["warnings"][:10]:
        print(f"  warning: {w}")
    table = spec_to_table(spec)
    cols = ["service", "unit_basis", "rate_cents", "daily_cap", "nbd_uplift_pct",
            "premium_threshold", "premium_uplift_pct", "discount_threshold", "discount_pct",
            "bundle_partner"]
    with pd.option_context("display.width", 200, "display.max_rows", 20):
        print()
        print(table[cols].head(15).to_string(index=False))
        print(f"  ... {len(table)} rows in total")
    print()


def hospital_named(word):
    """'hospital_3' or 'h3' -> 'hospital_3'; anything else -> None."""
    word = word.lower()
    if word in config.HOSPITALS:
        return word
    if len(word) == 2 and word[0] == "h" and word[1].isdigit() and f"hospital_{word[1]}" in config.HOSPITALS:
        return f"hospital_{word[1]}"
    return None


def index_for(hospital):
    if hospital not in _indexes:
        print(f"  indexing {hospital}'s contract ...", end="", flush=True)
        _indexes[hospital], _ = ask_mod.clause_index(DATA, hospital)
        print(" done")
    return _indexes[hospital]


def cmd_ask(words):
    """`ask hospital_3 <question>` scopes to one contract; `ask <question>` tries them all."""
    hospital = hospital_named(words[0]) if words else None
    question = " ".join(words[1:] if hospital else words).strip()
    if not question:
        print("  ask needs a question"); return
    try:
        model = ApiModel(config.EXTRACTION_MODEL)
    except RuntimeError as exc:
        print(f"  {exc}\n  `ask` calls a model live. Put OPENROUTER_API_KEY=... in .env and try again.")
        return
    if hospital:
        ask_mod.ask(question, index_for(hospital), model, hospital, table=rules_for(hospital))
    else:
        ask_mod.ask_every_hospital(question, {h: index_for(h) for h in config.HOSPITALS}, model)


def rules_for(hospital):
    """The verified rules table the model may answer set questions from."""
    return spec_to_table(result_for(hospital)["spec"])


def cmd_explain(invoice_id):
    hospital = audit.hospital_of(invoice_id)
    if hospital not in config.HOSPITALS:
        print(f"  '{invoice_id}' is not an invoice id like INV-H3-000142"); return
    explanation = output.explain_invoice(result_for(hospital), invoice_id)
    if explanation is None:
        print(f"  {invoice_id} is not in {hospital}'s invoice file"); return
    try:
        model = ApiModel(config.EXTRACTION_MODEL)
    except RuntimeError as exc:
        print(f"  {exc}\n  `explain` calls a model live; `audit {invoice_id}` gives the same facts without one.")
        return
    show_invoice(explanation)
    print("  in plain English:")
    ask_mod.explain_with_model(explanation, model)


def cmd_extract(hospital, model=None, version=None):
    """Read a prose contract with a model. Replays if recorded, otherwise calls live and records."""
    if hospital not in config.HOSPITALS:
        print(f"  unknown hospital '{hospital}'"); return
    if hospital in COMPILERS:
        print(f"  {hospital} is read from tables by regex; nothing to extract"); return
    try:
        spec = audit.load_spec(DATA, hospital, model_name=model, prompt_version=version, verbose=True)
    except RuntimeError as exc:
        print(f"  {exc}"); return
    prov = spec["provenance"]
    print(f"\n  {prov['model']} / {prov['prompt_version']}  "
          f"{'replayed' if prov['replayed'] else 'ran live and recorded to runs/'}")
    print(f"  services {prov['services_accepted']}/{prov['clauses_expected']}  "
          f"parse failures {prov['parse_failures']}  warnings {len(spec['warnings'])}")
    for k, v in summarise(spec).items():
        if k in ("daily_caps", "threshold_premiums", "nbd_uplifts", "volume_discounts", "bundles"):
            print(f"    {k:20} {v}")
    if hospital == "hospital_2":
        from evaluation.verify_hospital_2 import verify
        print("  checked against the contract text:")
        verify(spec, config.CONTRACTS / hospital / "master_services_agreement.md")
    _results.pop(hospital, None)              # the cached audit used the old spec


def cmd_evaluate():
    r = result_for(config.DEV_HOSPITAL)
    labels = load_labels(DATA)
    scoring.report(r["findings"], labels, f"{config.DEV_HOSPITAL} against its labels")
    rows = output.submission_rows(r).merge(labels[["invoice_id", "expected_total_cents"]],
                                           on="invoice_id", suffixes=("", "_label"))
    exact = (rows.expected_total_cents == rows.expected_total_cents_label).sum()
    print(f"\nexpected_total_cents exact: {exact} / {len(rows)}")


def cmd_submit(path="submission.csv"):
    results = [result_for(h) for h in config.SCORED_HOSPITALS]
    expected = pd.concat([load_invoices(DATA, h)["invoice_id"] for h in config.SCORED_HOSPITALS])
    submission = output.write_submission(results, path, expected_ids=set(expected))
    print(f"\n  {path}: {len(submission)} rows, {submission.flagged.sum()} flagged "
          f"({submission.flagged.mean():.1%}), validated")
    for h in config.SCORED_HOSPITALS:
        part = submission[submission.invoice_id.map(audit.hospital_of) == h]
        print(f"    {h}: {len(part)} invoices, {part.flagged.sum()} flagged, "
              f"mean confidence {part.confidence.mean():.3f}")
    print()


def run(command):
    parts = command.strip().split(maxsplit=2)
    if not parts:
        return True
    verb, args = parts[0].lower(), parts[1:]
    try:
        if verb in ("quit", "exit", "q"):
            return False
        elif verb == "help":
            print(HELP)
        elif verb == "audit" and len(args) == 1:
            cmd_audit(args[0])
        elif verb == "ask":
            cmd_ask(command.strip().split()[1:])
        elif verb == "explain" and len(args) == 1:
            cmd_explain(args[0])
        elif verb == "contract" and len(args) == 1:
            cmd_contract(args[0])
        elif verb == "extract" and len(args) >= 1:
            rest = (args[1].split() if len(args) > 1 else [])
            cmd_extract(args[0], *(rest[:2]))
        elif verb == "evaluate":
            cmd_evaluate()
        elif verb == "submit":
            cmd_submit()
        else:
            print(f"  unknown command. {HELP}")
    except Exception as exc:                 # a failure must not take the session down
        print(f"  error: {type(exc).__name__}: {exc}")
    return True


def main(argv):
    load_env()
    if argv:
        run(" ".join(argv))
        return
    print("invoice audit -- five hospitals, five contracts. Type `help`.")
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not run(line):
            break


if __name__ == "__main__":
    main(sys.argv[1:])
