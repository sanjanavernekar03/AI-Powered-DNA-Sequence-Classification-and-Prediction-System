import os
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.rag.config import default_rag_config

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """Represents a chunk of text with traceable metadata."""
    chunk_id: str
    content: str
    source_file: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class DocumentProcessor:
    """
    Ingests, cleans, extracts text, and chunks documents (TXT, MD, CSV, JSON, PDF).
    """

    def __init__(self, chunk_size: int = default_rag_config.chunk_size,
                 chunk_overlap: int = default_rag_config.chunk_overlap):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def process_file(self, file_path: Path | str) -> List[DocumentChunk]:
        """Process a single file and return structured document chunks."""
        path = Path(file_path)
        if not path.exists():
            logger.warning("File does not exist: %s", path)
            return []

        suffix = path.suffix.lower()
        text = ""

        try:
            if suffix in [".txt", ".md", ".csv", ".json"]:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            elif suffix == ".pdf":
                text = self._extract_pdf_text(path)
            else:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
        except Exception as e:
            logger.error("Failed to read file %s: %s", path, e)
            return []

        return self.chunk_text(text, source_file=path.name, extra_metadata={"file_path": str(path)})

    def chunk_text(self, text: str, source_file: str = "memory",
                   extra_metadata: Optional[Dict[str, Any]] = None) -> List[DocumentChunk]:
        """Split text into overlapping chunks respecting sentence and paragraph boundaries."""
        clean_text = self._clean_text(text)
        if not clean_text:
            return []

        # Split on double newlines / paragraph boundaries first
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean_text) if p.strip()]

        chunks: List[DocumentChunk] = []
        current_chunk: List[str] = []
        current_len = 0
        chunk_idx = 0

        for para in paragraphs:
            para_len = len(para)

            # If paragraph itself is excessively large, split by sentences
            if para_len > self.chunk_size:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sentence in sentences:
                    if current_len + len(sentence) > self.chunk_size and current_chunk:
                        chunk_content = " ".join(current_chunk)
                        chunks.append(DocumentChunk(
                            chunk_id=f"{source_file}#{chunk_idx}",
                            content=chunk_content,
                            source_file=source_file,
                            metadata=extra_metadata or {}
                        ))
                        chunk_idx += 1
                        # Maintain overlap
                        overlap_words = " ".join(current_chunk).split()[-self.chunk_overlap:]
                        current_chunk = [" ".join(overlap_words)] if overlap_words else []
                        current_len = sum(len(c) for c in current_chunk)

                    current_chunk.append(sentence)
                    current_len += len(sentence)
            else:
                if current_len + para_len > self.chunk_size and current_chunk:
                    chunk_content = " ".join(current_chunk)
                    chunks.append(DocumentChunk(
                        chunk_id=f"{source_file}#{chunk_idx}",
                        content=chunk_content,
                        source_file=source_file,
                        metadata=extra_metadata or {}
                    ))
                    chunk_idx += 1
                    overlap_words = " ".join(current_chunk).split()[-self.chunk_overlap:]
                    current_chunk = [" ".join(overlap_words)] if overlap_words else []
                    current_len = sum(len(c) for c in current_chunk)

                current_chunk.append(para)
                current_len += para_len

        if current_chunk:
            chunk_content = " ".join(current_chunk).strip()
            if chunk_content:
                chunks.append(DocumentChunk(
                    chunk_id=f"{source_file}#{chunk_idx}",
                    content=chunk_content,
                    source_file=source_file,
                    metadata=extra_metadata or {}
                ))

        return chunks

    def _extract_pdf_text(self, pdf_path: Path) -> str:
        """Extract text from PDF using PyMuPDF (fitz), pypdf/pypdf2 or binary stream regex fallback."""
        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            pages = []
            for page in doc:
                text = page.get_text() or ""
                if text.strip():
                    pages.append(text)
            doc.close()
            if pages:
                return "\n\n".join(pages)
        except Exception as e:
            logger.debug("fitz extraction failed or skipped: %s", e)

        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except ImportError:
            pass

        try:
            import pypdf2
            reader = pypdf2.PdfFileReader(str(pdf_path))
            pages = [reader.getPage(i).extractText() or "" for i in range(reader.numPages)]
            return "\n\n".join(pages)
        except Exception:
            pass

        # Fallback pure-python basic stream text stripper
        try:
            with open(pdf_path, "rb") as f:
                content = f.read().decode("latin-1", errors="ignore")
                matches = re.findall(r"\((.*?)\)T[jJ]", content)
                return " ".join(matches)
        except Exception as e:
            logger.warning("Could not extract PDF text from %s: %s", pdf_path, e)
            return ""

    def _clean_text(self, text: str) -> str:
        """Standardize whitespace and remove non-printable characters."""
        if not text:
            return ""
        t = re.sub(r"\r\n", "\n", text)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()
