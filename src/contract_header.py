"""The two contract facts that are free to extract.

`service_date_out_of_window` and `contract_number_mismatch` need nothing from a
contract except its number and its term. All five contracts state both in a
metadata block in the first ten lines, in the same format, so a regex is the honest
tool: exact, fast, and checkable by eye against the source document.
"""

import glob
import os
import re
from datetime import datetime

NUMBER = re.compile(r'\*\*Contract number:\*\*\s*(\S+)')
FROM   = re.compile(r'\*\*Effective from:\*\*\s*(.+)')
TO     = re.compile(r'\*\*Effective to:\*\*\s*(.+)')


def read_header(data_root, hospital):
    """Return {contract_number, effective_from, effective_to} for one hospital.

    Hospital 3's contract is three documents. Each repeats the same header, so we
    read them all and require agreement — a disagreement becomes an error rather
    than a silent first-match win.
    """
    docs = sorted(glob.glob(f'{data_root}/contracts/{hospital}/*.md'))
    seen = set()
    for path in docs:
        text = open(path).read()
        num, frm, to = NUMBER.search(text), FROM.search(text), TO.search(text)
        if not (num and frm and to):
            continue
        seen.add((num.group(1),
                  datetime.strptime(frm.group(1).strip(), '%d %B %Y').date(),
                  datetime.strptime(to.group(1).strip(), '%d %B %Y').date()))
    if len(seen) != 1:
        raise ValueError(f'{hospital}: headers disagree across documents: {seen}')
    number, start, end = seen.pop()
    return {'contract_number': number, 'effective_from': start,
            'effective_to': end, 'documents': [os.path.basename(d) for d in docs]}
