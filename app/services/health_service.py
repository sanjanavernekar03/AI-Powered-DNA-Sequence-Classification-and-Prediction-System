import os
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DISCLAIMERS = {
    'en': "This information is provided for general educational and wellness purposes only and is not a medical diagnosis, prescription, or substitute for professional medical advice. If you describe an urgent situation, please seek immediate help from local emergency services or a qualified healthcare professional.",
    'kn': "ಈ ಮಾಹಿತಿಯು ಕೇವಲ ಸಾಮಾನ್ಯ ಕ್ಷೇಮ ಮತ್ತು ಶೈಕ್ಷಣಿಕ ಉದ್ದೇಶಗಳಿಗಾಗಿ ಮಾತ್ರ, ಇದು ವೈದ್ಯಕೀಯ ರೋಗನಿರ್ಣಯ ಅಥವಾ ವೃತ್ತಿಪರ ವೈದ್ಯರ ಸಲಹೆಗೆ ಬದಲಿಯಾಗಿಲ್ಲ. ತುರ್ತು ಪರಿಸ್ಥಿತಿ ಇದ್ದಲ್ಲಿ ಅರ್ಹ ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ.",
    'hi': "यह जानकारी केवल सामान्य स्वास्थ्य एवं शैक्षिक उद्देश्यों के लिए है और यह किसी चिकित्सीय निदान या डॉक्टर की सलाह का विकल्प नहीं है। किसी भी आपातकालीन स्थिति में तुरंत योग्य चिकित्सक से परामर्श लें।",
    'te': "ఈ సమాచారం సాధారణ ఆరోగ్యం మరియు విద్యా ప్రయోజనాల కోసం మాత్రమే, ఇది వైద్య నిర్ధారణ లేదా వృత్తిపరమైన వైద్యుని సలహాకు ప్రత్యామ్నాయం కాదు. అత్యవసర పరిస్థితుల్లో వెంటనే అర్హత కలిగిన వైద్యుడిని సంప్రదించండి.",
    'ta': "இந்த தகவல் பொதுவான நல்வாழ்வு மற்றும் கல்வி நோக்கங்களுக்காக மட்டுமே, இது மருத்துவ சிகிச்சை அல்லது நிபுணர் ஆலோசனைக்கு மாற்றாகாது. அவசர தேவைகளுக்கு தகுதிவாய்ந்த மருத்துவரை அணுகவும்."
}

HEALTH_DISCLAIMER = DISCLAIMERS['en']

_GUIDANCE_CACHE: Dict[str, Dict[str, Any]] = {}


def generate_health_guidance(problem: str, language: str = 'en') -> Dict[str, Any]:
    """
    Generates structured wellness guidance in English, Hindi, Kannada, Telugu, or Tamil.
    Uses local Ollama AI when responsive, falling back seamlessly to domain engine.
    Optimized for sub-second response with in-memory caching for repeated queries.
    """
    target_lang = language.lower() if language in {'en', 'hi', 'kn', 'te', 'ta'} else 'en'
    problem_clean = problem.strip()
    if not problem_clean:
        return _get_default_guidance(target_lang)

    cache_key = f"{target_lang}:{problem_clean.lower()}"
    if cache_key in _GUIDANCE_CACHE:
        logger.info("Serving health guidance from cache for %s", cache_key)
        return _GUIDANCE_CACHE[cache_key]

    # For Indic languages (kn, hi, te, ta), the multilingual domain engine provides
    # instantaneous (sub-second), 100% native script responses without CPU token generation timeouts.
    # For English, attempt fast Ollama with 5-second timeout, falling back seamlessly.
    if target_lang == 'en':
        try:
            guidance = _call_ollama_health_guidance(problem_clean, target_lang)
            if guidance and isinstance(guidance, dict) and guidance.get("healthy_foods"):
                guidance["medical_disclaimer"] = DISCLAIMERS.get(target_lang, DISCLAIMERS['en'])
                _GUIDANCE_CACHE[cache_key] = guidance
                return guidance
        except Exception as e:
            logger.info("Local Ollama English generation bypassed (%s), using domain engine", e)

    # Domain Knowledge Multilingual Health Engine (Instant sub-second response)
    fallback_guidance = _generate_structured_domain_guidance(problem_clean, target_lang)
    _GUIDANCE_CACHE[cache_key] = fallback_guidance
    return fallback_guidance


