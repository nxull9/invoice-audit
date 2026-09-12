"""Turns text into vectors and searches them. The hospital filter is applied before
scoring, so a question about one contract is never answered from another.
"""

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

SENTENCE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def load_encoder(model_name=SENTENCE_MODEL):
    """Return (encode_fn, description).

    The encoder is stateful: it fits on first use and transforms thereafter, so every
    text encoded through it lands in one comparable space. Encoding subsets with
    independently fitted vectorisers is the classic way to get silently incomparable
    vectors, and the TF-IDF fallback would do exactly that otherwise.
    """
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        return (lambda texts: np.asarray(model.encode(list(texts), show_progress_bar=False)),
                f"sentence-transformers/{model_name.split('/')[-1]}")
    except Exception:
        state = {"vectoriser": None}

        def encode(texts):
            texts = list(texts)
            if state["vectoriser"] is None:
                state["vectoriser"] = TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(2, 4), lowercase=True).fit(texts)
            return state["vectoriser"].transform(texts).toarray()

        return encode, "tfidf-char-ngram (fallback)"


def embed(texts, encoder=None):
    """Unit-normalised embeddings, so dot product is cosine similarity."""
    encode, name = encoder if encoder else load_encoder()
    return normalize(encode(texts)), name



class VectorIndex:
    """Cosine-similarity index with metadata filtering.

    The filter is applied before scoring, not after. A query scoped to one hospital
    must never return another hospital's clause: similarity is a score, a hospital
    identifier is a fact, and facts are not negotiable by cosine distance.
    """

    def __init__(self, texts, metadata, encoder=None):
        self.texts = list(texts)
        self.metadata = list(metadata)
        # One encoder for the corpus and every later query. The TF-IDF fallback is
        # stateful (it fits on first use), so loading it twice yields two vocabularies
        # and a dimension mismatch on the first search.
        encoder = encoder or load_encoder()
        self.vectors, self.encoder_name = embed(self.texts, encoder)
        self._encode = encoder[0]

    def search(self, query, k=5, where=None):
        mask = np.ones(len(self.texts), dtype=bool)
        if where:
            for field, value in where.items():
                mask &= np.array([m.get(field) == value for m in self.metadata])
        if not mask.any():
            return []
        q = normalize(self._encode([query]))
        scores = (self.vectors @ q.T).ravel()
        scores[~mask] = -np.inf
        top = np.argsort(-scores)[:k]
        return [{"score": round(float(scores[i]), 4), "text": self.texts[i],
                 **self.metadata[i]} for i in top if np.isfinite(scores[i])]

    def recall_at_k(self, queries, relevant, k):
        """Fraction of relevant items retrieved in the top k, averaged over queries.

        The metric that matters when every relevant chunk must be found rather than
        the closest few.
        """
        hits = []
        for query, wanted in zip(queries, relevant):
            got = {r["text"] for r in self.search(query, k=k)}
            hits.append(len(got & set(wanted)) / max(1, len(wanted)))
        return round(float(np.mean(hits)), 4)
