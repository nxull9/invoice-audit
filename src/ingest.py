"""Getting contract text out of whatever a provider actually sends.

This exercise ships Markdown and plain text, but a provider signing on sends a PDF.
Three routes, tried in order of how much they can be trusted:

    1. Markdown or plain text        exact
    2. PDF with an embedded text layer   exact
    3. PDF with no text layer            OCR, and marked as such

The ordering matters more than it looks. OCR misreads digits -- 5/S, 0/O, 1/l -- and a
contract is almost entirely digits. A rate silently read as 25260 instead of 25250
misprices every invoice touching that service and nothing downstream can detect it,
because the wrong number is perfectly well-formed. So OCR is a last resort, every
extraction reports which route produced it, and an OCR-derived contract carries reduced
confidence on every rate it yields.
"""

import glob
import os
import re

TEXT_LAYER_MIN_CHARS = 500
DEMO_DIR = "reports/ocr_demo"   # never inside runs/, which holds recordings      # below this a PDF page is treated as an image
DIGIT_CONFUSIONS = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5"})


def _read_pdf_text(path):
    """Extract an embedded text layer, or return None if the PDF has none."""
    try:
        import pypdf
    except ImportError:
        return None, "pypdf not installed"
    try:
        reader = pypdf.PdfReader(path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if len(text.strip()) < TEXT_LAYER_MIN_CHARS:
        return None, f"text layer too thin ({len(text.strip())} chars)"
    return text, None


def _ocr_pdf(path, dpi=300):
    """Rasterise and OCR. Used only where a PDF carries no text layer."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as exc:
        return None, (f"OCR unavailable ({exc.name} missing). Install pytesseract, "
                      f"pdf2image, and the tesseract binary.")
    try:
        pages = convert_from_path(path, dpi=dpi)
        text = "\n".join(pytesseract.image_to_string(p) for p in pages)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return text, None


def repair_ocr_numbers(text):
    """Fix letter-for-digit confusions inside monetary amounts only.

    Applied nowhere else: 'GBP 2S2.SO' is unambiguous, but rewriting letters to digits
    in ordinary prose would corrupt service names.
    """
    def fix(match):
        return "GBP " + match.group(1).translate(DIGIT_CONFUSIONS)
    return re.sub(r"GBP\s+([0-9OolIS,\.]+)", fix, text)


def read_contract_file(path):
    """Return (text, provenance). Provenance records the route and its reliability."""
    extension = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)

    if extension in (".md", ".txt"):
        return open(path, encoding="utf-8").read(), {
            "file": name, "route": "text", "exact": True, "note": None}

    if extension == ".pdf":
        text, why = _read_pdf_text(path)
        if text is not None:
            return text, {"file": name, "route": "pdf_text_layer", "exact": True,
                          "note": None}
        ocr, ocr_why = _ocr_pdf(path)
        if ocr is not None:
            return repair_ocr_numbers(ocr), {
                "file": name, "route": "ocr", "exact": False,
                "note": f"no text layer ({why}); OCR used -- rates are not exact"}
        return "", {"file": name, "route": "failed", "exact": False,
                    "note": f"{why}; {ocr_why}"}

    return "", {"file": name, "route": "unsupported", "exact": False,
                "note": f"cannot read {extension}"}


def ingest_contract(folder, prefer_text=True):
    """Read every contract document in a folder.

    `prefer_text` skips a PDF where a .md or .txt of the same stem exists, since the
    text form is exact and the PDF is at best equal to it.
    """
    paths = sorted(glob.glob(os.path.join(folder, "*")))
    stems = {os.path.splitext(os.path.basename(p))[0]
             for p in paths if p.lower().endswith((".md", ".txt"))}

    documents, provenance = [], []
    for path in paths:
        stem = os.path.splitext(os.path.basename(path))[0]
        if prefer_text and path.lower().endswith(".pdf") and stem in stems:
            provenance.append({"file": os.path.basename(path), "route": "skipped",
                               "exact": True, "note": "text form of the same document available"})
            continue
        if path.lower().endswith(".pdf") and any(
                s.startswith(stem.rsplit("_", 1)[0]) for s in stems) and prefer_text:
            provenance.append({"file": os.path.basename(path), "route": "skipped",
                               "exact": True, "note": "text form available"})
            continue
        text, meta = read_contract_file(path)
        if text:
            documents.append(text)
        provenance.append(meta)

    combined = "\n\n".join(documents)
    return combined, provenance


def ingestion_confidence(provenance):
    """A multiplier applied to every rate extracted from these documents."""
    if any(p["route"] == "ocr" for p in provenance):
        return 0.70
    if any(p["route"] == "failed" for p in provenance):
        return 0.50
    return 1.00
