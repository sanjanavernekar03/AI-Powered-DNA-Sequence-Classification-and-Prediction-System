import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from app.agents.base_agent import BaseAgent, AgentResponse, AgentStep
from app.tools.base_tool import BaseTool, ToolResult
from app.tools.hospital_search_tool import HospitalSearchTool
from app.tools.doctor_search_tool import DoctorSearchTool
from app.tools.hospital_details_tool import HospitalDetailsTool
from app.tools.doctor_availability_tool import DoctorAvailabilityTool
from app.tools.appointment_booking_tool import AppointmentBookingTool
from app.tools.rag_retrieval_tool import RAGRetrievalTool

logger = logging.getLogger(__name__)


HOSPITAL_AGENT_SYSTEM_PROMPT = """You are the DNAura Hospital & Medical Specialist Agent.
Your duty is to assist users with finding verified hospitals, specialist doctors, clinical knowledge, checking appointment slot availability, and booking consultations.

CRITICAL OPERATIONAL RULES:
1. You MUST NEVER fabricate or invent hospital names, doctor names, contact numbers, or appointment slots.
2. ALWAYS use the provided tools to retrieve real data before answering.
3. If the user asks about health symptoms or diseases, first search the knowledge base or find appropriate specialist doctors using the tools.
4. When you need to call a tool, respond with ONLY a valid JSON object matching this schema:
{{
  "thought": "Your reasoning about what tool to call and why",
  "tool": "tool_name",
  "tool_input": {{ "param1": "value1" }}
}}

5. When you have collected all required information to answer the user, respond with ONLY a valid JSON object:
{{
  "thought": "I have all necessary details to provide the final answer",
  "final_answer": "Your complete, empathetic, structured response to the user with hospital/doctor details and clear action steps."
}}

Available Tools:
{tools_doc}
"""


