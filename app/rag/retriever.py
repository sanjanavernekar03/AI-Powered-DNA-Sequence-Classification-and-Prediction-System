import logging
from typing import Any, Dict, List, Optional
from app.rag.config import default_rag_config
from app.rag.embeddings import EmbeddingEngine
from app.rag.vector_store import VectorStore
from app.rag.document_processor import DocumentChunk
from app.rag.context_builder import ContextBuilder

logger = logging.getLogger(__name__)


class RAGRetriever:
    """
    Retrieval engine linking query embedding generation, cosine similarity ranking,
    and metadata-aware filtering (e.g., city, hospital_name, specialization).
    """

    def __init__(self, vector_store: VectorStore, embedding_engine: EmbeddingEngine,
                 top_k: int = default_rag_config.top_k,
                 min_score: float = default_rag_config.min_similarity_score):
        self.vector_store = vector_store
        self.embedding_engine = embedding_engine
        self.top_k = top_k
        self.min_score = min_score
        self.context_builder = ContextBuilder()

    def retrieve(self, query: str, top_k: Optional[int] = None,
                 min_score: Optional[float] = None,
                 city_filter: Optional[str] = None,
                 specialty_filter: Optional[str] = None,
                 hospital_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve top ranked document chunks matching the query string,
        with optional metadata filters for city, specialty, and hospital.
        """
        k = top_k if top_k is not None else self.top_k
        score_thresh = min_score if min_score is not None else self.min_score

        if not query or not query.strip():
            return []

        # Vector cosine similarity search
        query_vec = self.embedding_engine.embed_text(query)
        # Search a larger pool first if filters are active
        search_pool_k = k * 3 if (city_filter or specialty_filter or hospital_filter) else k
        scored_chunks = self.vector_store.similarity_search(query_vec, top_k=search_pool_k, min_score=score_thresh)

        results = []
        for chunk, score in scored_chunks:
            meta = chunk.metadata or {}

            # Apply city filter if provided
            if city_filter and city_filter.strip():
                c_clean = city_filter.strip().lower()
                chunk_city = str(meta.get("city", "")).lower()
                if c_clean not in chunk_city and c_clean not in chunk.content.lower():
                    continue

            # Apply specialty filter if provided
            if specialty_filter and specialty_filter.strip():
                s_clean = specialty_filter.strip().lower()
                chunk_spec = str(meta.get("specialization", "")).lower()
                if s_clean not in chunk_spec and s_clean not in chunk.content.lower():
                    continue

            # Apply hospital filter if provided
            if hospital_filter and hospital_filter.strip():
                h_clean = hospital_filter.strip().lower()
                chunk_hosp = str(meta.get("hospital_name", "")).lower()
                if h_clean not in chunk_hosp and h_clean not in chunk.content.lower():
                    continue

            results.append({
                "content": chunk.content,
                "source": chunk.source_file,
                "chunk_id": chunk.chunk_id,
                "score": round(score, 4),
                "metadata": meta
            })

            if len(results) >= k:
                break

        # Fallback keyword match if vector score was below threshold for specific city/name
        if not results and (city_filter or specialty_filter or hospital_filter or query):
            results = self._fallback_keyword_search(query, k, city_filter, specialty_filter, hospital_filter)

        return results

    def _fallback_keyword_search(self, query: str, top_k: int,
                                 city_filter: Optional[str] = None,
                                 specialty_filter: Optional[str] = None,
                                 hospital_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Exact keyword fallback to guarantee recall on specific named entities."""
        terms = [t.lower() for t in query.split() if len(t) > 3]
        matches = []
        for chunk in self.vector_store.chunks:
            meta = chunk.metadata or {}
            c_text = chunk.content.lower()

            # Metadata matching
            score = 0.0
            if city_filter and city_filter.lower() in str(meta.get("city", "")).lower():
                score += 0.4
            if specialty_filter and specialty_filter.lower() in str(meta.get("specialization", "")).lower():
                score += 0.4
            if hospital_filter and hospital_filter.lower() in str(meta.get("hospital_name", "")).lower():
                score += 0.5

            # Term overlap
            for term in terms:
                if term in c_text:
                    score += 0.2

            if score > 0.0:
                matches.append((chunk, score))

        matches.sort(key=lambda x: x[1], reverse=True)
        results = []
        for chunk, score in matches[:top_k]:
            results.append({
                "content": chunk.content,
                "source": chunk.source_file,
                "chunk_id": chunk.chunk_id,
                "score": round(score, 4),
                "metadata": chunk.metadata
            })
        return results

    def format_context(self, retrieved_items: List[Dict[str, Any]], query: str = "") -> str:
        """Format retrieved items into a compact context block for LLM prompts."""
        return self.context_builder.build_context(retrieved_items, query=query)
