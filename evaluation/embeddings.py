"""Label-free checks on the resolver: cluster descriptions by text alone and compare
with the price-based assignment. Two methods sharing no information agreeing is
evidence; it needs no labels, so it applies to the unlabelled hospitals too.
"""

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import (adjusted_rand_score, homogeneity_score,
                             silhouette_score, completeness_score)

from src.retrieval import embed, load_encoder  # noqa: F401  (re-exported for the notebook)


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
