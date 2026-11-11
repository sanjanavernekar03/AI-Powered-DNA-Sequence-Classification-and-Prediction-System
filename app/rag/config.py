import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RAGConfig:
    """Configuration settings for the RAG Knowledge Engine."""
    # Chunking settings
    chunk_size: int = 400
    chunk_overlap: int = 80

    # Retrieval settings
    top_k: int = 4
    min_similarity_score: float = 0.25

    # Storage paths
    data_dir: Path = Path(__file__).resolve().parent.parent.parent / "dataset" / "hospital_knowledge"
    index_storage_path: Path = Path(__file__).resolve().parent.parent.parent / "dataset" / "hospital_knowledge" / "vector_index.json"

    # Ollama settings
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_embedding_model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "llama3.2")
    embedding_dimension: int = 128  # Fallback dense projection dimension


default_rag_config = RAGConfig()
default_rag_config.data_dir.mkdir(parents=True, exist_ok=True)
