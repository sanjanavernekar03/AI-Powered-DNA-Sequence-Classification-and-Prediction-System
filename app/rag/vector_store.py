import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from app.rag.config import default_rag_config
from app.rag.document_processor import DocumentChunk

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Lightweight, high-performance in-memory and persistent vector index.
    Uses pure NumPy for matrix multiplication and cosine similarity scoring.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or default_rag_config.index_storage_path
        self.chunks: List[DocumentChunk] = []
        self.vectors: Optional[np.ndarray] = None  # Shape (N, dim)

    def add_chunks(self, chunks: List[DocumentChunk], embeddings: np.ndarray):
        """Add new document chunks and corresponding vectors to index."""
        if not chunks or embeddings is None or len(chunks) == 0:
            return

        self.chunks.extend(chunks)
        if self.vectors is None or len(self.vectors) == 0:
            self.vectors = np.array(embeddings, dtype=np.float32)
        else:
            self.vectors = np.vstack([self.vectors, embeddings])

        logger.info("VectorStore now contains %d chunks.", len(self.chunks))

    def similarity_search(self, query_vector: np.ndarray, top_k: int = 4,
                          min_score: float = 0.0) -> List[Tuple[DocumentChunk, float]]:
        """
        Perform fast cosine similarity matrix multiplication between query_vector (dim,)
        and indexed vectors (N, dim).
        """
        if self.vectors is None or len(self.vectors) == 0 or len(self.chunks) == 0:
            return []

        # Ensure query vector is 1D normalized
        q = np.array(query_vector, dtype=np.float32).flatten()
        q_norm = np.linalg.norm(q)
        if q_norm > 1e-6:
            q = q / q_norm

        # Matrix dot product gives cosine similarities since vectors are unit-norm
        scores = np.dot(self.vectors, q)

        # Top K indices
        ranked_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in ranked_indices:
            score = float(scores[idx])
            if score >= min_score:
                results.append((self.chunks[idx], score))

        return results

    def save(self, file_path: Optional[Path] = None):
        """Persist index chunks and vectors to JSON disk storage."""
        target = file_path or self.storage_path
        target.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "source_file": c.source_file,
                    "metadata": c.metadata
                }
                for c in self.chunks
            ],
            "vectors": self.vectors.tolist() if self.vectors is not None else []
        }

        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            logger.info("Saved VectorStore index to %s", target)
        except Exception as e:
            logger.error("Failed to save VectorStore to %s: %s", target, e)

    def load(self, file_path: Optional[Path] = None) -> bool:
        """Load index from JSON disk storage."""
        target = file_path or self.storage_path
        if not target.exists():
            return False

        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_chunks = data.get("chunks", [])
            raw_vectors = data.get("vectors", [])

            self.chunks = [
                DocumentChunk(
                    chunk_id=c["chunk_id"],
                    content=c["content"],
                    source_file=c["source_file"],
                    metadata=c.get("metadata", {})
                )
                for c in raw_chunks
            ]

            if raw_vectors:
                self.vectors = np.array(raw_vectors, dtype=np.float32)
            else:
                self.vectors = None

            logger.info("Loaded VectorStore with %d items from %s", len(self.chunks), target)
            return True
        except Exception as e:
            logger.error("Failed to load VectorStore from %s: %s", target, e)
            return False
