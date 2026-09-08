"""The two contract facts that are free to extract.

`service_date_out_of_window` and `contract_number_mismatch` need nothing from a
contract except its number and its term. Every one of the five contracts states
both in a metadata block in the first ten lines, in the same format, so a regex
is the honest tool here — no LLM, no ambiguity, and it is trivially verifiable
by eye against the source document.
"""

import re
from datetime import datetime

from src.config import CONTRACTS

_NUM = re.compile(r"\*\*Contract number:\*\*\s*(\S+)")
_FROM = re.compile(r"\*\*Effective from:\*\*\s*(.+)")
_TO = re.compile(r"\*\*Effective to:\*\*\s*(.+)")


def _date(text):
    """Parse the '1 January 2024' form used in every contract header."""
    return datetime.strptime(text.strip(), "%d %B %Y").date()


def read_header(hospital):
    """Return {contract_number, effective_from, effective_to} for one hospital.

    Where a contract is split across several documents (hospital_3), every
    document repeats the same header; we read them all and assert they agree,
    so a disagreement surfaces as an error rather than a silent first-match win.
    """
    docs = sorted(( CONTRACTS / hospital ).glob("*.md"))
    seen = set()
    for path in docs:
        text = path.read_text()
        num, frm, to = _NUM.search(text), _FROM.search(text), _TO.search(text)
        if not (num and frm and to):
            continue
        seen.add((num.group(1), _date(frm.group(1)), _date(to.group(1))))
    if len(seen) != 1:
        raise ValueError(f"{hospital}: headers disagree across documents: {seen}")
    number, start, end = seen.pop()
    return {"contract_number": number, "effective_from": start, "effective_to": end,
            "documents": [p.name for p in docs]}