def _call_ollama_health_guidance(problem: str, language: str) -> Optional[Dict[str, Any]]:
    lang_map = {
        'en': ('English', 'English'),
        'hi': ('Hindi', 'Devanagari script (हिन्दी)'),
        'kn': ('Kannada', 'Kannada script (ಕನ್ನಡ)'),
        'te': ('Telugu', 'Telugu script (తెలుగు)'),
        'ta': ('Tamil', 'Tamil script (தமிழ்)')
    }
    full_lang, script_name = lang_map.get(language, ('English', 'English'))

    system_prompt = f"""You are an AI Wellness Advisor. Provide concise wellness & diet guidance strictly in {full_lang} using {script_name}.
Output valid JSON matching this exact structure:
{{
  "title": "Wellness Guidance Summary in {full_lang}",
  "general_wellness": "1-2 brief sentences in {full_lang}",
  "healthy_foods": ["Food 1", "Food 2", "Food 3"],
  "diet_considerations": ["Diet tip 1", "Diet tip 2"],
  "exercise_suggestions": ["Exercise 1", "Exercise 2"],
  "lifestyle_recommendations": ["Lifestyle tip 1", "Lifestyle tip 2"]
}}
Do NOT diagnose or prescribe medicines. Keep guidance brief, practical, and actionable. Respond strictly in {full_lang}."""

    url = "http://127.0.0.1:11434/api/chat"
    payload = {
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"User Health & Diet Request: {problem}"}
        ],
        "format": "json",
        "stream": False,
        "keep_alive": "24h",
        "options": {
            "temperature": 0.2,
            "num_predict": 300
        }
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        res_data = json.loads(resp.read().decode('utf-8'))
        text = res_data.get("message", {}).get("content", "")
        if not text:
            return None
        text_clean = text.strip()
        if text_clean.startswith("```"):
            lines = text_clean.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text_clean = "\n".join(lines).strip()
        try:
            return json.loads(text_clean)
        except json.JSONDecodeError:
            start = text_clean.find("{")
            end = text_clean.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text_clean[start:end+1])
                except Exception:
                    pass
            raise


# ---------------------------------------------------------------------------
# INTELLIGENT MULTILINGUAL DOMAIN GUIDANCE ENGINE
# ---------------------------------------------------------------------------

def _detect_health_category(problem: str) -> str:
    p = problem.lower()
    
    # Fatigue / Energy
    if any(k in p for k in ["tired", "fatigue", "energy", "exhausted", "weakness", "lethargic", "ಆಯಾಸ", "ಸುಸ್ತು", "ದಣಿವು", "ಶಕ್ತಿ", "थकान", "कमजोरी", "ऊर्जा", "అలసట", "నీరసం", "శక్తి", "சோர்வு", "பலவீனம்", "ஆற்றல்"]):
        return "fatigue"
    
    # Diet / Nutrition / Weight
    if any(k in p for k in ["diet", "food", "weight", "loss", "gain", "fat", "nutrition", "eat", "meal", "protein", "ತೂಕ", "ಆಹಾರ", "ಡಯಟ್", "ಪೋಷಣೆ", "ಊಟ", "वजन", "मोटापा", "आहार", "डाइट", "पोषण", "భోజనం", "ఆహారం", "బరువు", "உணவு", "உணவுமுறை", "எடை"]):
        return "diet"

    # Fitness / Exercise / Strength
    if any(k in p for k in ["fit", "fitness", "exercise", "workout", "gym", "muscle", "strength", "cardio", "run", "walk", "ವ್ಯಾಯಾಮ", "ದೇಹದಂಡನೆ", "ಫಿಟ್ನೆಸ್", "ಬಲ", "ಕಸರತ್ತು", "व्यायाम", "कसरत", "फिटनेस", "ताकत", "వ్యాయామం", "కసరత్తు", "బలం", "உடற்பயிற்சி", "வலிமை"]):
        return "fitness"

    # Sleep / Stress / Mental Wellness
    if any(k in p for k in ["sleep", "insomnia", "stress", "anxiety", "depression", "tension", "relax", "headache", "mind", "ತಲೆನೋವು", "ನಿದ್ರೆ", "ಒತ್ತಡ", "ಆತಂಕ", "ಚಿಂತೆ", "ಶಾಂತಿ", "नींद", "अनिद्रा", "तनाव", "चिंता", "सिरदर्द", "నిద్ర", "ఒత్తిడి", "ఆందోళన", "తలనెప్పి", "தூக்கம்", "மன அழுத்தம்", "பதட்டம்", "தலைவலி"]):
        return "sleep_stress"

    # Digestion / Gut / Acidity
    if any(k in p for k in ["stomach", "digest", "acidity", "gas", "bloat", "constipation", "gut", "bowel", "ಹೊಟ್ಟೆ", "ಜೀರ್ಣ", "ಅಸಿಡಿಟಿ", "ಗ್ಯಾಸ್", "ಮಲಬದ್ಧತೆ", "ಬೊಜ್ಜು", "पेट", "पाचन", "एसिडिटी", "गैस", "कब्ज", "జీర్ణం", "జీర్ణక్రియ", "కడుపు", "ఎసిడిటీ", "വയிறு", "செரிமானம்", "அசிடிட்டி", "மலச்சிக்கல்"]):
        return "digestion"

    # Heart / Blood Pressure / Cardio
    if any(k in p for k in ["bp", "blood pressure", "heart", "hypertension", "cholesterol", "pulse", "ರಕ್ತದೊತ್ತಡ", "ಹೃದಯ", "ಕೊಲೆಸ್ಟ್ರಾಲ್", "ರಕ್ತದ ಒತ್ತಡ", "रक्तचाप", "बीपी", "हृदय", "कोलेस्ट्रॉल", "రక్తపోటు", "గుండె", "కొలెస్ట్రాల్", "இரத்த அழுத்தம்", "இதயம்"]):
        return "cardio"

    return "general"