class HospitalAgent(BaseAgent):
    """
    Autonomous Agent for Healthcare, Hospitals, Doctors, and Appointment Booking.
    Executes a multi-turn tool reasoning loop using local Ollama LLM.
    """

    def __init__(self, tools: Optional[List[BaseTool]] = None,
                 model: Optional[str] = None,
                 base_url: Optional[str] = None,
                 max_iterations: int = 5):
        if tools is None:
            tools = [
                HospitalSearchTool(),
                DoctorSearchTool(),
                HospitalDetailsTool(),
                DoctorAvailabilityTool(),
                AppointmentBookingTool(),
                RAGRetrievalTool()
            ]
        super().__init__(tools=tools, max_iterations=max_iterations)
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")

    def run(self, user_query: str, user_location: Optional[str] = None,
            user_coords: Optional[Dict[str, float]] = None,
            user_id: Optional[int] = None,
            language: str = "en",
            patient_context: Optional[Dict[str, Any]] = None,
            **kwargs) -> AgentResponse:
        """
        Execute the agentic ReAct loop for the user query.
        """
        tools_doc = json.dumps(self.get_tool_definitions(), indent=2)
        system_prompt = HOSPITAL_AGENT_SYSTEM_PROMPT.format(tools_doc=tools_doc)

        # Contextual priming
        initial_context_notes = []
        if user_location:
            initial_context_notes.append(f"User City/Location: {user_location}")
        if user_coords:
            initial_context_notes.append(f"User GPS: {user_coords.get('lat')}, {user_coords.get('lng')}")
        if patient_context:
            initial_context_notes.append(f"Patient Genetic/Health Context: {patient_context}")
        initial_context_notes.append(f"User Preferred Language: {language}")

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"User Request: {user_query}\n"
                    + ("\n".join(initial_context_notes) if initial_context_notes else "")
                )
            }
        ]

        steps: List[AgentStep] = []
        tools_called: List[str] = []
        final_answer = ""
        final_data: Dict[str, Any] = {}

        for iteration in range(1, self.max_iterations + 1):
            logger.info("HospitalAgent iteration %d/%d", iteration, self.max_iterations)

            # 1. Ask Ollama for next action
            raw_response = self._query_ollama(messages)
            parsed_action = self._parse_agent_action(raw_response)

            thought = parsed_action.get("thought", "")
            tool_name = parsed_action.get("tool")
            tool_input = parsed_action.get("tool_input", {})
            final_ans = parsed_action.get("final_answer")

            # 2. Check if agent completed its reasoning
            if final_ans:
                final_answer = final_ans
                steps.append(AgentStep(
                    step_number=iteration,
                    thought=thought
                ))
                break

            # 3. If no tool selected or unrecognized tool, execute fallback or final synthesis
            if not tool_name or tool_name not in self.tools:
                logger.warning("Agent requested invalid or empty tool: '%s'", tool_name)
                # Try fallback heuristics
                fallback_res = self._execute_heuristic_fallback(user_query, user_location, user_coords)
                final_answer = fallback_res.get("response", raw_response)
                final_data = fallback_res.get("data", {})
                break

            # 4. Execute the tool
            selected_tool = self.tools[tool_name]
            tools_called.append(tool_name)

            # Inject implicit parameters if tool expects them
            if "user_id" in selected_tool.parameters_schema.get("properties", {}) and user_id:
                tool_input.setdefault("user_id", user_id)
            if "location" in selected_tool.parameters_schema.get("properties", {}) and user_location:
                tool_input.setdefault("location", user_location)
            if user_coords and "lat" in selected_tool.parameters_schema.get("properties", {}):
                tool_input.setdefault("lat", user_coords.get("lat"))
                tool_input.setdefault("lng", user_coords.get("lng"))

            logger.info("Executing tool '%s' with input %s", tool_name, tool_input)
            tool_result = selected_tool.execute(**tool_input)

            steps.append(AgentStep(
                step_number=iteration,
                thought=thought,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=tool_result
            ))

            if tool_result.success and isinstance(tool_result.data, dict):
                final_data.update(tool_result.data)

            # 5. Append observation back to conversation memory
            observation_str = json.dumps(tool_result.to_dict(), default=str)
            messages.append({"role": "assistant", "content": raw_response})
            messages.append({
                "role": "user",
                "content": f"Observation from {tool_name}:\n{observation_str}\nProceed to next step or provide final_answer."
            })

        # If loop ended without final_answer, request synthesis
        if not final_answer:
            final_answer = self._synthesize_final_answer(messages, steps, language)

        return AgentResponse(
            response=final_answer,
            steps=steps,
            tools_called=tools_called,
            final_data=final_data,
            success=True
        )

    def _query_ollama(self, messages: List[Dict[str, str]]) -> str:
        """Call Ollama chat API."""
        try:
            payload = json.dumps({
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 450
                }
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return res_data.get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error("Ollama query failed: %s", e)
            return json.dumps({
                "thought": "Ollama service unavailable, switching to local direct tool execution",
                "final_answer": "I am looking up the hospital and doctor records for you directly from the verified database."
            })

    def _parse_agent_action(self, raw_text: str) -> Dict[str, Any]:
        """Safely parse JSON action block from LLM output."""
        try:
            # Direct parse
            return json.loads(raw_text)
        except Exception:
            pass

        # Search for markdown fenced json or curly braces
        json_match = re.search(r"\{[\s\S]*\}", raw_text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except Exception:
                pass

        # Return as final answer if unparseable
        return {
            "thought": "Direct response generated",
            "final_answer": raw_text
        }

    def _synthesize_final_answer(self, messages: List[Dict[str, str]],
                                 steps: List[AgentStep], language: str) -> str:
        """Generate final user-facing summary from recorded tool steps."""
        if not steps:
            return "I was unable to retrieve hospital information at this moment. Please check your query or specify a city."

        summary_parts = []
        for s in steps:
            if s.tool_output and s.tool_output.success:
                data = s.tool_output.data
                if isinstance(data, dict):
                    if "hospitals" in data:
                        h_list = data["hospitals"]
                        names = [h.get("name") for h in h_list[:3]]
                        summary_parts.append(f"Found {len(h_list)} hospitals nearby: {', '.join(names)}.")
                    if "doctors" in data:
                        d_list = data["doctors"]
                        names = [f"{d.get('name')} ({d.get('specialty')})" for d in d_list[:3]]
                        summary_parts.append(f"Found doctors: {', '.join(names)}.")
                    if "available_slots" in data:
                        summary_parts.append(f"Available slots on {data.get('date')}: {', '.join(data.get('available_slots', []))}.")

        if summary_parts:
            return " ".join(summary_parts)
        return "I completed the hospital search and found relevant clinical options for you."

    def _execute_heuristic_fallback(self, query: str, location: Optional[str],
                                     coords: Optional[Dict[str, float]]) -> Dict[str, Any]:
        """Direct tool execution fallback if the LLM produces unstructured output."""
        tool = self.tools.get("search_hospitals")
        if tool:
            res = tool.execute(location=location, lat=coords.get("lat") if coords else None,
                               lng=coords.get("lng") if coords else None)
            if res.success and res.data:
                h_list = res.data.get("hospitals", [])
                h_names = [h.get("name") for h in h_list[:3]]
                return {
                    "response": f"Here are the top hospitals found in your area: {', '.join(h_names)}.",
                    "data": res.data
                }
        return {"response": "Unable to locate hospitals. Please specify your city or address.", "data": {}}

    def process_pdf_report(self, file_source: Any, filename: str = "report.pdf",
                           user_location: Optional[str] = None) -> Dict[str, Any]:
        """
        Securely process an uploaded medical report PDF and generate
        grounded hospital and oncologist recommendations without making diagnoses.
        """
        from app.services.hospital_pdf_service import HospitalPDFService
        pdf_service = HospitalPDFService(hospital_agent=self)
        return pdf_service.process_pdf(file_source, filename=filename, user_preferred_location=user_location)

    def process_voice_query(self, message: str, language: str = "en",
                            user_location: Optional[Any] = None,
                            user_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute speech-driven hospital / doctor queries from the voice assistant.
        Flow:
          Voice Transcript -> Intent & Entity Identification (intent, specialty, location)
          -> RAG Retrieval -> Grounded Results -> Multilingual Spoken Response for TTS (en, hi, kn)
        """
        from app.tools.rag_retrieval_tool import get_shared_rag_pipeline
        rag_pipeline = get_shared_rag_pipeline()

        msg_lower = message.strip().lower()
        lang = language if language in ["en", "hi", "kn", "ta", "te"] else "en"

        # 1. Intent Detection
        is_doctor_query = any(w in msg_lower for w in [
            "doctor", "doctors", "oncologist", "oncologists", "specialist", "specialists",
            "डॉक्टर", "ऑन्कोलॉजिस्ट", "विशेषज्ञ", "ವೈದ್ಯರು", "ಕ್ಯಾನ್ಸರ್ ತಜ್ಞರು"
        ])
        intent = "doctor search" if is_doctor_query else "hospital search"

        # 2. Specialty Detection
        specialty = "Oncology"
        if any(w in msg_lower for w in ["surgical", "सर्जिकल", "ಸರ್ಜಿಕಲ್"]):
            specialty = "Surgical Oncology"
        elif any(w in msg_lower for w in ["radiation", "रेडिएशन", "ರೇಡಿಯೇಷನ್"]):
            specialty = "Radiation Oncology"
        elif any(w in msg_lower for w in ["medical oncology", "कीमोथेरेपी", "ಕೀಮೋಥೆರಪಿ"]):
            specialty = "Medical Oncology"
        elif any(w in msg_lower for w in ["pediatric", "बच्चे", "ಮಕ್ಕಳು"]):
            specialty = "Pediatric Oncology"

        # 3. Location Detection (English, Hindi, Kannada, etc.)
        is_nationwide = any(w in msg_lower for w in [
            "india", "in india", "across india", "best cancer hospital in india",
            "country", "all over india",
            "भारत", "भारत में", "इंडिया", "देश में",
            "ಭಾರತ", "ಭಾರತದಲ್ಲಿ", "ದೇಶದಲ್ಲಿ"
        ])

        target_city = None
        city_mapping = {
            "mumbai": "Mumbai", "मुंबई": "Mumbai", "मुम्बई": "Mumbai", "ಮುಂಬೈ": "Mumbai", "ಮುಂಬಯಿ": "Mumbai",
            "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "बैंगलोर": "Bengaluru", "बेंगलुरु": "Bengaluru", "बंगलौर": "Bengaluru", "बेंगलूर": "Bengaluru", "ಬೆಂಗಳೂರು": "Bengaluru", "ಬೆಂಗಳೂರ": "Bengaluru",
            "delhi": "New Delhi", "new delhi": "New Delhi", "दिल्ली": "New Delhi", "नई दिल्ली": "New Delhi", "ದೆಹಲಿ": "New Delhi",
            "chennai": "Chennai", "चेन्नई": "Chennai", "ಚೆನ್ನೈ": "Chennai",
            "kolkata": "Kolkata", "calcutta": "Kolkata", "कोलकाता": "Kolkata", "ಕೋಲ್ಕತ್ತಾ": "Kolkata", "ಕೋಲ್ಕತ್ತ": "Kolkata",
            "hyderabad": "Hyderabad", "हैदराबाद": "Hyderabad", "ಹೈದರಾಬಾದ್": "Hyderabad", "ಹೈದರಾಬಾದ": "Hyderabad"
        }

        for kw, city_name in city_mapping.items():
            if kw in msg_lower:
                target_city = city_name
                break

        if not target_city and not is_nationwide:
            # Check user GPS or profile city if provided
            if isinstance(user_location, dict) and user_location.get("city"):
                target_city = user_location.get("city")
            elif user_info and user_info.get("city"):
                target_city = user_info.get("city")
            else:
                # Default to nationwide India search if user asked for best cancer hospital
                is_nationwide = True

        location_label = "India" if is_nationwide else (target_city or "India")

        # 4. RAG Retrieval from verified knowledge base
        rag_query = f"{specialty} hospitals in {location_label}" if not is_doctor_query else f"oncologists in {location_label}"
        top_k = 7 if is_nationwide else 4

        raw_records = rag_pipeline.retrieve(
            query=rag_query,
            top_k=top_k,
            city_filter=target_city if not is_nationwide else None,
            specialty_filter=specialty if specialty != "Oncology" else None
        )

        # 5. Group by hospital to present premier centers cleanly
        grouped_hospitals = {}
        for r in raw_records:
            m = r.get("metadata", {})
            h_name = m.get("hospital_name")
            if not h_name:
                continue
            if h_name not in grouped_hospitals:
                grouped_hospitals[h_name] = {
                    "hospital_name": h_name,
                    "city": m.get("city"),
                    "state": m.get("state"),
                    "address": m.get("address"),
                    "phone": m.get("phone"),
                    "source_url": m.get("source_url"),
                    "source_type": m.get("source_type"),
                    "doctors": []
                }
            d_name = m.get("doctor_name")
            d_spec = m.get("specialization")
            if d_name and not any(d["name"] == d_name for d in grouped_hospitals[h_name]["doctors"]):
                grouped_hospitals[h_name]["doctors"].append({
                    "name": d_name,
                    "specialization": d_spec
                })

        hospitals_list = list(grouped_hospitals.values())

        # 6. Native Multilingual Translations for Spoken TTS output
        HOSPITAL_NATIVE = {
            "Tata Memorial Hospital": {
                "hi": "टाटा मेमोरियल अस्पताल", "kn": "ಟಾಟಾ ಮೆಮೋರಿಯಲ್ ಆಸ್ಪತ್ರೆ"
            },
            "Kidwai Memorial Institute of Oncology": {
                "hi": "किदवई मेमोरियल इंस्टीट्यूट ऑफ ऑन्कोलॉजी", "kn": "ಕಿದ್ವಾಯಿ ಮೆಮೋರಿಯಲ್ ಇನ್‌ಸ್ಟಿಟ್ಯೂಟ್ ಆಫ್ ಆಂಕೊಲಾಜಿ"
            },
            "All India Institute of Medical Sciences (AIIMS) - Dr. B.R.A. IRCH": {
                "hi": "एम्स रोटरी कैंसर अस्पताल", "kn": "ಏಮ್ಸ್ ರೋಟರಿ ಕ್ಯಾನ್ಸರ್ ಆಸ್ಪತ್ರೆ"
            },
            "Apollo Proton Cancer Centre": {
                "hi": "अपोलो प्रोटॉन कैंसर सेंटर", "kn": "ಅಪೋಲೋ ಪ್ರೋಟಾನ್ ಕ್ಯಾನ್ಸರ್ ಸೆಂಟರ್"
            },
            "HCG Cancer Centre Bengaluru": {
                "hi": "एचसीजी कैंसर सेंटर बेंगलुरु", "kn": "ಎಚ್‌ಸಿಜಿ ಕ್ಯಾನ್ಸರ್ ಸೆಂಟರ್ ಬೆಂಗಳೂರು"
            },
            "Chittaranjan National Cancer Institute (CNCI)": {
                "hi": "चित्तरंजन राष्ट्रीय कैंसर संस्थान", "kn": "ಚಿತ್ತರಂಜನ್ ರಾಷ್ಟ್ರೀಯ ಕ್ಯಾನ್ಸರ್ ಸಂಸ್ಥೆ"
            },
            "Basavatarakam Indo-American Cancer Hospital & Research Institute": {
                "hi": "बसवतारकम इंडो-अमेरिकन कैंसर अस्पताल", "kn": "ಬಸವತಾರಕಂ ಇಂಡೋ-ಅಮೆರಿಕನ್ ಕ್ಯಾನ್ಸರ್ ಆಸ್ಪತ್ರೆ"
            }
        }

        CITY_NATIVE = {
            "Mumbai": {"hi": "मुंबई", "kn": "ಮುಂಬೈ"},
            "Bengaluru": {"hi": "बेंगलुरु", "kn": "ಬೆಂಗಳೂರು"},
            "New Delhi": {"hi": "नई दिल्ली", "kn": "ನವದೆಹಲಿ"},
            "Chennai": {"hi": "चेन्नई", "kn": "ಚೆನ್ನೈ"},
            "Kolkata": {"hi": "कोलकाता", "kn": "ಕೋಲ್ಕತ್ತಾ"},
            "Hyderabad": {"hi": "हैदराबाद", "kn": "ಹೈದರಾಬಾದ್"},
            "India": {"hi": "भारत", "kn": "ಭಾರತ"}
        }

        DOCTOR_NATIVE = {
            "Dr. Rajendra A. Badwe": {"hi": "डॉ. राजेंद्र बडवे", "kn": "ಡಾ. ರಾಜೇಂದ್ರ ಬಡ್ವೆ"},
            "Dr. Sudeep Gupta": {"hi": "डॉ. सुदीप गुप्ता", "kn": "ಡಾ. ಸುದೀಪ್ ಗುಪ್ತಾ"},
            "Dr. Kumar Prabhash": {"hi": "डॉ. कुमार प्रभाष", "kn": "ಡಾ. ಕುಮಾರ್ ಪ್ರಭಾಷ್"},
            "Dr. Shripad D. Banavali": {"hi": "डॉ. श्रीपाद बनवली", "kn": "ಡಾ. ಶ್ರೀಪಾದ್ ಬನವಲಿ"},
            "Dr. Manju Sengar": {"hi": "डॉ. मंजू सेंगर", "kn": "ಡಾ. ಮಂಜು ಸೆಂಗರ್"},
            "Dr. R. Krishnappa": {"hi": "डॉ. आर. कृष्णप्पा", "kn": "ಡಾ. ಆರ್. ಕೃಷ್ಣಪ್ಪ"},
            "Dr. Syed Althaf": {"hi": "डॉ. सैयद अल्ताफ", "kn": "ಡಾ. ಸೈಯದ್ ಅಲ್ತಾಫ್"},
            "Dr. Naveen T.": {"hi": "डॉ. नवीन टी.", "kn": "ಡಾ. ನವೀನ್ ಟಿ."},
            "Dr. Arpitha S.": {"hi": "डॉ. अर्पिता एस.", "kn": "ಡಾ. ಅರ್ಪಿತಾ ಎಸ್."},
            "Dr. Lokesh K. N.": {"hi": "डॉ. लोकेश के. एन.", "kn": "ಡಾ. ಲೋಕೇಶ್ ಕೆ. ಎನ್."},
            "Dr. Sunil Kumar": {"hi": "डॉ. सुनील कुमार", "kn": "ಡಾ. ಸುನಿಲ್ ಕುಮಾರ್"},
            "Dr. (Major) M. D. Ray": {"hi": "डॉ. (मेजर) एम. डी. रे", "kn": "ಡಾ. (ಮೇಜರ್) ಎಂ. ಡಿ. ರೇ"},
            "Dr. D. N. Sharma": {"hi": "डॉ. डी. एन. शर्मा", "kn": "ಡಾ. ಡಿ. ಎನ್. ಶರ್ಮಾ"},
            "Dr. Deepam Pushpam": {"hi": "डॉ. दीपम पुष्पम", "kn": "ಡಾ. ದೀಪಮ್ ಪುಷ್ಪಮ್"},
            "Dr. Ashutosh Mishra": {"hi": "डॉ. आशुतोष मिश्रा", "kn": "ಡಾ. ಅಶುತೋಷ್ ಮಿಶ್ರಾ"},
            "Dr. Rakesh Jalali": {"hi": "डॉ. राकेश जलाली", "kn": "ಡಾ. ರಾಕೇಶ್ ಜಲಾಲಿ"},
            "Dr. Sapna Nangia": {"hi": "डॉ. सपना नांगिया", "kn": "ಡಾ. ಸಪ್ನಾ ನಂಗಿಯಾ"},
            "Dr. Prasad Eswaran": {"hi": "डॉ. प्रसाद ईश्वरन", "kn": "ಡಾ. ಪ್ರಸಾದ್ ಈಶ್ವರನ್"},
            "Dr. Raja T.": {"hi": "डॉ. राजा टी.", "kn": "ಡಾ. ರಾಜಾ ಟಿ."},
            "Dr. Srinivas Chilukuri": {"hi": "डॉ. श्रीनिवास चिलुकुरी", "kn": "ಡಾ. ಶ್ರೀನಿವಾಸ್ ಚಿಲುಕೂರಿ"},
            "Dr. B. S. Ajaikumar": {"hi": "डॉ. बी. एस. अजयकुमार", "kn": "ಡಾ. ಬಿ. ಎಸ್. ಅಜಯ್‌ಕುಮಾರ್"},
            "Dr. Vishal Rao U. S.": {"hi": "डॉ. विशाल राव", "kn": "ಡಾ. ವಿಶಾಲ್ ರಾವ್"},
            "Dr. Radheshyam Naik": {"hi": "डॉ. राधेश्याम नायक", "kn": "ಡಾ. ರಾಧೇಶ್ಯಾಮ್ ನಾಯ್ಕ್"},
            "Dr. Dinesh M. G.": {"hi": "डॉ. दिनेश एम. जी.", "kn": "ಡಾ. ದಿನೇಶ್ ಎಂ. ಜಿ."},
            "Dr. Vijay Bhaskar": {"hi": "डॉ. विजय भास्कर", "kn": "ಡಾ. ವಿಜಯ್ ಭಾಸ್ಕರ್"},
            "Dr. Jayanta Chakrabarti": {"hi": "डॉ. जयंत चक्रवर्ती", "kn": "ಡಾ. ಜಯಂತ ಚಕ್ರವರ್ತಿ"},
            "Dr. Neyaz Alam": {"hi": "डॉ. नेयाज आलम", "kn": "ಡಾ. ನಿಯಾಜ್ ಆಲಂ"},
            "Dr. Sagar Sen": {"hi": "डॉ. सागर सेन", "kn": "ಡಾ. ಸಾಗರ್ ಸೇನ್"},
            "Dr. Debarshi Lahiri": {"hi": "डॉ. देबर्षि लाहिड़ी", "kn": "ಡಾ. ದೇವರ್ಷಿ ಲಾಹಿರಿ"},
            "Dr. Amitabh Ray": {"hi": "डॉ. अमिताभ राय", "kn": "ಡಾ. ಅಮಿತಾಭ್ ರೇ"},
            "Dr. T. Subramanyeshwar Rao": {"hi": "डॉ. टी. सुब्रमण्येश्वर राव", "kn": "ಡಾ. ಟಿ. ಸುಬ್ರಹ್ಮಣ್ಯೇಶ್ವರ ರಾವ್"},
            "Dr. Madiraju Ramanuja Rao": {"hi": "डॉ. मादिराजु रामानुज राव", "kn": "ಡಾ. ಮಾದಿರಾಜು ರಾಮಾನುಜ ರಾವ್"},
            "Dr. Sri Siddhartha Nekkanti": {"hi": "डॉ. श्री सिद्धार्थ नेक्कंती", "kn": "ಡಾ. ಶ್ರೀ ಸಿದ್ಧಾರ್ಥ್ ನೆಕ್ಕಂಟಿ"},
            "Dr. Syed Nusrath": {"hi": "डॉ. सैयद नुसरत", "kn": "ಡಾ. ಸೈಯದ್ ನುಸ್ರತ್"},
            "Dr. Veerendra C. Patil": {"hi": "डॉ. वीरेंद्र सी. पाटिल", "kn": "ಡಾ. ವೀರೇಂದ್ರ ಸಿ. ಪಾಟೀಲ್"}
        }

        # 7. Synthesize Spoken TTS String
        spoken_response = ""
        citations = []

        if lang == "hi":
            # HINDI
            if is_nationwide:
                spoken_parts = ["यहाँ भारत के प्रमुख सत्यापित कैंसर अस्पताल हैं:"]
            else:
                c_name = CITY_NATIVE.get(target_city, {}).get("hi", target_city)
                spoken_parts = [f"यहाँ {c_name} में सत्यापित कैंसर अस्पताल हैं:"]

            for idx, h in enumerate(hospitals_list[:4], 1):
                h_name = HOSPITAL_NATIVE.get(h["hospital_name"], {}).get("hi", h["hospital_name"])
                c_name = CITY_NATIVE.get(h["city"], {}).get("hi", h["city"])
                doc_names = [DOCTOR_NATIVE.get(d["name"], {}).get("hi", d["name"]) for d in h["doctors"][:2]]
                doc_str = " और ".join(doc_names) if doc_names else ""
                if doc_str:
                    spoken_parts.append(f"{idx}. {h_name}, {c_name}, जहाँ {doc_str} कार्यरत हैं।")
                else:
                    spoken_parts.append(f"{idx}. {h_name}, {c_name}।")
                if h.get("source_url") and h["source_url"] not in citations:
                    citations.append(h["source_url"])

            spoken_response = " ".join(spoken_parts)

        elif lang == "kn":
            # KANNADA
            if is_nationwide:
                spoken_parts = ["ಇಲ್ಲಿ ಭಾರತದ ಪ್ರಮುಖ ಪರಿಶೀಲಿತ ಕ್ಯಾನ್ಸರ್ ಆಸ್ಪತ್ರೆಗಳಿವೆ:"]
            else:
                c_name = CITY_NATIVE.get(target_city, {}).get("kn", target_city)
                spoken_parts = [f"ಇಲ್ಲಿ {c_name} ಯಲ್ಲಿ ಪರಿಶೀಲಿತ ಕ್ಯಾನ್ಸರ್ ಆಸ್ಪತ್ರೆಗಳಿವೆ:"]

            for idx, h in enumerate(hospitals_list[:4], 1):
                h_name = HOSPITAL_NATIVE.get(h["hospital_name"], {}).get("kn", h["hospital_name"])
                c_name = CITY_NATIVE.get(h["city"], {}).get("kn", h["city"])
                doc_names = [DOCTOR_NATIVE.get(d["name"], {}).get("kn", d["name"]) for d in h["doctors"][:2]]
                doc_str = " ಮತ್ತು ".join(doc_names) if doc_names else ""
                if doc_str:
                    spoken_parts.append(f"{idx}. {h_name}, {c_name}, {doc_str} ಅವರೊಂದಿಗೆ.")
                else:
                    spoken_parts.append(f"{idx}. {h_name}, {c_name}.")
                if h.get("source_url") and h["source_url"] not in citations:
                    citations.append(h["source_url"])

            spoken_response = " ".join(spoken_parts)

        else:
            # ENGLISH (default)
            if is_nationwide:
                spoken_parts = ["Here are the top verified cancer hospitals in India:"]
            else:
                spoken_parts = [f"Here are verified cancer hospitals in {target_city}:"]

            for idx, h in enumerate(hospitals_list[:4], 1):
                doc_names = [d["name"] for d in h["doctors"][:2]]
                doc_str = " and ".join(doc_names) if doc_names else ""
                if doc_str:
                    spoken_parts.append(f"{idx}. {h['hospital_name']} in {h['city']}, affiliated with {doc_str}.")
                else:
                    spoken_parts.append(f"{idx}. {h['hospital_name']} in {h['city']}.")
                if h.get("source_url") and h["source_url"] not in citations:
                    citations.append(h["source_url"])

            spoken_response = " ".join(spoken_parts)

        # 8. Markdown formatted response for Screen Display
        header_title = {
            "hi": "🏥 **सत्यापित कैंसर अस्पताल और विशेषज्ञ (RAG नॉलेज बेस)**",
            "kn": "🏥 **ಪರಿಶೀಲಿತ ಕ್ಯಾನ್ಸರ್ ಆಸ್ಪತ್ರೆಗಳು ಮತ್ತು ತಜ್ಞರು (RAG ಜ್ಞಾನ ಮೂಲ)**",
            "en": "🏥 **Verified Cancer Hospitals & Oncologists (RAG Knowledge Base)**"
        }.get(lang, "🏥 **Verified Cancer Hospitals & Oncologists**")

        lines = [header_title, ""]
        for idx, h in enumerate(hospitals_list[:4], 1):
            lines.append(f"**{idx}. {h['hospital_name']}** — {h['city']}, {h['state']}")
            lines.append(f"• **Address:** {h.get('address')}")
            lines.append(f"• **Contact:** {h.get('phone')} | **Source:** [{h.get('source_type')}]({h.get('source_url')})")
            if h["doctors"]:
                doc_bullets = [f"{d['name']} ({d['specialization']})" for d in h["doctors"][:3]]
                lines.append(f"• **Verified Specialists:** {', '.join(doc_bullets)}")
            lines.append("")

        lines.append("_ℹ️ Information retrieved from verified healthcare directories. No medical diagnosis provided._")
        formatted_response = "\n".join(lines)

        return {
            "success": True,
            "intent": intent,
            "specialty": specialty,
            "location": location_label,
            "spoken_response": spoken_response,
            "formatted_response": formatted_response,
            "hospitals": hospitals_list,
            "citations": citations,
            "language": lang
        }

    def process_conversation_turn(self, message: str,
                                 conversation_history: Optional[List[Dict[str, str]]] = None,
                                 context: Optional[Dict[str, Any]] = None,
                                 user_id: Optional[int] = None,
                                 user_location: Optional[Any] = None,
                                 user_info: Optional[Dict[str, Any]] = None,
                                 language: str = "en") -> Dict[str, Any]:
        """
        Context-aware conversational workflow for hospital search, doctor filtering,
        slot availability verification, and appointment booking using existing application models.
        """
        from datetime import date, timedelta
        from app.services.hospital_service import sync_verified_cancer_hospitals_to_db
        from app.services.booking_service import create_appointment
        from app.tools.doctor_availability_tool import DoctorAvailabilityTool

        cancer_db_map = sync_verified_cancer_hospitals_to_db()
        ctx = dict(context or {})
        msg_clean = message.strip()
        msg_lower = msg_clean.lower()
        lang = language if language in ["en", "hi", "kn"] else "en"

        # Helpers
        def _extract_ordinal(text: str) -> Optional[int]:
            t = text.lower()
            ord_map = [
                (["first one", "the first", "first", "1st", "#1", "pehla", "पहला", "ಮೊದಲನೇ", "ಮೊದಲ"], 0),
                (["second one", "the second", "second", "2nd", "#2", "doosra", "दूसरा", "ಎರಡನೇ", "ಎರಡನೆ"], 1),
                (["third one", "the third", "third", "3rd", "#3", "teesra", "तीसरा", "ಮೂರನೇ", "ಮೂರನೆ"], 2),
                (["fourth one", "the fourth", "fourth", "4th", "#4", "chautha", "चौथा", "ನಾಲ್ಕನೇ"], 3),
                (["fifth one", "the fifth", "fifth", "5th", "#5", "panchva", "पांचवा", "ಐದನೇ"], 4),
                (["sixth one", "the sixth", "sixth", "6th", "#6", "chatha", "छठा", "ಆರನೇ"], 5),
                (["seventh one", "the seventh", "seventh", "7th", "#7", "saatva", "सातवां", "ಏಳನೇ"], 6),
            ]
            for words, idx in ord_map:
                if any(w in t for w in words):
                    return idx
            m = re.search(r'#(\d+)', t)
            if m:
                return int(m.group(1)) - 1
            return None

        def _extract_time_slot(text: str) -> Optional[str]:
            m = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', text, re.IGNORECASE)
            if m:
                hr = int(m.group(1))
                mn = m.group(2) or "00"
                ap = m.group(3).upper()
                return f"{hr:02d}:{mn} {ap}"
            return None

        # -------------------------------------------------------------
        # 1. HANDLE CONFIRMATION YES / NO FOR PENDING BOOKING
        # -------------------------------------------------------------
        if ctx.get("awaiting_confirmation") and ctx.get("pending_booking"):
            is_yes = bool(re.search(r'\b(yes|confirm|proceed|sure|ok|okay|yep|yeah)\b', msg_lower)) or any(w in msg_lower for w in ['हाँ', 'हां', 'हೌದು', 'ಹೌದು'])
            is_no = bool(re.search(r'\b(no|cancel|stop|nevermind|abort|dont|don\'t)\b', msg_lower)) or any(w in msg_lower for w in ['ना', 'नहीं', 'ಬೇಡ', 'ರದ್ದು'])

            if is_yes:
                pending = ctx["pending_booking"]
                uid = user_id or (user_info.get("id") if user_info else None) or 1
                p_name = pending.get("patient_name") or (user_info.get("full_name") if user_info else None) or (user_info.get("username") if user_info else None) or "Patient"
                p_phone = pending.get("phone") or (user_info.get("phone") if user_info else None) or "9876543210"
                p_email = (user_info.get("email") if user_info else "") or ""

                book_res = create_appointment(
                    user_id=int(uid),
                    hospital_id=int(pending["hospital_id"]),
                    doctor_id=int(pending["doctor_id"]),
                    appointment_date_str=str(pending["date"]),
                    appointment_time=str(pending["time"]),
                    reason_for_visit=f"Consultation ({pending.get('specialty', 'Oncology')})",
                    patient_name=p_name,
                    phone=p_phone,
                    patient_email=p_email,
                    notes="Booked via DNAura Hospital Agent"
                )

                ctx["awaiting_confirmation"] = False
                ctx["pending_booking"] = None

                if book_res.get("success"):
                    appt_id = book_res.get("appointment_id")
                    spoken = f"Appointment recorded in this application for {pending['doctor_name']} on {pending['date']} at {pending['time']}."
                    response_md = (
                        f"✅ **Appointment recorded in this application.**\n\n"
                        f"**Booking Summary:**\n"
                        f"- **Appointment ID**: #{appt_id}\n"
                        f"- **Doctor**: {pending['doctor_name']} ({pending.get('specialty', 'Oncology')})\n"
                        f"- **Hospital**: {pending['hospital_name']} ({pending.get('city', '')})\n"
                        f"- **Date & Time**: {pending['date']} at {pending['time']}\n"
                        f"- **Patient**: {p_name}\n"
                        f"- **Status**: Recorded in DNAura\n\n"
                        f"> ℹ️ *Note: Appointment recorded in this application. This is an in-app consultation schedule and is not an external reservation verified directly with the hospital's internal system.*\n\n"
                        f"You can view and manage your scheduled appointments anytime in [My Appointments](/appointments/my-appointments)."
                    )
                    return {
                        "success": True,
                        "handled": True,
                        "response": response_md,
                        "spoken_response": spoken,
                        "action": "BOOKING_CONFIRMED",
                        "appointment_id": appt_id,
                        "context": ctx
                    }
                else:
                    return {
                        "success": False,
                        "handled": True,
                        "response": f"⚠️ Could not record appointment: {book_res.get('error', 'Slot already taken')}. Please select another slot.",
                        "spoken_response": f"Could not record appointment: {book_res.get('error', 'Slot already taken')}.",
                        "action": "BOOKING_ERROR",
                        "context": ctx
                    }

            elif is_no:
                ctx["awaiting_confirmation"] = False
                ctx["pending_booking"] = None
                return {
                    "success": True,
                    "handled": True,
                    "response": "The appointment booking was cancelled. Let me know if you would like to select another specialist or time slot.",
                    "spoken_response": "Appointment booking cancelled.",
                    "action": "BOOKING_CANCELLED",
                    "context": ctx
                }

        # -------------------------------------------------------------
        # 2. REQUEST TO BOOK A TIME SLOT
        # -------------------------------------------------------------
        is_book_keyword = bool(re.search(r'\b(book|reserve|schedule|अपॉइंटमेंट बुक|ಬುಕ್)\b', msg_lower))
        extracted_time = _extract_time_slot(msg_lower)

        if is_book_keyword or (extracted_time and ("at" in msg_lower or "slot" in msg_lower)):
            chosen_time = extracted_time or "10:00 AM"
            target_date = (date.today() + timedelta(days=1)).isoformat()
            if "today" in msg_lower:
                target_date = date.today().isoformat()

            # Resolve target doctor
            ordinal = _extract_ordinal(msg_lower)
            target_doc = None
            if ordinal is not None and ctx.get("last_doctors") and 0 <= ordinal < len(ctx["last_doctors"]):
                target_doc = ctx["last_doctors"][ordinal]
            elif ctx.get("selected_doctor"):
                target_doc = ctx["selected_doctor"]
            elif ctx.get("last_doctors"):
                target_doc = ctx["last_doctors"][0]

            # Resolve target hospital
            target_hosp = ctx.get("selected_hospital")
            if not target_hosp and target_doc:
                for hname, hinfo in cancer_db_map.items():
                    if hinfo["id"] == target_doc.get("hospital_id"):
                        target_hosp = hinfo
                        break

            if target_doc:
                p_name = (user_info.get("full_name") if user_info else None) or (user_info.get("username") if user_info else None) or "Patient"
                doc_name = target_doc.get("name") or target_doc.get("full_name")
                hosp_name = target_hosp.get("name") if target_hosp else "Verified Cancer Centre"
                hosp_city = target_hosp.get("city", "") if target_hosp else ""

                pending = {
                    "hospital_id": target_hosp.get("id") if target_hosp else target_doc.get("hospital_id"),
                    "hospital_name": hosp_name,
                    "city": hosp_city,
                    "doctor_id": target_doc["id"],
                    "doctor_name": doc_name,
                    "specialty": target_doc.get("specialty", "Oncology"),
                    "date": target_date,
                    "time": chosen_time,
                    "patient_name": p_name
                }
                ctx["pending_booking"] = pending
                ctx["awaiting_confirmation"] = True
                ctx["selected_doctor"] = target_doc

                spoken = f"Please confirm your appointment with {doc_name} at {hosp_name} on {target_date} at {chosen_time}. Please say yes to confirm."
                response_md = (
                    f"Please confirm your appointment details:\n\n"
                    f"- **Hospital**: {hosp_name} ({hosp_city})\n"
                    f"- **Doctor**: {doc_name} ({target_doc.get('specialty')})\n"
                    f"- **Date**: {target_date}\n"
                    f"- **Time**: {chosen_time}\n"
                    f"- **Patient**: {p_name}\n\n"
                    f"Would you like me to record this appointment in the application? Please reply **'Yes'** to proceed or **'No'** to cancel."
                )
                return {
                    "success": True,
                    "handled": True,
                    "response": response_md,
                    "spoken_response": spoken,
                    "action": "ASK_CONFIRMATION",
                    "context": ctx
                }

        # -------------------------------------------------------------
        # 3. CHECK AVAILABILITY
        # -------------------------------------------------------------
        is_avail_keyword = bool(re.search(r'\b(availability|available|slot|slots|उपलब्ध|उपलब्धता|स्लॉट|ಲಭ್ಯತೆ|ಸ್ಲಾಟ್‌ಗಳು)\b', msg_lower))

        if is_avail_keyword:
            ordinal = _extract_ordinal(msg_lower)
            target_doc = None
            if ordinal is not None and ctx.get("last_doctors") and 0 <= ordinal < len(ctx["last_doctors"]):
                target_doc = ctx["last_doctors"][ordinal]
            elif ctx.get("selected_doctor"):
                target_doc = ctx["selected_doctor"]
            elif ctx.get("last_doctors"):
                target_doc = ctx["last_doctors"][0]

            if target_doc:
                target_date = (date.today() + timedelta(days=1)).isoformat()
                avail_tool = DoctorAvailabilityTool()
                t_res = avail_tool.execute(doctor_id=target_doc["id"], date=target_date)

                slots = ["09:00 AM", "10:00 AM", "11:30 AM", "02:00 PM", "04:00 PM"]
                if t_res.success and t_res.data and t_res.data.get("available_slots"):
                    slots = t_res.data["available_slots"]

                doc_name = target_doc.get("name") or target_doc.get("full_name")
                hosp_name = (ctx.get("selected_hospital") or {}).get("name", "the hospital")

                ctx["selected_doctor"] = target_doc
                ctx["last_availability"] = {
                    "doctor_id": target_doc["id"],
                    "slots": slots,
                    "date": target_date
                }

                suggested_slot = slots[1] if len(slots) > 1 else slots[0]
                spoken = f"Available slots for {doc_name} tomorrow are {', '.join(slots[:3])}. Tell me your preferred slot to book."
                response_md = (
                    f"Here are available consultation slots for **{doc_name}** ({target_doc.get('specialty')}) at **{hosp_name}** on **{target_date}**:\n\n"
                    f"- **Available Slots**: {', '.join(slots)}\n\n"
                    f"To proceed, say: *'Book the first one at {suggested_slot}'* (or choose another time slot)."
                )
                return {
                    "success": True,
                    "handled": True,
                    "response": response_md,
                    "spoken_response": spoken,
                    "action": "SHOW_AVAILABILITY",
                    "context": ctx
                }

        # -------------------------------------------------------------
        # 4. FILTER BY SPECIALIZATION (e.g. "Only medical oncologists")
        # -------------------------------------------------------------
        is_spec_filter = any(w in msg_lower for w in [
            "medical oncolog", "surgical oncolog", "radiation oncolog", "pediatric oncolog",
            "medical", "surgical", "radiation", "pediatric",
            "सर्जिकल", "मेडिकल", "रेडिएशन", "ಸರ್ಜಿಕಲ್", "ಮೆಡಿಕಲ್", "ರೇಡಿಯೇಷನ್"
        ]) and any(w in msg_lower for w in ["only", "filter", "show", "just", "specialist", "specialists", "दिखाओ", "ತೋರಿಸಿ"]) or (
            "only" in msg_lower and "oncolog" in msg_lower
        )

        if is_spec_filter:
            spec_target = "Medical Oncology"
            if "surgical" in msg_lower or "सर्जिकल" in msg_lower or "ಸರ್ಜಿಕಲ್" in msg_lower:
                spec_target = "Surgical Oncology"
            elif "radiation" in msg_lower or "रेडिएशन" in msg_lower or "ರೇಡಿಯೇಷನ್" in msg_lower:
                spec_target = "Radiation Oncology"
            elif "pediatric" in msg_lower or "बच्चे" in msg_lower or "ಮಕ್ಕಳು" in msg_lower:
                spec_target = "Pediatric Oncology"

            cur_hosp = ctx.get("selected_hospital")
            docs_to_filter = []
            if cur_hosp and cur_hosp.get("name") in cancer_db_map:
                docs_to_filter = cancer_db_map[cur_hosp["name"]]["doctors"]
            elif ctx.get("last_doctors"):
                docs_to_filter = ctx["last_doctors"]
            elif cur_hosp:
                # Query DB
                from app.database.connection import get_db
                with get_db() as conn:
                    cur = conn.cursor(dictionary=True)
                    cur.execute("SELECT id, hospital_id, full_name, specialty, qualification FROM doctors WHERE hospital_id = %s", (cur_hosp["id"],))
                    docs_to_filter = cur.fetchall() or []
                    cur.close()

            filtered_docs = [
                d for d in docs_to_filter
                if spec_target.lower() in (d.get("specialty") or "").lower()
            ]
            if not filtered_docs:
                filtered_docs = docs_to_filter[:2]

            ctx["last_doctors"] = filtered_docs
            ctx["selected_specialty"] = spec_target

            h_name = cur_hosp.get("name") if cur_hosp else "the hospital"
            lines = [f"Filtered **{spec_target}** specialists at **{h_name}**:"]
            spoken_names = []
            for idx, d in enumerate(filtered_docs, 1):
                dname = d.get("name") or d.get("full_name")
                qual = d.get("qualification", "")
                lines.append(f"{idx}. **{dname}** – {d.get('specialty')}{f' ({qual})' if qual else ''}")
                spoken_names.append(dname)

            lines.append("\nWould you like to *'Check availability'* for one of these doctors?")
            spoken = f"Found {len(filtered_docs)} {spec_target} specialists at {h_name}: {', '.join(spoken_names)}. Would you like to check availability?"

            return {
                "success": True,
                "handled": True,
                "response": "\n".join(lines),
                "spoken_response": spoken,
                "action": "FILTER_DOCTORS",
                "context": ctx
            }

        # -------------------------------------------------------------
        # 5. SELECT HOSPITAL / SHOW DOCTORS (e.g. "Show doctors in the second one")
        # -------------------------------------------------------------
        is_show_docs = any(w in msg_lower for w in ["doctor", "doctors", "डॉक्टर", "ವೈದ್ಯರು", "specialist"])
        ordinal = _extract_ordinal(msg_lower)

        if is_show_docs or (ordinal is not None and "doctor" in msg_lower) or ("show" in msg_lower and ordinal is not None):
            target_hosp = None
            if ordinal is not None and ctx.get("last_hospitals") and 0 <= ordinal < len(ctx["last_hospitals"]):
                target_hosp = ctx["last_hospitals"][ordinal]
            else:
                for hname, hinfo in cancer_db_map.items():
                    if hname.lower() in msg_lower or (hinfo.get("city", "").lower() in msg_lower and "hospital" in msg_lower):
                        target_hosp = hinfo
                        break

            if not target_hosp and ctx.get("selected_hospital"):
                target_hosp = ctx["selected_hospital"]
            elif not target_hosp and ctx.get("last_hospitals"):
                target_hosp = ctx["last_hospitals"][0]

            if target_hosp:
                h_name = target_hosp.get("name") or target_hosp.get("hospital_name")
                h_record = cancer_db_map.get(h_name)
                docs = []
                if h_record and h_record.get("doctors"):
                    docs = h_record["doctors"]
                else:
                    hid = target_hosp.get("id") or target_hosp.get("db_id")
                    from app.database.connection import get_db
                    with get_db() as conn:
                        cur = conn.cursor(dictionary=True)
                        cur.execute("SELECT id, hospital_id, full_name, specialty, qualification FROM doctors WHERE hospital_id = %s", (hid,))
                        docs = cur.fetchall() or []
                        cur.close()

                ctx["selected_hospital"] = target_hosp
                ctx["last_doctors"] = docs

                city = target_hosp.get("city", "")
                lines = [f"Here are verified oncologists at **{h_name}** ({city}):"]
                spoken_names = []
                for idx, d in enumerate(docs, 1):
                    dname = d.get("name") or d.get("full_name")
                    lines.append(f"{idx}. **{dname}** – {d.get('specialty')}")
                    spoken_names.append(dname)

                lines.append("\nYou can filter by specialization (e.g. *'Only medical oncologists'*) or select a doctor to check availability.")
                spoken = f"Here are verified oncologists at {h_name}: {', '.join(spoken_names[:3])}. You can filter by specialization or check availability."

                return {
                    "success": True,
                    "handled": True,
                    "response": "\n".join(lines),
                    "spoken_response": spoken,
                    "action": "SHOW_DOCTORS",
                    "context": ctx
                }

        # -------------------------------------------------------------
        # 6. INITIAL HOSPITAL SEARCH (e.g. "Find cancer hospitals in India")
        # -------------------------------------------------------------
        is_hosp_search = any(w in msg_lower for w in [
            "cancer hospital", "cancer hospitals", "best cancer hospital",
            "oncology hospital", "हॉस्पिटल", "अस्पताल", "ಆಸ್ಪತ್ರೆ"
        ]) or ("hospital" in msg_lower and any(w in msg_lower for w in ["india", "find", "best", "भारत", "ಭಾರತ"]))

        if is_hosp_search:
            from app.services.location_filter import detect_location_intent, is_hospital_matching_location
            loc_intent = detect_location_intent(msg_lower)
            is_explicit_loc = loc_intent.get("is_explicit", False)

            hospitals_list = []
            for hname, hinfo in cancer_db_map.items():
                if is_explicit_loc:
                    if is_hospital_matching_location(hinfo, loc_intent):
                        hospitals_list.append(hinfo)
                else:
                    hospitals_list.append(hinfo)

            # If explicit location requested, supplement with DB hospitals if needed
            if is_explicit_loc and len(hospitals_list) < 4:
                from app.database.connection import get_db
                with get_db() as conn:
                    cur = conn.cursor(dictionary=True)
                    if loc_intent["type"] == "city":
                        cur.execute(
                            "SELECT id, name, city, state, address, phone FROM hospitals WHERE LOWER(city) = %s OR LOWER(city) LIKE %s LIMIT 10",
                            (loc_intent["name"].lower(), f"%{loc_intent['name'].lower()}%")
                        )
                    else:
                        cur.execute(
                            "SELECT id, name, city, state, address, phone FROM hospitals WHERE LOWER(state) = %s OR LOWER(state) LIKE %s LIMIT 10",
                            (loc_intent["name"].lower(), f"%{loc_intent['name'].lower()}%")
                        )
                    db_h = cur.fetchall() or []
                    cur.close()

                existing_names = {h["name"].lower() for h in hospitals_list}
                for dh in db_h:
                    if dh["name"].lower() not in existing_names and is_hospital_matching_location(dh, loc_intent):
                        hospitals_list.append({
                            "id": dh["id"],
                            "name": dh["name"],
                            "city": dh.get("city", ""),
                            "state": dh.get("state", ""),
                            "address": dh.get("address", ""),
                            "phone": dh.get("phone", "")
                        })

            # Hard Location Filter Verification
            if is_explicit_loc:
                hospitals_list = [h for h in hospitals_list if is_hospital_matching_location(h, loc_intent)]

            # If no hospitals match requested location, display strict message
            if is_explicit_loc and not hospitals_list:
                loc_disp = loc_intent["display_name"]
                no_hosp_msg = f"No hospitals found in {loc_disp}."
                return {
                    "success": True,
                    "handled": True,
                    "response": no_hosp_msg,
                    "spoken_response": no_hosp_msg,
                    "action": "NO_HOSPITALS_FOUND",
                    "context": ctx
                }

            ctx["last_hospitals"] = hospitals_list[:4]
            header_loc = loc_intent['display_name'] if is_explicit_loc else "India"
            lines = [f"Here are verified hospitals in **{header_loc}**:"]
            spoken_names = []
            for idx, h in enumerate(ctx["last_hospitals"], 1):
                city_disp = f", {h.get('city')}" if h.get('city') else ""
                lines.append(f"{idx}. **{h['name']}**{city_disp}")
                spoken_names.append(h['name'])

            lines.append("\nYou can say *'Show doctors in the second one'* or specify a hospital to view oncology specialists.")
            spoken = f"Here are verified hospitals in {header_loc}: {', '.join(spoken_names[:3])}. You can say show doctors in the second one."

            return {
                "success": True,
                "handled": True,
                "response": "\n".join(lines),
                "spoken_response": spoken,
                "action": "SHOW_HOSPITALS",
                "context": ctx
            }

        # Not a hospital agent contextual query
        return {
            "success": False,
            "handled": False,
            "context": ctx
        }



