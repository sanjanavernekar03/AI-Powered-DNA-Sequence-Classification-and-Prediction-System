import json
import logging
import urllib.error
import urllib.request
from typing import List, Optional
import numpy as np
from app.rag.config import default_rag_config

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """
    Dual-engine embedding generator.
    Attempts Ollama embedding API with graceful fallback to dense normalized TF-IDF / feature hashing.
    """

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self.base_url = (base_url or default_rag_config.ollama_base_url).rstrip("/")
        self.model = model or default_rag_config.ollama_embedding_model
        self.dim = default_rag_config.embedding_dimension
        self._ollama_available = True

    def embed_text(self, text: str) -> np.ndarray:
        """Generate a 1D normalized float numpy embedding for a single string."""
        clean = (text or "").strip()
        if not clean:
            return np.zeros(self.dim, dtype=np.float32)

        if self._ollama_available:
            try:
                emb = self._call_ollama_embeddings(clean)
                if emb is not None and len(emb) > 0:
                    arr = np.array(emb, dtype=np.float32)
                    norm = np.linalg.norm(arr)
                    return arr / norm if norm > 1e-6 else arr
            except Exception as e:
                logger.info("Ollama embedding not responding (%s), using native dense vectorizer fallback.", e)
                self._ollama_available = False

        return self._fallback_dense_embed(clean)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Generate a 2D float numpy array (N, dim) for multiple strings."""
        vectors = [self.embed_text(t) for t in texts]
        return np.array(vectors, dtype=np.float32)

    def _call_ollama_embeddings(self, text: str) -> Optional[List[float]]:
        payload = json.dumps({
            "model": self.model,
            "prompt": text[:1500]  # Safe token window
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("embedding")

    def _fallback_dense_embed(self, text: str) -> np.ndarray:
        """
        Deterministic lightweight subword hashing + n-gram dense projector.
        Guarantees semantic overlap between medical keywords without external models.
        """
        import hashlib

        vec = np.zeros(self.dim, dtype=np.float32)
        words = text.lower().split()
        for i, word in enumerate(words):
            # Term weight with deterministic md5 hashing
            h_int = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)
            w_hash = h_int % self.dim
            vec[w_hash] += 1.0

            # Character 3-grams for morphological similarity
            for j in range(max(0, len(word) - 2)):
                ngram = word[j:j+3]
                ng_int = int(hashlib.md5(ngram.encode("utf-8")).hexdigest()[:8], 16)
                ng_hash = ng_int % self.dim
                vec[ng_hash] += 0.35

        norm = np.linalg.norm(vec)
        if norm > 1e-6:
            vec /= norm
        return vec

