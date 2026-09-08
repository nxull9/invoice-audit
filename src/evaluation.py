"""Scoring predictions against the hospital_1 labels.

Two things are measured separately, because they fail for different reasons:

* **Detection** — did we flag the right invoices? Reported as precision,
  recall and F1 at the invoice level. With 58 erroneous invoices in 913,
  accuracy is meaningless here and is deliberately not reported.
* **Attribution** — for the invoices we flagged, did we name the right
  category? Reported per category, because the categories have very
  different costs to get wrong.

A per-category recall of 1.0 on a category with four instances is not
evidence of much; the support column is printed for that reason.
"""

import pandas as pd


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def detection_scores(predicted_ids, labels):
    """Invoice-level precision/recall/F1 for "is this invoice erroneous?"."""
    truth = set(labels.loc[labels["is_erroneous"] == 1, "invoice_id"])
    pred = set(predicted_ids)
    known = set(labels["invoice_id"])
    pred = pred & known                      # ignore ids absent from the label file
    tp, fp, fn = len(pred & truth), len(pred - truth), len(truth - pred)
    p, r, f = _prf(tp, fp, fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f,
            "n_truth": len(truth), "n_pred": len(pred)}


def category_scores(findings, labels):
    """Per-category precision/recall/F1, treating (invoice_id, category) as the unit."""
    truth = {(r.invoice_id, c) for r in labels.itertuples() for c in r.categories}
    pred = {(r.invoice_id, r.category) for r in findings.itertuples()}
    known = set(labels["invoice_id"])
    pred = {(i, c) for i, c in pred if i in known}

    rows = []
    for cat in sorted({c for _, c in truth} | {c for _, c in pred}):
        t = {i for i, c in truth if c == cat}
        p_ = {i for i, c in pred if c == cat}
        tp, fp, fn = len(p_ & t), len(p_ - t), len(t - p_)
        pr, rc, f1 = _prf(tp, fp, fn)
        rows.append({"category": cat, "support": len(t), "predicted": len(p_),
                     "tp": tp, "fp": fp, "fn": fn,
                     "precision": round(pr, 3), "recall": round(rc, 3), "f1": round(f1, 3)})
    return pd.DataFrame(rows)


def report(findings, labels, title="tier 1 (structural checks only)"):
    """Print the detection and attribution tables for one run."""
    det = detection_scores(findings["invoice_id"].unique(), labels)
    print(f"=== {title} ===")
    print(f"detection : precision {det['precision']:.3f}  recall {det['recall']:.3f}  "
          f"f1 {det['f1']:.3f}   (tp {det['tp']}  fp {det['fp']}  fn {det['fn']} "
          f"of {det['n_truth']} erroneous)")
    print()
    print(category_scores(findings, labels).to_string(index=False))
    return det