def _generate_structured_domain_guidance(problem: str, lang: str) -> Dict[str, Any]:
    category = _detect_health_category(problem)
    disclaimer = DISCLAIMERS.get(lang, DISCLAIMERS['en'])

    # ---------------- Kannada (kn) ----------------
    if lang == 'kn':
        if category == "fatigue":
            return {
                "title": f"'{problem}' ಗಾಗಿ ಆಯಾಸ ನಿವಾರಣೆ ಮತ್ತು ಶಕ್ತಿ ವರ್ಧನೆಯ ಮಾರ್ಗದರ್ಶನ",
                "general_wellness": "ಆಗಾಗ ಕಾಡುವ ಆಯಾಸವನ್ನು ಸಮತೋಲಿತ ಪೋಷಕಾಂಶ, ಸಾಕಷ್ಟು ನೀರು ಕುಡಿಯುವುದು ಮತ್ತು ನಿಯಮಿತ ನಿದ್ರೆಯ ಮೂಲಕ ಪರಿಣಾಮಕಾರಿಯಾಗಿ ನಿಯಂತ್ರಿಸಬಹುದು.",
                "healthy_foods": [
                    "ಕಬ್ಬಿಣಾಂಶ ಭರಿತ ಹಸಿರು ಸೊಪ್ಪುಗಳು (ಪಾಲಕ್, ಮೆಂತ್ಯ)",
                    "ತಾಜಾ ಹಣ್ಣುಗಳು (ಬಾಳೆಹಣ್ಣು, ದಾಳಿಂಬೆ, ಸೇಬು)",
                    "ಅಣುಬೀಜಗಳು ಮತ್ತು ಒಣ ಹಣ್ಣುಗಳು (ಬಾದಾಮಿ, ವಾಲ್ನಟ್)",
                    "ಕಾಳುಗಳು ಮತ್ತು ಮೊಳಕೆ ಬರಿಸಿದ ಧಾನ್ಯಗಳು"
                ],
                "diet_considerations": [
                    "ದಿನಕ್ಕೆ ಕನಿಷ್ಠ 2.5 ರಿಂದ 3 ಲೀಟರ್ ನೀರು ಕುಡಿದು ದೇಹವನ್ನು ಹೈಡ್ರೇಟ್ ಆಗಿರಿಸಿ",
                    "ಹೆಚ್ಚು ಸಂಸ್ಕರಿಸಿದ ಸಕ್ಕರೆ ಮತ್ತು ಜಂಕ್ ಫುಡ್ ಸೇವನೆಯನ್ನು ಕಡಿಮೆ ಮಾಡಿ",
                    "ಪ್ರತಿ ಊಟದಲ್ಲೂ ಉತ್ತಮ ಪ್ರೋಟೀನ್ ಮತ್ತು ನಾರಿನಂಶ ಇರಲಿ"
                ],
                "exercise_suggestions": [
                    "ದಿನಕ್ಕೆ 30 ನಿಮಿಷಗಳ ಕಾಲ ಚುರುಕಾದ ನಡಿಗೆ (Brisk Walking)",
                    "ದಣಿವಾರಿಸುವ ಪ್ರಾಣಾಯಾಮ ಮತ್ತು ಅನುಲೋಮ-ವಿಲೋಮ",
                    "ಬೆಳಗಿನ ಜಾವ ಸೂರ್ಯನ ಬಿಸಿಲಿನಲ್ಲಿ ಲಘು ವ್ಯಾಯಾಮ"
                ],
                "lifestyle_recommendations": [
                    "ರಾತ್ರಿ 7 ರಿಂದ 8 ಗಂಟೆಗಳ ಕಾಲ ಅಡೆತಡೆಯಿಲ್ಲದ ನಿದ್ರೆ ಮಾಡಿ",
                    "ಕೆಲಸದ ನಡುವೆ ಸಣ್ಣ ವಿರಾಮಗಳನ್ನು ತೆಗೆದುಕೊಂಡು ವಿಶ್ರಾಂತಿ ಪಡೆಯಿರಿ",
                    "ಮಲಗುವ ಮುನ್ನ ಮೊಬೈಲ್ ಹಾಗೂ ಪರದೆಗಳ ಬಳಕೆಯನ್ನು ತಪ್ಪಿಸಿ"
                ],
                "medical_disclaimer": disclaimer
            }
        elif category == "diet":
            return {
                "title": f"'{problem}' ಗಾಗಿ ಪೌಷ್ಟಿಕ ಆಹಾರ ಹಾಗೂ ತೂಕ ನಿರ್ವಹಣೆ ಮಾರ್ಗದರ್ಶನ",
                "general_wellness": "ಸಮತೋಲಿತ ಪೋಷಕಾಂಶಯುಕ್ತ ಆಹಾರ ಹಾಗೂ ನಿಯಮಿತ ಊಟದ ಸಮಯ ಆರೋಗ್ಯಕರ ತೂಕ ಮತ್ತು ಉತ್ತಮ ಚಯಾಪಚಯ ಕ್ರಿಯೆಗೆ ಅಡಿಪಾಯವಾಗಿದೆ.",
                "healthy_foods": [
                    "ರಾಗಿ, ಸಿರಿಧಾನ್ಯಗಳು ಮತ್ತು ಕೆಂಪಕ್ಕಿ",
                    "ಹಸಿ ತರಕಾರಿ ಸಲಾಡ್‌ಗಳು ಮತ್ತು ಮೊಳಕೆ ಕಾಳುಗಳು",
                    "ಪ್ರೋಟೀನ್‌ಯುಕ್ತ ದಾಲ್, ಹೆಸರುಕಾಳು ಮತ್ತು ಪನೀರ್/ಮೊಟ್ಟೆ",
                    "ಮಜ್ಜಿಗೆ, ಎಳನೀರು ಮತ್ತು ನಿಂಬೆ ನೀರು"
                ],
                "diet_considerations": [
                    "ಎಣ್ಣೆ ಮತ್ತು ಕರಿದ ಪದಾರ್ಥಗಳನ್ನು ಆದಷ್ಟು ಕಡಿಮೆ ಮಾಡಿ",
                    "ಊಟವನ್ನು ನಿಧಾನವಾಗಿ ಜಗಿದು ಸೇವಿಸಿ ಹಾಗೂ ಅತಿಯಾಗಿ ತಿನ್ನಬೇಡಿ",
                    "ರಾತ್ರಿ ಊಟವನ್ನು ಮಲಗುವ ಕನಿಷ್ಠ 2 ಗಂಟೆಗಳ ಮೊದಲು ಮುಗಿಸಿ"
                ],
                "exercise_suggestions": [
                    "ದಿನವೂ 35 ನಿಮಿಷಗಳ ಕಾರ್ಡಿಯೋ ಅಥವಾ ಈಜು",
                    "ದೇಹದ ತೂಕದ ಸರಳ ವ್ಯಾಯಾಮಗಳು (Squats, Lunges)",
                    "ಊಟದ ನಂತರ 15 ನಿಮಿಷಗಳ ಲಘು ನಡಿಗೆ"
                ],
                "lifestyle_recommendations": [
                    "ದೈನಂದಿನ ನೀರಿನ ಸೇವನೆಯನ್ನು ಸರಿಯಾಗಿ ಕಾಪಾಡಿಕೊಳ್ಳಿ",
                    "ಊಟದ ನಿರ್ದಿಷ್ಟ ಸಮಯವನ್ನು ಪ್ರತಿದಿನ ಪಾಲಿಸಿ",
                    "ಮಾನಸಿಕ ಒತ್ತಡದ ಸಮಯದಲ್ಲಿ ಅತಿಯಾಗಿ ತಿನ್ನುವುದನ್ನು ನಿಯಂತ್ರಿಸಿ"
                ],
                "medical_disclaimer": disclaimer
            }
        elif category == "fitness":
            return {
                "title": f"'{problem}' ಗಾಗಿ ದೈಹಿಕ ಸಾಮರ್ಥ್ಯ ಮತ್ತು ಫಿಟ್‌ನೆಸ್ ಮಾರ್ಗದರ್ಶನ",
                "general_wellness": "ದೈನಂದಿನ ವ್ಯಾಯಾಮ, ಸರಿಯಾದ ವಾರ್ಮ್-ಅಪ್ ಮತ್ತು ಪೋಷಕಾಂಶಯುಕ್ತ ಊಟವು ಸ್ನಾಯುಗಳ ಬಲ ಮತ್ತು ಶಕ್ತಿಯನ್ನು ಸುಧಾರಿಸುತ್ತದೆ.",
                "healthy_foods": [
                    "ಹೆಚ್ಚಿನ ಪ್ರೋಟೀನ್ ಇರುವ ಮೊಳಕೆ ಕಾಳುಗಳು, ಸೋಯಾ, ಪನೀರ್",
                    "ಬಾಳೆಹಣ್ಣು ಮತ್ತು ಓಟ್ಸ್ ವ್ಯಾಯಾಮಕ್ಕೆ ಮುನ್ನ",
                    "ಮೊಟ್ಟೆಯ ಬಿಳಿಭಾಗ ಅಥವಾ ಬೇಳೆಕಾಳುಗಳು",
                    "ಹೈಡ್ರೇಶನ್‌ಗಾಗಿ ಎಳನೀರು ಮತ್ತು ಸಿಟ್ರಸ್ ಹಣ್ಣುಗಳು"
                ],
                "diet_considerations": [
                    "ವ್ಯಾಯಾಮದ ನಂತರ 45 ನಿಮಿಷಗಳಲ್ಲಿ ಪ್ರೋಟೀನ್ ಸೇವಿಸಿ",
                    "ಸಾಕಷ್ಟು ನೀರು ಕುಡಿದು ಸ್ನಾಯು ಸೆಳೆತ ತಡೆಯಿರಿ",
                    "ಸಕ್ಕರೆ ಪಾನೀಯಗಳ ಬದಲು ನೈಸರ್ಗಿಕ ಹಣ್ಣಿನ ರಸ ಬಳಸಿ"
                ],
                "exercise_suggestions": [
                    "ವಾರದಲ್ಲಿ 4-5 ದಿನ 30-40 ನಿಮಿಷಗಳ ಸಾಮರ್ಥ್ಯ ತರಬೇತಿ",
                    "ಸ್ನಾಯುಗಳ ಸಡಿಲತೆಗೆ ಸ್ಟ್ರೆಚಿಂಗ್ ಮತ್ತು ಸೂರ್ಯ ನಮಸ್ಕಾರ",
                    "ದಿನವೂ 8,000 ರಿಂದ 10,000 ಹೆಜ್ಜೆಗಳನ್ನು ನಡೆಯಿರಿ"
                ],
                "lifestyle_recommendations": [
                    "ವ್ಯಾಯಾಮದ ನಂತರ ಸ್ನಾಯುಗಳ ಚೇತರಿಕೆಗೆ ಉತ್ತಮ ನಿದ್ರೆ ಪಡೆಯಿರಿ",
                    "ದೀರ್ಘಕಾಲ ಒಂದೇ ಕಡೆ ಕೂರದೆ ಆಗಾಗ ಎದ್ದು ಓಡಾಡಿ",
                    "ವಾರದಲ್ಲಿ ಒಂದು ದಿನ ದೇಹಕ್ಕೆ ಸಂಪೂರ್ಣ ವಿಶ್ರಾಂತಿ ನೀಡಿ"
                ],
                "medical_disclaimer": disclaimer
            }
        elif category == "sleep_stress":
            return {
                "title": f"'{problem}' ಗಾಗಿ ಮಾನಸಿಕ ಶಾಂತಿ ಮತ್ತು ಗಾಢ ನಿದ್ರೆಯ ಮಾರ್ಗದರ್ಶನ",
                "general_wellness": "ಒತ್ತಡ ನಿರ್ವಹಣೆ ಮತ್ತು ಸರಿಯಾದ ನಿದ್ರೆಯ ಅಭ್ಯಾಸಗಳು ಮಾನಸಿಕ ಉತ್ಸಾಹ ಮತ್ತು ಶಕ್ತಿಯನ್ನು ಪುನರುಜ್ಜೀವನಗೊಳಿಸುತ್ತವೆ.",
                "healthy_foods": [
                    "ರಾತ್ರಿ ಮಲಗುವ ಮುನ್ನ ಬಿಸಿ ಹಾಲು ಅಥವಾ ಜೀರಿಗೆ ಕಷಾಯ",
                    "ಬಾದಾಮಿ, ವಾಲ್ನಟ್ ಮತ್ತು ಕುಂಬಳಕಾಯಿ ಬೀಜಗಳು",
                    "ಮೆಗ್ನೀಸಿಯಮ್ ಭರಿತ ಪಾಲಕ್ ಮತ್ತು ಬಾಳೆಹಣ್ಣು",
                    "ಹರ್ಬಲ್ ಚಹಾ ಮತ್ತು ಶಾಂತಿಯುತ ಪಾನೀಯಗಳು"
                ],
                "diet_considerations": [
                    "ಸಂಜೆ 6 ಗಂಟೆಯ ನಂತರ ಕಾಫಿ, ಟೀ ಸೇವಿಸಬೇಡಿ",
                    "ರಾತ್ರಿ ಅತಿ ಖಾರ ಅಥವಾ ಭಾರವಾದ ಊಟವನ್ನು ತಪ್ಪಿಸಿ",
                    "ಮಲಗುವ ಮುನ್ನ ಹೆಚ್ಚು ನೀರು ಕುಡಿಯುವುದನ್ನು ಕಡಿಮೆ ಮಾಡಿ"
                ],
                "exercise_suggestions": [
                    "ಯೋಗ ನಿದ್ರಾ ಮತ್ತು ಶಾಂತಿಯುತ ಧ್ಯಾನ (Meditation)",
                    "ದಿನಕ್ಕೆ 15 ನಿಮಿಷಗಳ ಆಳವಾದ ಉಸಿರಾಟದ ಪ್ರಾಣಾಯಾಮ",
                    "ಸಂಜೆ ಸಮಯದಲ್ಲಿ ಲಘು ಮುಕ್ತ ನಡಿಗೆ"
                ],
                "lifestyle_recommendations": [
                    "ಪ್ರತಿದಿನ ಒಂದೇ ಸಮಯಕ್ಕೆ ಮಲಗಿ ಮತ್ತು ಏಳಿ",
                    "ಮಲಗುವ ಕೋಣೆಯನ್ನು ಕತ್ತಲೆ ಮತ್ತು ತಂಪಾಗಿ ಇರಿಸಿ",
                    "ಮಲಗುವ 1 ಗಂಟೆ ಮುನ್ನ ಸ್ಕ್ರೀನ್/ಫೋನ್ ಬಳಸಬೇಡಿ"
                ],
                "medical_disclaimer": disclaimer
            }
        else: # digestion, cardio, general
            return {
                "title": f"'{problem}' ಗಾಗಿ ಸಮಗ್ರ ಆರೋಗ್ಯ ಮತ್ತು ಕ್ಷೇಮ ಮಾರ್ಗದರ್ಶನ",
                "general_wellness": "ಸಮತೋಲಿತ ಪೌಷ್ಟಿಕ ಆಹಾರ, ನಿರಂತರ ಚಟುವಟಿಕೆ ಮತ್ತು ಸಕಾರಾತ್ಮಕ ಜೀವನಶೈಲಿಯು ಒಟ್ಟಾರೆ ಕ್ಷೇಮವನ್ನು ರಕ್ಷಿಸುತ್ತದೆ.",
                "healthy_foods": [
                    "ಹಸಿರು ಸೊಪ್ಪು ತರಕಾರಿಗಳು ಮತ್ತು ಸಲಾಡ್‌ಗಳು",
                    "ತಾಜಾ ಹಣ್ಣುಗಳು (ಸೇಬು, ಕಿತ್ತಳೆ, ದಾಳಿಂಬೆ)",
                    "ಮೊಳಕೆ ಕಾಳುಗಳು ಮತ್ತು ಸುಲಭವಾಗಿ ಜೀರ್ಣವಾಗುವ ಆಹಾರ",
                    "ಬಾದಾಮಿ, ವಾಲ್ನಟ್ ಮತ್ತು ಒಣದ್ರಾಕ್ಷಿ"
                ],
                "diet_considerations": [
                    "ದಿನಕ್ಕೆ 2.5 ರಿಂದ 3 ಲೀಟರ್ ನೀರು ಕುಡಿಯಿರಿ",
                    "ಸಂಸ್ಕರಿಸಿದ ಎಣ್ಣೆ ಹಾಗೂ ಸಕ್ಕರೆಯನ್ನು ಮಿತಗೊಳಿಸಿ",
                    "ಸಮಯಕ್ಕೆ ಸರಿಯಾಗಿ ಪೌಷ್ಟಿಕ ಆಹಾರ ಸೇವಿಸಿ"
                ],
                "exercise_suggestions": [
                    "ದಿನವೂ 30 ನಿಮಿಷಗಳ ವೇಗದ ನಡಿಗೆ",
                    "ಯೋಗ, ಪ್ರಾಣಾಯಾಮ ಮತ್ತು ಸ್ಟ್ರೆಚಿಂಗ್",
                    "ದೈನಂದಿನ ಮೆಟ್ಟಿಲು ಹತ್ತುವ ಸಣ್ಣ ಅಭ್ಯಾಸಗಳು"
                ],
                "lifestyle_recommendations": [
                    "ದಿನಕ್ಕೆ 7-8 ಗಂಟೆಗಳ ಕಾಲ ಗಾಢ ನಿದ್ರೆ ಮಾಡಿ",
                    "ಮಾನಸಿಕ ಒತ್ತಡವನ್ನು ಧ್ಯಾನದ ಮೂಲಕ ಕಡಿಮೆ ಮಾಡಿಕೊಳ್ಳಿ",
                    "ನಿಯಮಿತವಾಗಿ ಆರೋಗ್ಯ ತಪಾಸಣೆ ಮಾಡಿಸಿಕೊಳ್ಳಿ"
                ],
                "medical_disclaimer": disclaimer
            }

    # ---------------- Hindi (hi) ----------------
    elif lang == 'hi':
        if category == "fatigue":
            return {
                "title": f"'{problem}' के लिए ऊर्जा संवर्धन एवं स्वास्थ्य मार्गदर्शन",
                "general_wellness": "लगातार थकान को संतुलित पोषण, पर्याप्त जलयोजन और नियमित नींद के माध्यम से आसानी से नियंत्रित किया जा सकता है।",
                "healthy_foods": [
                    "आयरन युक्त हरी पत्तेदार सब्जियां (पालक, मेथी)",
                    "ताजे मौसमी फल (केला, अनार, सेब)",
                    "अंकुरित अनाज और दालें",
                    "बादाम, अखरोट और कद्दू के बीज"
                ],
                "diet_considerations": [
                    "प्रतिदिन कम से कम 2.5 से 3 लीटर पानी पिएं",
                    "अत्यधिक चीनी और फास्ट फूड से पूरी तरह बचें",
                    "हर भोजन में पर्याप्त प्रोटीन और फाइबर शामिल करें"
                ],
                "exercise_suggestions": [
                    "रोजाना 30 मिनट तेज चाल (Brisk Walk)",
                    "अनुलोम-विलोम और भ्रामरी प्राणायाम",
                    "सुबह धूप में हल्का योगाभ्यास"
                ],
                "lifestyle_recommendations": [
                    "रात में 7-8 घंटे की निर्बाध गुणवत्तापूर्ण नींद लें",
                    "काम के बीच छोटे-छोटे ब्रेक लेकर आराम करें",
                    "सोने से 1 घंटा पहले स्क्रीन का प्रयोग बंद करें"
                ],
                "medical_disclaimer": disclaimer
            }
        elif category == "diet":
            return {
                "title": f"'{problem}' के लिए संतुलित आहार एवं पोषण योजना",
                "general_wellness": "सही पोषण और नियमित खान-पान स्वस्थ वजन और बेहतर मेटाबॉलिज्म की मजबूत नींव है।",
                "healthy_foods": [
                    "साबुत अनाज (दलिया, ओट्स, बाजरा, ब्राउन राइस)",
                    "ताजा सलाद और हरी सब्जियां",
                    "दालें, राजमा, चना और पनीर",
                    "छाछ, नारियल पानी और नींबू पानी"
                ],
                "diet_considerations": [
                    "तले-भुने और जंक फूड का सेवन सीमित करें",
                    "भोजन को अच्छी तरह चबाकर और धीरे-धीरे खाएं",
                    "सोने से कम से कम 2 घंटे पहले रात्रिभोज पूरा करें"
                ],
                "exercise_suggestions": [
                    "सप्ताह में 4-5 दिन 35 मिनट कार्डियो या एरोबिक्स",
                    "हल्के वजन का स्ट्रेंथ ट्रेनिंग अभ्यास",
                    "भोजन के बाद 15 मिनट टहलें"
                ],
                "lifestyle_recommendations": [
                    "हाइड्रेशन स्तर को हमेशा बनाए रखें",
                    "भोजन का निश्चित समय निर्धारित करें",
                    "तनाव में अधिक खाने की आदत पर नियंत्रण रखें"
                ],
                "medical_disclaimer": disclaimer
            }
        else: # fitness, sleep, digestion, cardio, general
            return {
                "title": f"'{problem}' के लिए स्वास्थ्य एवं पोषण मार्गदर्शन",
                "general_wellness": "पर्याप्त पोषण, नियमित शारीरिक गतिविधि और तनाव प्रबंधन समग्र ऊर्जा और स्वास्थ्य के लिए आवश्यक हैं।",
                "healthy_foods": [
                    "हरी पत्तेदार सब्जियां और ताजे फल",
                    "अंकुरित अनाज, दालें और सूखे मेवे",
                    "दही, छाछ और प्रोबायोटिक खाद्य पदार्थ",
                    "एंटीऑक्सीडेंट युक्त बीज (अलसी, चिया सीड)"
                ],
                "diet_considerations": [
                    "प्रतिदिन 8-10 गिलास पानी पीकर हाइड्रेटेड रहें",
                    "अधिक चीनी और प्रसंस्कृत खाद्य पदार्थों से बचें",
                    "संतुलित आहार में प्रोटीन और फाइबर शामिल करें"
                ],
                "exercise_suggestions": [
                    "रोजाना 30 मिनट तेज चाल या कार्डियो",
                    "हल्का योगाभ्यास, सूर्य नमस्कार और प्राणायाम",
                    "मांसपेशियों के लिए बेसिक स्ट्रेचिंग"
                ],
                "lifestyle_recommendations": [
                    "प्रतिदिन 7-8 घंटे की गुणवत्तापूर्ण नींद लें",
                    "नियमित समय पर भोजन करें",
                    "स्क्रीन टाइम घटाएं और तनाव मुक्त रहें"
                ],
                "medical_disclaimer": disclaimer
            }

    # ---------------- Telugu (te) ----------------
    elif lang == 'te':
        return {
            "title": f"'{problem}' కోసం ఆరోగ్యం మరియు జీవనశైలి మార్గదర్శకత్వం",
            "general_wellness": "మంచి పోషకాహారం, తగినంత నీరు త్రాగడం, క్రమబద్ధమైన వ్యాయామం మీ శక్తిని మరియు ఆరోగ్యాన్ని కాపాడతాయి.",
            "healthy_foods": [
                "ఆకుకూరలు (పాలకూర, మెంతి) మరియు తాజా కూరగాయలు",
                "తాజా పండ్లు (యాపిల్స్, అరటిపండ్లు, దానిమ్మ)",
                "పప్పు ధాన్యాలు మరియు మొలకలు",
                "బాదం, అక్రోట్లు మరియు ఎండు ఫలాలు"
            ],
            "diet_considerations": [
                "రోజుకు కనీసం 2.5 నుండి 3 లీటర్ల నీరు త్రాగండి",
                "ప్రాసెస్ చేసిన ఆహారాలు మరియు చక్కెరను తగ్గించండి",
                "ప్రోటీన్ మరియు పీచు పదార్థాలు ఉన్న ఆహారాన్ని తీసుకోండి"
            ],
            "exercise_suggestions": [
                "రోజువారీ 30 నిమిషాల వేగవంతమైన నడక (Brisk Walk)",
                "యోగా మరియు ప్రాణాయామం",
                "రోజూ తేలికపాటి వ్యాయామాలు"
            ],
            "lifestyle_recommendations": [
                "రోజుకు 7-8 గంటల నాణ్యమైన నిద్ర పొందండి",
                "సమయానికి ఆహారం తీసుకోండి",
                "మానసిక ఒత్తిడిని తగ్గించుకోవడానికి విశ్రాంతి తీసుకోండి"
            ],
            "medical_disclaimer": disclaimer
        }

    # ---------------- Tamil (ta) ----------------
    elif lang == 'ta':
        return {
            "title": f"'{problem}' க்கான சுகாதாரம் மற்றும் வாழ்க்கை முறை வழிகாட்டுதல்",
            "general_wellness": "நல்ல ஊட்டச்சத்து உணவு, போதுமான நீர் அருந்துதல், வழக்கமான உடற்பயிற்சி உங்கள் ஆற்றலை அதிகரிக்க உதவும்.",
            "healthy_foods": [
                "பச்சை காய்கறிகள் மற்றும் கீரைகள் (முருங்கை, பாலக்)",
                "புதிய பழங்கள் (வாழைப்பழம், ஆப்பிள், மாதுளை)",
                "பருப்பு வகைகள் மற்றும் முளைகட்டிய தானியங்கள்",
                "பாதாம் மற்றும் உலர்ந்த பழங்கள்"
            ],
            "diet_considerations": [
                "நாளைக்கு 2.5 முதல் 3 லிட்டர் தண்ணீர் குடிக்கவும்",
                "பதப்படுத்தப்பட்ட உணவுகள் மற்றும் சர்க்கரையை குறைக்கவும்",
                "புரதம் மற்றும் நார்ச்சத்து நிறைந்த உணவை உட்கொள்ளுங்கள்"
            ],
            "exercise_suggestions": [
                "தினசரி 30 நிமிடங்கள் விறுவிறுப்பான நடைபயிற்சி",
                "யோகா மற்றும் பிராணாயாமம்",
                "எளிய உடற்பயிற்சிகள்"
            ],
            "lifestyle_recommendations": [
                "நாளைக்கு 7-8 மணிநேரம் அமைதியான தூக்கம் பெறவும்",
                "நேரத்திற்கு உணவு உண்ணுங்கள்",
                "மன அழுத்தத்தைக் குறைத்து ஓய்வெடுக்கவும்"
            ],
            "medical_disclaimer": disclaimer
        }

    # ---------------- English (en) Default ----------------
    else:
        if category == "fatigue":
            return {
                "title": f"Energy Boosting & Fatigue Relief Guidance for '{problem}'",
                "general_wellness": "Combating persistent fatigue requires a foundation of micronutrient replenishment, adequate hydration, and restorative sleep cycles.",
                "healthy_foods": [
                    "Iron-rich leafy greens (spinach, kale)",
                    "Complex carbs for sustained stamina (oats, quinoa)",
                    "Antioxidant berries & potassium-rich bananas",
                    "Raw almonds, walnuts & pumpkin seeds"
                ],
                "diet_considerations": [
                    "Maintain 2.5 - 3 liters of water intake daily to prevent dehydration fatigue",
                    "Limit refined sugars and energy drinks that cause steep energy crashes",
                    "Incorporate protein and healthy fats into every meal"
                ],
                "exercise_suggestions": [
                    "30 minutes of brisk walking in natural morning light",
                    "Gentle yoga stretches to stimulate circulation and lymphatic flow",
                    "Deep diaphragmatic breathing exercises"
                ],
                "lifestyle_recommendations": [
                    "Aim for 7 to 8 hours of uninterrupted, restful sleep each night",
                    "Take short 5-minute movement breaks during prolonged sitting",
                    "Limit electronic screen exposure at least 45 minutes before bedtime"
                ],
                "medical_disclaimer": disclaimer
            }
        elif category == "diet":
            return {
                "title": f"Nutritional Balance & Healthy Diet Plan for '{problem}'",
                "general_wellness": "Sustainable wellness relies on nutrient-dense whole foods, mindful eating, and stabilizing metabolic glucose levels.",
                "healthy_foods": [
                    "Lean proteins (lentils, chickpeas, tofu, paneer, eggs)",
                    "Fiber-rich colorful vegetables and crisp salads",
                    "Whole grains (brown rice, millets, oats)",
                    "Healthy hydration (buttermilk, coconut water, lemon water)"
                ],
                "diet_considerations": [
                    "Eliminate ultra-processed snacks and trans-fat cooking oils",
                    "Chew slowly and practice mindful portion control",
                    "Finish dinner at least 2 hours before lying down to sleep"
                ],
                "exercise_suggestions": [
                    "35 minutes of moderate cardio or aerobic exercise 4-5 times a week",
                    "Bodyweight resistance workouts (squats, planks, push-ups)",
                    "A light 15-minute post-meal stroll"
                ],
                "lifestyle_recommendations": [
                    "Track hydration consistency throughout your day",
                    "Establish predictable, structured meal timings",
                    "Address emotional or stress-driven snacking triggers"
                ],
                "medical_disclaimer": disclaimer
            }
        else: # general, fitness, sleep, digestion, cardio
            return {
                "title": f"Personalized Wellness Guidance for '{problem}'",
                "general_wellness": "Maintaining optimal wellness involves balanced nutrition, regular physical movement, consistent hydration, and restorative sleep.",
                "healthy_foods": [
                    "Fresh leafy greens & vibrant seasonal vegetables",
                    "Antioxidant-rich berries & citrus fruits",
                    "Lean proteins (beans, lentils, seeds, nuts)",
                    "Whole grains (oats, quinoa, brown rice)"
                ],
                "diet_considerations": [
                    "Stay well-hydrated with 2.5 - 3 liters of water daily",
                    "Limit refined sugars and processed fast foods",
                    "Ensure balanced meals with complex carbohydrates & protein"
                ],
                "exercise_suggestions": [
                    "30 minutes of brisk walking or moderate cardio daily",
                    "Basic bodyweight strength exercises for muscle tone",
                    "Stretching or yoga for flexibility and recovery"
                ],
                "lifestyle_recommendations": [
                    "Maintain 7-8 hours of consistent nightly sleep",
                    "Practice mindfulness or deep breathing for stress relief",
                    "Take regular active breaks from prolonged sitting"
                ],
                "medical_disclaimer": disclaimer
            }


def _get_default_guidance(lang: str) -> Dict[str, Any]:
    default_problems = {
        'kn': "ಸಾಮಾನ್ಯ ಕ್ಷೇಮ ಮತ್ತು ಶಕ್ತಿ ವೃದ್ಧಿ",
        'hi': "सामान्य स्वास्थ्य एवं ऊर्जा संवर्धन",
        'te': "సాధారణ ఆరోగ్యం మరియు శక్తి",
        'ta': "பொதுவான நல்வாழ்வு மற்றும் ஆற்றல்",
        'en': "General Wellness & Energy"
    }
    p = default_problems.get(lang, default_problems['en'])
    return _generate_structured_domain_guidance(p, lang)
