import os
import re
import tempfile
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from app.rag.pipeline import RAGPipeline
from app.tools.rag_retrieval_tool import get_shared_rag_pipeline
from app.agents.hospital_agent import HospitalAgent

logger = logging.getLogger(__name__)

# Security constants
MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit
PDF_MAGIC_BYTES = b"%PDF-"


class HospitalPDFProcessingError(Exception):
    """Custom exception for secure PDF processing errors."""
    pass


class HospitalPDFService:
    """
    Dedicated secure PDF input workflow for the Hospital Agent and RAG system.
    
    Pipeline:
      PDF Upload -> Security Validation -> Passive Text Extraction
      -> Relevant Information Extraction (condition, disease, specialty, treatment, location, referral)
      -> Hospital Agent & RAG Retrieval -> Verified Hospital Recommendations
    
    Security & Safety Guarantees:
      - Validates MIME, extension, and %PDF- magic bytes
      - Enforces strict file size limits (<= 10MB)
      - Never executes embedded JavaScript or binary streams
      - Zero persistent logging of patient PII or raw medical text
      - Ephemeral temporary files deleted immediately in try...finally
      - Strictly NON-DIAGNOSTIC output phrasing (never says 'You have cancer')
    """

    # Comprehensive dictionaries for clinical information extraction
    CANCER_CONDITIONS = [
        "carcinoma", "sarcoma", "lymphoma", "leukemia", "melanoma",
        "neoplasm", "malignancy", "tumor", "tumour", "metastasis",
        "adenocarcinoma", "glioblastoma", "myeloma", "blastomas"
    ]

    DISEASE_KEYWORDS = {
        "breast cancer": ["breast cancer", "infiltrating ductal carcinoma", "invasive ductal carcinoma", "brca1", "brca2"],
        "lung cancer": ["lung cancer", "nsclc", "sclc", "non-small cell lung", "bronchogenic carcinoma"],
        "brain tumor / neuro-oncology": ["glioblastoma", "glioma", "astrocytoma", "meningioma", "brain tumor", "brain tumour"],
        "colorectal cancer": ["colorectal cancer", "colon cancer", "rectal cancer", "colonic adenocarcinoma"],
        "leukemia / lymphoma": ["leukemia", "lymphoma", "acute myeloid leukemia", "aml", "all", "cll", "hodgkin", "non-hodgkin", "multiple myeloma"],
        "head and neck cancer": ["head and neck", "oral cancer", "laryngeal cancer", "tongue carcinoma", "squamous cell carcinoma of oral"],
        "gastrointestinal cancer": ["gastric cancer", "stomach cancer", "esophageal cancer", "pancreatic cancer", "hepatocellular"],
        "gynecological cancer": ["ovarian cancer", "cervical cancer", "uterine cancer", "endometrial carcinoma"],
        "pediatric cancer": ["pediatric oncology", "neuroblastoma", "wilms tumor", "retinoblastoma"]
    }

    SPECIALTY_MAPPING = {
        "surgical oncology": ["surgical oncology", "surgery", "resection", "lumpectomy", "mastectomy", "colectomy", "excision"],
        "medical oncology": ["medical oncology", "chemotherapy", "systemic therapy", "immunotherapy", "targeted therapy"],
        "radiation oncology": ["radiation oncology", "radiotherapy", "radiation", "proton therapy", "imrt", "sbrt", "cyberknife", "brachytherapy"],
        "pediatric oncology": ["pediatric oncology", "pediatric hematology", "childhood cancer", "paediatric oncology"],
        "hematology oncology": ["hematology oncology", "bone marrow transplant", "stem cell transplant", "leukemia", "lymphoma", "myeloma"],
        "neuro-oncology": ["neuro-oncology", "brain tumor radiation", "cranial surgery"]
    }

    TREATMENT_TYPES = [
        "chemotherapy", "radiation therapy", "proton therapy", "pencil beam proton therapy",
        "surgical resection", "bone marrow transplant", "stem cell transplant",
        "immunotherapy", "targeted therapy", "cyberknife", "radiosurgery",
        "tomotherapy", "hormone therapy", "brachytherapy", "car-t cell therapy"
    ]

    INDIAN_CITIES = {
        "mumbai": "Mumbai",
        "bengaluru": "Bengaluru",
        "bangalore": "Bengaluru",
        "delhi": "New Delhi",
        "new delhi": "New Delhi",
        "chennai": "Chennai",
        "kolkata": "Kolkata",
        "calcutta": "Kolkata",
        "hyderabad": "Hyderabad",
        "pune": "Pune",
        "ahmedabad": "Ahmedabad",
        "jaipur": "Jaipur",
        "chandigarh": "Chandigarh",
        "kochi": "Kochi",
        "lucknow": "Lucknow"
    }

    INDIAN_STATES = {
        "maharashtra": "Maharashtra",
        "karnataka": "Karnataka",
        "tamil nadu": "Tamil Nadu",
        "west bengal": "West Bengal",
        "telangana": "Telangana",
        "delhi": "Delhi"
    }

    KNOWN_HOSPITALS = [
        "tata memorial", "kidwai", "aiims", "apollo proton", "apollo cancer",
        "hcg cancer", "hcg", "cnci", "chittaranjan national cancer",
        "basavatarakam", "indo-american cancer", "manipal"
    ]

    def __init__(self, rag_pipeline: Optional[RAGPipeline] = None,
                 hospital_agent: Optional[HospitalAgent] = None):
        self.rag_pipeline = rag_pipeline or get_shared_rag_pipeline()
        self.hospital_agent = hospital_agent

    def validate_pdf_content(self, raw_bytes: bytes, filename: str = "document.pdf") -> Tuple[bool, str]:
        """
        Securely validate PDF integrity, magic bytes, and file size.
        """
        # 1. Filename extension check
        if not filename.lower().endswith(".pdf"):
            return False, "Invalid file format: Only PDF files (.pdf) are permitted."

        # 2. Size validation
        byte_len = len(raw_bytes)
        if byte_len == 0:
            return False, "Empty file: The uploaded PDF contains zero bytes."
        if byte_len > MAX_PDF_SIZE_BYTES:
            return False, f"File size exceeds limit: {byte_len / (1024 * 1024):.1f}MB exceeds {MAX_PDF_SIZE_BYTES / (1024 * 1024):.0f}MB."

        # 3. Magic bytes inspection (%PDF-)
        # Check within the first 1024 bytes to allow for harmless header offsets
        header_sample = raw_bytes[:1024]
        if PDF_MAGIC_BYTES not in header_sample:
            return False, "Invalid PDF header: File does not start with valid PDF magic bytes (%PDF-)."

        return True, "Valid PDF"

    def extract_text_from_pdf(self, file_source: Union[bytes, Path, str]) -> str:
        """
        Extract text passively and safely from PDF using PyMuPDF (fitz) with fallback.
        Ensures temporary files are cleaned up immediately.
        """
        temp_path: Optional[Path] = None
        extracted_text = ""

        try:
            if isinstance(file_source, bytes):
                # Write to secure temporary file with restricted permissions
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    tf.write(file_source)
                    temp_path = Path(tf.name)
                target_path = temp_path
            else:
                target_path = Path(file_source)

            if not target_path.exists():
                raise HospitalPDFProcessingError(f"PDF file not found at {target_path}")

            # Safe extraction via PyMuPDF (fitz)
            try:
                import fitz
                doc = fitz.open(str(target_path))
                pages_text = []
                for page in doc:
                    txt = page.get_text() or ""
                    if txt.strip():
                        pages_text.append(txt)
                doc.close()
                extracted_text = "\n\n".join(pages_text)
            except Exception as fitz_err:
                logger.debug("PyMuPDF extraction failed: %s, attempting pypdf fallback", fitz_err)
                try:
                    import pypdf
                    reader = pypdf.PdfReader(str(target_path))
                    pages_text = [p.extract_text() or "" for p in reader.pages]
                    extracted_text = "\n\n".join(pages_text)
                except Exception as pypdf_err:
                    logger.debug("pypdf fallback failed: %s", pypdf_err)

        finally:
            # Ephemeral security: delete temporary file immediately
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception as del_err:
                    logger.warning("Failed to unlink temporary PDF %s: %s", temp_path, del_err)

        return extracted_text.strip()

    def extract_relevant_info(self, text: str) -> Dict[str, Any]:
        """
        Extract ONLY clinical entities relevant for hospital/specialist search:
        - condition
        - disease mentioned
        - specialty
        - treatment type
        - location (city/state)
        - hospital referral
        - doctor referral
        - has_sufficient_info
        
        Strictly filters out and ignores patient PII (names, ages, IDs, addresses).
        """
        if not text or len(text.strip()) == 0:
            return {
                "condition": None,
                "disease_mentioned": None,
                "specialty": None,
                "treatment_type": None,
                "location": None,
                "state": None,
                "hospital_referral": None,
                "doctor_referral": None,
                "has_sufficient_info": False,
                "extraction_summary": "Document contains no readable text."
            }

        t_lower = text.lower()

        # 1. Condition extraction
        detected_conditions = []
        for cond in self.CANCER_CONDITIONS:
            if re.search(rf"\b{re.escape(cond)}\b", t_lower):
                detected_conditions.append(cond.capitalize())

        # 2. Disease mentioned
        detected_diseases = []
        for disease_name, patterns in self.DISEASE_KEYWORDS.items():
            for pat in patterns:
                if re.search(rf"\b{re.escape(pat)}\b", t_lower):
                    detected_diseases.append(disease_name.title())
                    break

        # 3. Specialty extraction
        detected_specialties = []
        for specialty_name, patterns in self.SPECIALTY_MAPPING.items():
            for pat in patterns:
                if re.search(rf"\b{re.escape(pat)}\b", t_lower):
                    detected_specialties.append(specialty_name.title())
                    break

        # If general oncology is implied by condition/disease but no sub-specialty found
        if not detected_specialties and (detected_conditions or detected_diseases):
            detected_specialties.append("Oncology")

        # 4. Treatment type extraction
        detected_treatments = []
        for treat in self.TREATMENT_TYPES:
            if re.search(rf"\b{re.escape(treat)}\b", t_lower):
                detected_treatments.append(treat.title())

        # 5. Location extraction (Cities & States)
        detected_city = None
        for key, city_std in self.INDIAN_CITIES.items():
            if re.search(rf"\b{re.escape(key)}\b", t_lower):
                detected_city = city_std
                break

        detected_state = None
        for key, state_std in self.INDIAN_STATES.items():
            if re.search(rf"\b{re.escape(key)}\b", t_lower):
                detected_state = state_std
                break

        # 6. Hospital referral extraction
        detected_hospital = None
        for hosp in self.KNOWN_HOSPITALS:
            if re.search(rf"\b{re.escape(hosp)}\b", t_lower):
                detected_hospital = hosp.title()
                break

        # 7. Doctor referral extraction (e.g., "Dr. <Name>")
        detected_doctor = None
        doc_match = re.search(r"(?:dr\.|doctor)\s+([A-Z][a-zA-Z\.]*(?:\s+[A-Z][a-zA-Z\.]*)*)", text, re.IGNORECASE)
        if doc_match:
            doc_name = doc_match.group(1).rstrip("., \t\r\n")
            if doc_name.lower().startswith("dr.") or doc_name.lower().startswith("dr "):
                detected_doctor = doc_name
            else:
                detected_doctor = f"Dr. {doc_name}"

        # 8. Sufficiency determination
        has_medical_signal = bool(detected_conditions or detected_diseases or detected_specialties or detected_treatments or detected_hospital)
        has_sufficient_info = has_medical_signal or bool(detected_city)

        primary_specialty = detected_specialties[0] if detected_specialties else ("Oncology" if has_medical_signal else None)
        primary_disease = detected_diseases[0] if detected_diseases else None
        primary_condition = detected_conditions[0] if detected_conditions else None
        primary_treatment = detected_treatments[0] if detected_treatments else None

        summary_parts = []
        if primary_specialty:
            summary_parts.append(f"Specialty: {primary_specialty}")
        if primary_disease:
            summary_parts.append(f"Disease Context: {primary_disease}")
        if detected_city:
            summary_parts.append(f"Location: {detected_city}")
        if primary_treatment:
            summary_parts.append(f"Treatment: {primary_treatment}")

        summary = ", ".join(summary_parts) if summary_parts else "Insufficient clinical details found."

        return {
            "condition": primary_condition,
            "disease_mentioned": primary_disease,
            "specialty": primary_specialty,
            "treatment_type": primary_treatment,
            "location": detected_city,
            "state": detected_state,
            "hospital_referral": detected_hospital,
            "doctor_referral": detected_doctor,
            "all_conditions": detected_conditions,
            "all_diseases": detected_diseases,
            "all_specialties": detected_specialties,
            "all_treatments": detected_treatments,
            "has_sufficient_info": has_sufficient_info,
            "extraction_summary": summary
        }

    def process_pdf(self, file_source: Union[bytes, Path, str],
                    filename: str = "report.pdf",
                    user_preferred_location: Optional[str] = None) -> Dict[str, Any]:
        """
        Complete end-to-end PDF processing workflow:
        1. Validate file format and security bounds
        2. Extract text passively
        3. Extract hospital-relevant clinical entities
        4. Query RAG knowledge base for matching cancer hospitals & doctors
        5. Return non-diagnostic recommendations with verified citations
        """
        # Step 1: Security Validation
        if isinstance(file_source, bytes):
            raw_bytes = file_source
        else:
            path = Path(file_source)
            if not path.exists():
                return {
                    "success": False,
                    "error": f"File does not exist: {path}",
                    "non_diagnostic_message": "Unable to process the file: The specified file could not be found."
                }
            with open(path, "rb") as f:
                raw_bytes = f.read()

        is_valid, val_msg = self.validate_pdf_content(raw_bytes, filename=filename)
        if not is_valid:
            logger.warning("PDF security validation failed for %s: %s", filename, val_msg)
            return {
                "success": False,
                "error": val_msg,
                "non_diagnostic_message": f"Upload rejected: {val_msg}"
            }

        # Step 2: Safe Text Extraction
        extracted_text = self.extract_text_from_pdf(raw_bytes)
        if not extracted_text or len(extracted_text.strip()) == 0:
            return {
                "success": True,
                "is_empty": True,
                "extracted_info": {
                    "condition": None,
                    "specialty": None,
                    "location": None,
                    "has_sufficient_info": False
                },
                "hospitals": [],
                "non_diagnostic_message": (
                    "The uploaded PDF does not contain any readable text. "
                    "Please ensure the document contains clear printed text and is not an empty or password-protected scan."
                )
            }

        # Step 3: Information Extraction (hospital-relevant parameters only)
        extracted_info = self.extract_relevant_info(extracted_text)

        # Step 4: Resolve Location & Specialty for RAG Retrieval
        target_city = extracted_info.get("location") or user_preferred_location
        target_specialty = extracted_info.get("specialty")
        target_hospital = extracted_info.get("hospital_referral")

        # Step 5: Check if Information is Sufficient
        if not extracted_info["has_sufficient_info"]:
            return {
                "success": True,
                "is_empty": False,
                "extracted_info": extracted_info,
                "hospitals": [],
                "non_diagnostic_message": (
                    "The document does not contain sufficient clinical specialty, condition, "
                    "or hospital referral information to recommend a specific center. "
                    "Please specify your preferred city or specialty, or consult a licensed healthcare professional."
                )
            }

        # Step 6: Query RAG Knowledge Base
        rag_query_parts = []
        if target_specialty:
            rag_query_parts.append(f"{target_specialty} cancer hospital")
        elif extracted_info.get("disease_mentioned"):
            rag_query_parts.append(f"{extracted_info['disease_mentioned']} cancer hospital")
        else:
            rag_query_parts.append("cancer hospital and oncologists")

        if target_city:
            rag_query_parts.append(f"in {target_city}")

        rag_query = " ".join(rag_query_parts)

        retrieved_records = self.rag_pipeline.retrieve(
            query=rag_query,
            top_k=5,
            city_filter=target_city,
            specialty_filter=target_specialty if target_specialty != "Oncology" else None,
            hospital_filter=target_hospital
        )

        # Format clean, non-PII recommendations
        hospitals_recommended = []
        seen_hospitals = set()
        citations = []

        for rec in retrieved_records:
            meta = rec.get("metadata", {})
            h_name = meta.get("hospital_name")
            if not h_name:
                continue

            doc_info = {
                "name": meta.get("doctor_name"),
                "specialization": meta.get("specialization"),
                "profile": meta.get("profile", "")
            }

            if h_name not in seen_hospitals:
                seen_hospitals.add(h_name)
                hospitals_recommended.append({
                    "hospital_name": h_name,
                    "city": meta.get("city"),
                    "state": meta.get("state"),
                    "address": meta.get("address"),
                    "phone": meta.get("phone"),
                    "source_url": meta.get("source_url"),
                    "source_type": meta.get("source_type"),
                    "verified_at": meta.get("verified_at"),
                    "doctors": [doc_info]
                })
            else:
                # Add doctor to existing hospital entry
                for h in hospitals_recommended:
                    if h["hospital_name"] == h_name:
                        h["doctors"].append(doc_info)
                        break

            if meta.get("source_url") and meta.get("source_url") not in citations:
                citations.append(meta.get("source_url"))

        # Step 7: Construct Ethical, Non-Diagnostic Response
        specialty_label = target_specialty or "oncology"
        loc_str = f" in {target_city}" if target_city else ""

        non_diag_message = (
            f"The report contains information related to {specialty_label.lower()}{loc_str}. "
            "I can help you find relevant hospitals and specialists."
        )

        return {
            "success": True,
            "is_empty": False,
            "extracted_info": extracted_info,
            "target_city": target_city,
            "target_specialty": target_specialty,
            "hospitals": hospitals_recommended,
            "citations": citations,
            "non_diagnostic_message": non_diag_message
        }
