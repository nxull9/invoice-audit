"""Helpers to read tables out of the markdown contracts. Columns are matched by header
text, not by position, because the contracts order the same columns differently.
"""

import re
from decimal import Decimal

_HEADING = re.compile(r"^#{2,3}\s+(.*)$", re.M)


def sections(text):
    """{heading: body} for every '##' or '###' heading in the document."""
    marks = [(m.start(), m.group(1).strip()) for m in _HEADING.finditer(text)]
    out = {}
    for i, (pos, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out[title] = text[pos:end]
    return out


def table(body):
    """Every data row of the markdown table(s) in `body`, as lists of cells.

    The header row and the `|---|` separator are dropped. A cell of '—' (the
    em dash the contracts use for "not applicable") becomes None.
    """
    rows, header = [], None
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells                    # first row of a table is its header
            continue
        rows.append([None if c in {"—", "-", ""} else c for c in cells])
    return rows, header


def columns(rows, header, *names):
    """Pull named columns out of a table by header text, not by position.

    Hospital 1's bundle table is `Service A | Service B | Rate A | Rate B`; hospital 5's
    is `Service A | Rate A | Service B | Rate B`. Reading by position silently swaps a
    service name for a price. Reading by header does not, and fails loudly if a column
    is missing.

    A name may list alternatives separated by `|`, because the five contracts label the
    same column differently -- "Not billable within" and "Window" both mean the length
    of an exclusion window. The first alternative that matches wins.
    """
    idx = []
    for want in names:
        chosen = None
        for alt in want.split("|"):
            matches = [i for i, h in enumerate(header) if alt.lower() in h.lower()]
            if matches:
                chosen = matches[0]
                break
        if chosen is None:
            raise KeyError(f"none of {want.split('|')!r} found in {header}")
        idx.append(chosen)
    return [[r[i] for i in idx] for r in rows]


def decimal_val(text):
    """'1.08' -> Decimal('1.08'). Via str, never via float."""
    return Decimal(str(text).strip())


def find(secs, *keywords):
    """The body of the first section whose heading contains all keywords."""
    for title, body in secs.items():
        low = title.lower()
        if all(k.lower() in low for k in keywords):
            return body
    return None


def cents(text):
    """'GBP 1,301.25' -> 130125. Exact: parsed as Decimal, never as float."""
    digits = re.sub(r"[^0-9.]", "", text)
    return int((Decimal(digits) * 100).to_integral_value())


def fraction(text):
    """'+20%' -> 0.20, '12%' -> 0.12. Returned as Decimal for exact arithmetic."""
    return Decimal(re.sub(r"[^0-9.]", "", text)) / Decimal(100)


def quantity(text):
    """'6 days', 'more than 10 items', '8 visits' -> 6, 10, 8."""
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None
