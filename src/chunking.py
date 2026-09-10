"""Splitting a contract into pieces a model can read.

Hospital 2 is 37,036 tokens; Qwen2.5-7B's context window is 32,768. The contract
does not fit, so chunking is forced rather than chosen -- by the smallest model in
the lineup, which is exactly the model that proves the pipeline can run air-gapped.

We chunk structurally, not semantically. The contract's own headings say which
articles carry rates: 13 titled 'Contracted Services (N Group)' hold all 76 rate
clauses, and 22 boilerplate articles hold none. A one-line filter on the heading
drops 49% of the document with no recall risk, because the heading states what the
section is. An embedding index would return the top-k most similar chunks; we need
all thirteen, and top-k is the wrong tool when you need everything.

Convention articles are pulled out separately rather than dropped silently. The task
description warns of a definitions section that quietly changes how days are
counted, and hospital 2 does exactly that.
"""

import re

from src.markdown_tables import sections

RATE_ARTICLE = 'Contracted Services'
CLAUSE = re.compile(r'^\d+\.\d+ In respect of', re.M)
CONVENTION_MARKERS = ['Definitions', 'Calculation Conventions', 'Interpretation']


def rate_chunks(text, marker=RATE_ARTICLE):
    """The articles that carry rates, as [{title, text, n_clauses}].

    `n_clauses` is how many Services the article should yield, counted by regex, so a
    model returning fewer has demonstrably missed some without needing a gold answer.
    """
    return [{'title': title, 'text': body.strip(), 'n_clauses': len(CLAUSE.findall(body))}
            for title, body in sections(text).items()
            if marker.lower() in title.lower()]


def dropped_chunks(text, marker=RATE_ARTICLE):
    """What the filter threw away, so it can be audited rather than trusted."""
    return [{'title': title, 'chars': len(body)}
            for title, body in sections(text).items()
            if marker.lower() not in title.lower()]


def chunk_stats(text, marker=RATE_ARTICLE):
    """What the filter kept and what it dropped."""
    kept, dropped = rate_chunks(text, marker), dropped_chunks(text, marker)
    kept_chars = sum(len(c['text']) for c in kept)
    dropped_chars = sum(c['chars'] for c in dropped)
    return {'articles_kept': len(kept),
            'articles_dropped': len(dropped),
            'clauses_expected': sum(c['n_clauses'] for c in kept),
            'tokens_kept': kept_chars // 4,
            'tokens_dropped': dropped_chars // 4,
            'fraction_dropped': round(dropped_chars / (kept_chars + dropped_chars), 3),
            'largest_chunk_tokens': max((len(c['text']) // 4 for c in kept), default=0)}


def convention_chunks(text, markers=None):
    """Articles that define terms or calculation order rather than rates."""
    markers = markers or CONVENTION_MARKERS
    return [{'title': title, 'text': body.strip()}
            for title, body in sections(text).items()
            if any(m.lower() in title.lower() for m in markers)]


def convention_checklist(text):
    """The conventions the engine depends on, quoted from the contract itself.

    Every one of these is implemented in `audit_engine`. Printing them beside the
    contract's own words is how we check the engine matches *this* hospital, rather
    than assuming all five contracts say the same thing.
    """
    body = ' '.join(c['text'] for c in convention_chunks(text))
    wanted = {
        'rounding': r'rounded to the nearest whole cent[^.]*',
        'rounding_step': r'Rounding is applied[^.]*',
        'adjustment_order': r'adjustments shall be applied to the base rate[^.]*',
        'service_day': r'"Service Day" means[^.]*',
        'business_day': r'"Business Day" means[^.]*',
        'cumulative': r'"Cumulative utilisation" means[^.]*',
    }
    out = {}
    for key, pattern in wanted.items():
        m = re.search(pattern, body)
        out[key] = m.group(0).strip() if m else None
    return out


# --------------------------------------------------------------------------
# Tabular contracts, batched
# --------------------------------------------------------------------------
# Hospital 3's rate schedule is 118 rows. Asking for all of them in one reply needs
# roughly 9,400 output tokens against a 4,096 limit, so the JSON would be truncated
# mid-object and the model would score zero for a reason unrelated to whether it can
# read. Batching keeps every reply comfortably inside the limit.
#
# This is a real constraint of the task rather than a workaround: output length is a
# harder ceiling than context length, and a system that ignores it fails silently on
# exactly the largest documents.

TABLE_BATCH = 15


def table_chunks(text, markers, batch_size=TABLE_BATCH, min_rows=3):
    """Rate tables from a tabular contract, split into batches of `batch_size` rows.

    Each batch keeps the table header so it remains readable on its own.
    """
    out = []
    for title, body in sections(text).items():
        if not any(m.lower() in title.lower() for m in markers):
            continue
        lines = [l for l in body.splitlines() if l.strip().startswith("|")]
        if len(lines) < min_rows + 2:
            continue
        header, rows = lines[:2], lines[2:]
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            out.append({
                "title": f"{title} [rows {start + 1}-{start + len(batch)}]",
                "text": "\n".join(header + batch),
                "n_clauses": len(batch),
            })
    return out
