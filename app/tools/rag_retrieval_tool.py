import logging
from typing import Any, Dict, Optional
from app.tools.base_tool import BaseTool, ToolResult
from app.rag.pipeline import RAGPipeline

logger = logging.getLogger(__name__)

# Singleton pipeline instance for tool efficiency
_pipeline_instance: Optional[RAGPipeline] = None


def get_shared_rag_pipeline() -> RAGPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = RAGPipeline()
    return _pipeline_instance


class RAGRetrievalTool(BaseTool):
    """Tool to query verified hospital records, cancer specialties, oncologists, and clinical guidelines."""

    name = "query_knowledge_base"
    description = (
        "Search the verified clinical knowledge base for hospitals, cancer specialties, "
        "oncologists, doctor profiles, locations, contacts, and appointment guidelines. "
        "Optionally filter by city or specialty."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Specific query (e.g. 'cancer hospitals in Bengaluru', 'oncologists in Mumbai', 'Tata Memorial doctors')"
            },
            "city": {
                "type": "string",
                "description": "Optional city filter (e.g. 'Bengaluru', 'Mumbai', 'Chennai', 'Delhi')"
            },
            "specialty": {
                "type": "string",
                "description": "Optional specialty filter (e.g. 'Oncology', 'Surgical Oncology', 'Radiation Oncology')"
            },
            "hospital_name": {
                "type": "string",
                "description": "Optional hospital name filter"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of verified records to retrieve (default 4)",
                "default": 4
            }
        },
        "required": ["query"]
    }

    def __init__(self, pipeline: Optional[RAGPipeline] = None):
        self.pipeline = pipeline or get_shared_rag_pipeline()

    def execute(self, query: str, city: Optional[str] = None,
                specialty: Optional[str] = None,
                hospital_name: Optional[str] = None,
                top_k: int = 4, **kwargs) -> ToolResult:
        try:
            items = self.pipeline.retrieve(
                query=query,
                top_k=top_k,
                city_filter=city,
                specialty_filter=specialty,
                hospital_filter=hospital_name
            )
            context = self.pipeline.get_grounded_context(
                query=query,
                top_k=top_k,
                city_filter=city,
                specialty_filter=specialty,
                hospital_filter=hospital_name
            )

            # Extract structured summary for agent convenience
            structured_records = []
            for item in items:
                m = item.get("metadata", {})
                structured_records.append({
                    "hospital": m.get("hospital_name"),
                    "doctor": m.get("doctor_name"),
                    "specialization": m.get("specialization"),
                    "city": m.get("city"),
                    "phone": m.get("phone"),
                    "source": f"{m.get('source_type')} ({m.get('source_url')})",
                    "source_url": m.get("source_url"),
                    "source_type": m.get("source_type"),
                    "verified_at": m.get("verified_at")
                })

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "retrieved_count": len(items),
                    "records": structured_records,
                    "formatted_context": context
                }
            )
        except Exception as exc:
            logger.error("RAGRetrievalTool error: %s", exc)
            return ToolResult(success=False, data=None, error=str(exc))
