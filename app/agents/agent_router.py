import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional
from app.agents.hospital_agent import HospitalAgent
from app.rag.pipeline import RAGPipeline
from app.tools.rag_retrieval_tool import get_shared_rag_pipeline
from app.services.chatbot_service import get_chatbot_response, ChatbotServiceError
from app.services.voice_assistant_service import get_i18n_msg, process_voice_assistant_command

logger = logging.getLogger(__name__)


class TargetIntent(str, Enum):
    NORMAL_CHAT = "normal_chat"
    DIET = "diet"
    HOSPITAL = "hospital"


# Alias for backward compatibility
RouteTarget = TargetIntent


class SafeIntentRouter:
    """
    Production-grade Safe Intent Router.
    Deterministically routes user messages:
    1. NORMAL CHAT: "What is DNA?", "What is mutation?", "Hello.", "Explain machine learning." -> Existing Chatbot / Ollama
    2. DIET: "Create a diet plan." -> Existing Diet Planner
    3. HOSPITAL: "Find cancer hospitals in India.", "Find an oncologist.", "Show doctors.", "Book an appointment.", "Find a hospital near me." -> NEW Hospital Agent + RAG + Tools
    """

    DIET_KEYWORDS = [
        "diet plan", "diet planner", "create a diet plan", "make a diet plan",
        "make diet plan", "i want a diet plan", "nutrition plan", "meal plan",
        "डाइट प्लान", "डाइट प्लानर", "ಡಯಟ್ ಪ್ಲಾನ್", "ಆಹಾರ ಯೋಜನೆ"
    ]

    HOSPITAL_KEYWORDS = [
        # Hospital keywords
        "hospital", "hospitals", "cancer hospital", "cancer hospitals", "best cancer hospital",
        "oncology hospital", "clinic", "medical center", "centre", "center",
        "अस्पताल", "हॉस्पिटल", "ಆಸ್ಪತ್ರೆ",
        # Doctor / Oncologist keywords
        "oncologist", "oncologists", "oncology", "cancer doctor", "cancer doctors",
        "doctor", "doctors", "dr", "dr.", "physician", "specialist", "specialists",
        "surgeon", "cardiologist", "neurologist", "dermatologist", "pediatrician",
        "ऑन्कोलॉजिस्ट", "कैंसर डॉक्टर", "डॉक्टर", "चिकित्सक", "ಕ್ಯಾನ್ಸರ್ ತಜ್ಞರು", "ವೈದ್ಯರು",
        # Appointment / Consultation keywords
        "appointment", "appointments", "book appointment", "book an appointment",
        "schedule appointment", "consultation", "consult", "book", "slot", "slots",
        "availability", "available slots", "check availability",
        "अपॉइंटमेंट", "बुकिंग", "स्लॉट", "ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್", "ಬುಕ್", "ಲಭ್ಯತೆ",
        # Location-based hospital queries
        "hospital near me", "hospitals near me", "doctor near me", "clinic near me",
        "find a hospital near me", "nearest hospital", "closest hospital"
    ]

    def __init__(self, hospital_agent: Optional[HospitalAgent] = None,
                 rag_pipeline: Optional[RAGPipeline] = None):
        self.hospital_agent = hospital_agent or HospitalAgent()
        self.rag_pipeline = rag_pipeline or get_shared_rag_pipeline()

    def classify_intent(self, user_query: str, context: Optional[Dict[str, Any]] = None) -> TargetIntent:
        """
        Classifies user query into TargetIntent.NORMAL_CHAT, TargetIntent.DIET, or TargetIntent.HOSPITAL.
        Preserves conversation context for multi-turn hospital workflows.
        """
        q_clean = (user_query or "").strip()
        q_lower = q_clean.lower()
        ctx = context or {}

        # 1. Check for Active Hospital Agent Contextual Flow
        if ctx.get("awaiting_confirmation") and ctx.get("pending_booking"):
            if re.search(r'\b(?:yes|no|confirm|cancel|stop|proceed|ok|okay|yep|yeah|sure)\b', q_lower) or any(w in q_lower for w in ['हाँ', 'हां', 'हೌದು', 'ಹೌದು', 'ना', 'नहीं', 'ಬೇಡ']):
                return TargetIntent.HOSPITAL

        if ctx.get("last_hospitals") or ctx.get("last_doctors"):
            followup_regex = r'\b(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|#1|#2|#3|first one|second one|show doctors|only|medical|surgical|radiation|pediatric|check availability|available|slots|book|confirm)\b'
            if re.search(followup_regex, q_lower) or re.search(r'\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b', q_lower):
                if not re.search(r'\b(?:what is dna|what is mutation|explain machine learning|create a diet plan|diet plan)\b', q_lower):
                    return TargetIntent.HOSPITAL

        # 2. Check for DIET Intent
        if any(dk in q_lower for dk in self.DIET_KEYWORDS) or re.search(r'\b(?:create|make|generate|need|want)?\s*(?:a\s+)?diet\s*plan\b', q_lower):
            return TargetIntent.DIET

        # 3. Check for HOSPITAL Intent
        # Look for explicit hospital/doctor/appointment keywords
        for hk in self.HOSPITAL_KEYWORDS:
            if " " in hk:
                if hk in q_lower:
                    return TargetIntent.HOSPITAL
            else:
                if re.search(rf"\b{re.escape(hk)}\b", q_lower):
                    return TargetIntent.HOSPITAL

        # Indic script keyword check
        indic_terms = ["कैंसर", "अस्पताल", "ऑन्कोलॉजिस्ट", "डॉक्टर", "अपॉइंटमेंट", "ಕ್ಯಾನ್ಸರ್", "ಆಸ್ಪತ್ರೆ", "ವೈದ್ಯರು", "ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್"]
        if any(term in q_lower for term in indic_terms):
            return TargetIntent.HOSPITAL

        # 4. Fallback: NORMAL CHAT
        return TargetIntent.NORMAL_CHAT

    # Alias for router
    def route(self, user_query: str, context: Optional[Dict[str, Any]] = None) -> TargetIntent:
        return self.classify_intent(user_query, context)

    def dispatch(self, user_query: str,
                 current_page: str = "",
                 language: str = "en",
                 conversation: Optional[List[Dict[str, str]]] = None,
                 context: Optional[Dict[str, Any]] = None,
                 user_id: Optional[int] = None,
                 user_location: Optional[Any] = None,
                 user_info: Optional[Dict[str, Any]] = None,
                 **kwargs) -> Dict[str, Any]:
        """
        Safely dispatches the query to the correct handler:
        - TargetIntent.NORMAL_CHAT -> Existing Chatbot / Ollama
        - TargetIntent.DIET -> Existing Diet Planner
        - TargetIntent.HOSPITAL -> NEW Hospital Agent (Ollama + Tools + RAG)
        """
        target = self.classify_intent(user_query, context=context)
        logger.info("SafeIntentRouter classified '%s' as %s", user_query[:50], target.value)

        # -------------------------------------------------------------
        # BRANCH 1: DIET PLANNER
        # -------------------------------------------------------------
        if target == TargetIntent.DIET:
            msg = get_i18n_msg("CREATE_DIET_PLAN", lang=language)
            return {
                "route": TargetIntent.DIET.value,
                "intent": "CREATE_DIET_PLAN",
                "action": "NAVIGATE",
                "navigate_url": "/health-guidance/",
                "response": msg,
                "spoken_response": msg,
                "language": language,
                "data": {"target": "diet_planner"}
            }

        # -------------------------------------------------------------
        # BRANCH 2: NEW HOSPITAL AGENT + TOOLS + RAG
        # -------------------------------------------------------------
        elif target == TargetIntent.HOSPITAL:
            agent_turn = self.hospital_agent.process_conversation_turn(
                message=user_query,
                conversation_history=conversation,
                context=context,
                user_id=user_id,
                user_location=user_location,
                user_info=user_info,
                language=language
            )

            action_name = agent_turn.get("action", "")
            intent_name = "FIND_HOSPITAL" if action_name == "SHOW_HOSPITALS" else (
                "FIND_DOCTOR" if action_name in ["SHOW_DOCTORS", "FILTER_DOCTORS"] else (
                    "BOOK_APPOINTMENT" if action_name in ["BOOKING_CONFIRMED", "ASK_CONFIRMATION"] else "HOSPITAL_AGENT"
                )
            )

            # Fallback to agent.run() if not handled by contextual multi-turn flow
            if not agent_turn.get("handled"):
                loc_str = str(user_location) if user_location else None
                coords = user_location if isinstance(user_location, dict) and "lat" in user_location else None
                run_res = self.hospital_agent.run(
                    user_query=user_query,
                    user_location=loc_str,
                    user_coords=coords,
                    user_id=user_id,
                    language=language,
                    **kwargs
                )
                return {
                    "route": TargetIntent.HOSPITAL.value,
                    "intent": "FIND_HOSPITAL",
                    "action": "SHOW_RECOMMENDATION",
                    "response": run_res.response,
                    "spoken_response": run_res.response,
                    "language": language,
                    "data": run_res.final_data,
                    "context": context
                }

            return {
                "route": TargetIntent.HOSPITAL.value,
                "intent": intent_name,
                "action": "SHOW_RECOMMENDATION",
                "response": agent_turn.get("response"),
                "spoken_response": agent_turn.get("spoken_response"),
                "language": language,
                "appointment_id": agent_turn.get("appointment_id"),
                "context": agent_turn.get("context"),
                "data": {
                    "appointment_id": agent_turn.get("appointment_id"),
                    "hospitals": agent_turn.get("context", {}).get("last_hospitals", []),
                    "context": agent_turn.get("context")
                }
            }

        # -------------------------------------------------------------
        # BRANCH 3: NORMAL CHAT -> EXISTING CHATBOT / OLLAMA
        # -------------------------------------------------------------
        else:
            q_clean = user_query.strip().lower()
            is_question = bool(re.search(r'^(?:what|explain|how|why|tell me|define|who|when)\b', q_clean)) or '?' in user_query
            is_ui_cmd = bool(re.search(r'^(?:open|go to|navigate to|switch to|turn on)\b', q_clean)) or any(k in q_clean for k in ['dark mode', 'light mode', 'change theme', 'logout', 'log out'])

            if is_ui_cmd and not is_question:
                voice_res = process_voice_assistant_command(
                    message=user_query,
                    current_page=current_page,
                    language=language,
                    user_location=user_location,
                    user_info=user_info,
                    conversation=conversation,
                    pending_action=kwargs.get('pending_action')
                )
                if voice_res and voice_res.get('intent') not in ['CHATBOT_QUERY', 'FIND_HOSPITAL', 'FIND_DOCTOR', 'OPEN_HOSPITALS']:
                    voice_res['route'] = TargetIntent.NORMAL_CHAT.value
                    return voice_res

            try:
                cb_res = get_chatbot_response(
                    user_query,
                    current_page=current_page,
                    language=language,
                    conversation=conversation
                )
                return {
                    "route": TargetIntent.NORMAL_CHAT.value,
                    "intent": "CHATBOT_QUERY",
                    "action": "CHATBOT",
                    "response": cb_res["response"],
                    "language": language
                }
            except ChatbotServiceError as exc:
                logger.warning("ChatbotService error for '%s': %s", user_query[:40], exc)
                return {
                    "route": TargetIntent.NORMAL_CHAT.value,
                    "intent": "CHATBOT_QUERY",
                    "action": "CHATBOT",
                    "response": str(exc),
                    "language": language,
                    "error": str(exc)
                }


# Global AgentRouter alias for compatibility
AgentRouter = SafeIntentRouter
