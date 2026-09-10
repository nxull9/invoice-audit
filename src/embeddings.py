"""Embedding, projection and clustering of billing descriptions and contract text.

Two uses. First, an independent check on the price-anchored resolver: if a sentence
embedding model clusters descriptions the same way the resolver assigns them, two
methods sharing no information agree, and the agreement is measurable without labels.
Second, a vector index over contract chunks, so retrieval can be compared against the
structural filter rather than assumed to be better.

Falls back to character n-gram TF-IDF where sentence-transformers is unavailable, so
the notebook runs without a GPU or a model download.
"""

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (adjusted_rand_score, homogeneity_score,
                             silhouette_score, completeness_score)
from sklearn.preprocessing import normalize

SENTENCE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def load_encoder(model_name=SENTENCE_MODEL):
    """Return (encode_fn, description). Falls back to TF-IDF if unavailable."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        return (lambda texts: np.asarray(model.encode(list(texts), show_progress_bar=False)),
                f"sentence-transformers/{model_name.split('/')[-1]}")
    except Exception:
        def encode(texts):
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True)
            return vec.fit_transform(list(texts)).toarray()
        return encode, "tfidf-char-ngram (fallback)"


def embed(texts, encoder=None):
    """Unit-normalised embeddings, so dot product is cosine similarity."""
    encode, name = encoder if encoder else load_encoder()
    return normalize(encode(texts)), name


def project(vectors, n_components=2, random_state=0):
    """PCA projection, with the variance each component explains."""
    pca = PCA(n_components=n_components, random_state=random_state)
    coords = pca.fit_transform(vectors)
    return coords, pca.explained_variance_ratio_


def cluster(vectors, n_clusters, random_state=0):
    return KMeans(n_clusters=n_clusters, n_init=10,
                  random_state=random_state).fit_predict(vectors)


def agreement(cluster_labels, assigned_services):
    """How far unsupervised clustering agrees with the resolver's assignment.

    The resolver uses price and never sees the text; the encoder uses text and never
    sees a price. Agreement is therefore evidence, not circular.
    """
    truth = [str(s) for s in assigned_services]
    return {
        "adjusted_rand": round(float(adjusted_rand_score(truth, cluster_labels)), 4),
        "homogeneity": round(float(homogeneity_score(truth, cluster_labels)), 4),
        "completeness": round(float(completeness_score(truth, cluster_labels)), 4),
        "n_clusters": int(len(set(cluster_labels))),
        "n_services": int(len(set(truth))),
    }


def separation(vectors, labels):
    """Silhouette score of a labelling. -1 to 1; higher means better separated."""
    if len(set(labels)) < 2:
        return None
    return round(float(silhouette_score(vectors, labels, metric="cosine")), 4)


class VectorIndex:
    """Cosine-similarity index with metadata filtering.

    The filter is applied before scoring, not after. A query scoped to one hospital
    must never return another hospital's clause: similarity is a score, a hospital
    identifier is a fact, and facts are not negotiable by cosine distance.
    """

    def __init__(self, texts, metadata, encoder=None):
        self.texts = list(texts)
        self.metadata = list(metadata)
        self.vectors, self.encoder_name = embed(self.texts, encoder)
        self._encode = (encoder or load_encoder())[0]

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
