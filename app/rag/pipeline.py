import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.rag.config import RAGConfig, default_rag_config
from app.rag.document_processor import DocumentProcessor
from app.rag.embeddings import EmbeddingEngine
from app.rag.vector_store import VectorStore
from app.rag.retriever import RAGRetriever
from app.rag.ingestion import DocumentIngestionEngine
from app.rag.context_builder import ContextBuilder

logger = logging.getLogger(__name__)


class RAGPipeline:
    """
    Unified end-to-end RAG orchestrator for verified hospital and doctor records.
    Provides document ingestion, vector storage, semantic retrieval, and context construction.
    """

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or default_rag_config
        self.doc_processor = DocumentProcessor(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap
        )
        self.embedding_engine = EmbeddingEngine(
            base_url=self.config.ollama_base_url,
            model=self.config.ollama_embedding_model
        )
        self.vector_store = VectorStore(storage_path=self.config.index_storage_path)
        self.ingestion_engine = DocumentIngestionEngine(
            vector_store=self.vector_store,
            embedding_engine=self.embedding_engine,
            doc_processor=self.doc_processor
        )
        self.context_builder = ContextBuilder()
        self.retriever = RAGRetriever(
            vector_store=self.vector_store,
            embedding_engine=self.embedding_engine,
            top_k=self.config.top_k,
            min_score=self.config.min_similarity_score
        )

        self._initialize_pipeline()

    def _initialize_pipeline(self):
        """Load existing vector index or bootstrap from verified dataset files."""
        loaded = self.vector_store.load()
        has_hospitals = any(c.metadata.get("hospital_name") for c in self.vector_store.chunks)
        if not loaded or not has_hospitals:
            logger.info("Initializing vector index from verified hospital records...")
            self.bootstrap_knowledge_base()

    def bootstrap_knowledge_base(self) -> int:
        """
        Ingest the bundled verified dataset of cancer hospitals, oncologists, and facilities.
        """
        json_file = self.config.data_dir / "verified_cancer_hospitals.json"
        total = 0
        if json_file.exists():
            # Reset chunks to avoid duplicate bootstrap entries
            self.vector_store.chunks = []
            self.vector_store.vectors = None
            total = self.ingestion_engine.ingest_hospital_json(json_file)
            self.save_index()
            logger.info("Bootstrapped %d records into RAG knowledge base.", total)
        else:
            logger.warning("Verified dataset file not found at %s", json_file)
        return total

    def ingest_file(self, file_path: Path | str) -> int:
        """Ingest an external hospital document, JSON, or clinical PDF."""
        path = Path(file_path)
        if path.suffix.lower() == ".json":
            cnt = self.ingestion_engine.ingest_hospital_json(path)
        else:
            cnt = self.ingestion_engine.ingest_clinical_document(path)
        if cnt > 0:
            self.save_index()
        return cnt

    def retrieve(self, query: str, top_k: Optional[int] = None,
                 city_filter: Optional[str] = None,
                 specialty_filter: Optional[str] = None,
                 hospital_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve verified records for a user query."""
        return self.retriever.retrieve(
            query=query,
            top_k=top_k,
            city_filter=city_filter,
            specialty_filter=specialty_filter,
            hospital_filter=hospital_filter
        )

    def get_grounded_context(self, query: str, top_k: Optional[int] = None,
                             city_filter: Optional[str] = None,
                             specialty_filter: Optional[str] = None,
                             hospital_filter: Optional[str] = None) -> str:
        """
        Retrieve records and construct an attributed context block ready for the Agent.
        """
        records = self.retrieve(
            query=query,
            top_k=top_k,
            city_filter=city_filter,
            specialty_filter=specialty_filter,
            hospital_filter=hospital_filter
        )
        return self.context_builder.build_context(records, query=query)

    def save_index(self):
        """Persist vector store index to disk."""
        self.vector_store.save()
