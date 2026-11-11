from typing import Any, Dict, List, Optional


MEDICAL_DISCLAIMER_NOTICE = (
    "NOTICE: Verified information retrieved for hospital navigation and specialist referral. "
    "This system does not provide medical diagnoses or prescribe treatments."
)


class ContextBuilder:
    """
    Dedicated component for constructing grounded, source-attributed prompt context
    from retrieved RAG knowledge records.
    """

    @staticmethod
    def build_context(retrieved_items: List[Dict[str, Any]], query: str = "") -> str:
        """
        Assemble a structured context block with strict attribution and clinical disclaimers.
        """
        if not retrieved_items:
            return (
                "No verified records were found in the knowledge base matching your search criteria. "
                "The agent must inform the user honestly that no verified record is available "
                "and recommend consulting verified hospital directories."
            )

        header = [
            "### VERIFIED HEALTHCARE & HOSPITAL REFERENCE CONTEXT",
            f"User Query Target: {query}" if query else "",
            f"Disclaimer: {MEDICAL_DISCLAIMER_NOTICE}",
            "Instructions for Agent: Answer using ONLY the verified facts below. DO NOT invent or assume any hospital, doctor, or contact details not present in this text.",
            "=" * 60,
            ""
        ]

        sections = []
        for i, item in enumerate(retrieved_items, 1):
            meta = item.get("metadata", {})
            hosp_name = meta.get("hospital_name", "Verified Healthcare Facility")
            hosp_id = meta.get("hospital_id", "N/A")
            doc_name = meta.get("doctor_name", "Consultant Doctor")
            doc_id = meta.get("doctor_id", "N/A")
            spec = meta.get("specialization", "Specialist")
            city = meta.get("city", "")
            state = meta.get("state", "")
            location_str = f"{city}, {state}".strip(", ") if (city or state) else "India"
            source_url = meta.get("source_url", "https://mohfw.gov.in")
            source_type = meta.get("source_type", "Verified Registry")
            verified_at = meta.get("verified_at", "Verified")
            score = item.get("score", 0.0)

            record_block = (
                f"--- RECORD {i} (Relevance Score: {score:.2f}) ---\n"
                f"Hospital Name: {hosp_name} [ID: {hosp_id}]\n"
                f"Location: {location_str}\n"
                f"Doctor: {doc_name} [ID: {doc_id}]\n"
                f"Specialization: {spec}\n"
                f"Source: {source_type} ({source_url})\n"
                f"Verification Timestamp: {verified_at}\n"
                f"\nContent Details:\n{item.get('content', '').strip()}\n"
            )
            sections.append(record_block)

        return "\n".join(header) + "\n".join(sections)

    @staticmethod
    def format_records_for_agent(retrieved_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Return structured dictionary records suitable for programmatic agent actions.
        """
        structured = []
        for item in retrieved_items:
            meta = item.get("metadata", {})
            structured.append({
                "hospital_name": meta.get("hospital_name"),
                "hospital_id": meta.get("hospital_id"),
                "doctor_name": meta.get("doctor_name"),
                "doctor_id": meta.get("doctor_id"),
                "specialization": meta.get("specialization"),
                "city": meta.get("city"),
                "state": meta.get("state"),
                "phone": meta.get("phone"),
                "source_url": meta.get("source_url"),
                "source_type": meta.get("source_type"),
                "verified_at": meta.get("verified_at"),
                "score": item.get("score"),
                "snippet": item.get("content")
            })
        return structured
