"""Ask a question about a contract, answered from retrieved clauses.

Interactive counterpart to the batch extraction. The model only ever sees clauses
retrieved from one hospital's contract, so an answer cannot be drawn from another
hospital's terms or from the model's own recollection, and every answer carries the
clauses it was based on.
"""

import glob
import os
import re
import textwrap

from src.config import PROMPTS
from src.retrieval import VectorIndex
from src.llm import parse_json

QA_PROMPT_VERSION = "qa_v1"


def answer_prompt():
    return open(PROMPTS / f"contract_{QA_PROMPT_VERSION}.txt").read()



def clause_index(data_root, hospital, encoder=None):
    """Split a hospital's contract into clauses and index them for retrieval."""
    clauses, meta = [], []
    for path in sorted(glob.glob(f"{data_root}/contracts/{hospital}/*.md")):
        document = os.path.basename(path)
        text = open(path).read()
        section = "preamble"
        for block in re.split(r"\n(?=#{2,3} |\d+\.\d+ |[A-Z]\d\.\d )", text):
            block = block.strip()
            if len(block) < 40:
                continue
            heading = block.splitlines()[0]
            if heading.startswith("#"):
                section = heading.lstrip("# ").strip()
            clauses.append(block[:1800])
            meta.append({"hospital": hospital, "document": document, "section": section})
    return VectorIndex(clauses, meta, encoder), clauses


def ask(question, index, model, hospital, k=4, show_context=True):
    """Retrieve the k most relevant clauses from one hospital, then answer from them."""
    hits = index.search(question, k=k, where={"hospital": hospital})
    if not hits:
        return "No clauses retrieved for that hospital."

    context = "\n\n".join(
        f"[{i + 1}] ({h['document']} · {h['section']})\n{h['text']}"
        for i, h in enumerate(hits))
    answer, usage = model.generate(answer_prompt(),
                                   f"CLAUSES:\n{context}\n\nQUESTION: {question}")

    if show_context:
        print(f"question  {question}")
        print(f"hospital  {hospital}   clauses retrieved: {len(hits)}")
        for i, h in enumerate(hits):
            print(f"   [{i + 1}] {h['score']:.3f}  {h['section'][:60]}")
        print()
    print(textwrap.fill(answer, 92, subsequent_indent="  "))
    print()
    print(f"[{usage['input_tokens']} in · {usage['output_tokens']} out · {usage['seconds']}s]")
    return answer
