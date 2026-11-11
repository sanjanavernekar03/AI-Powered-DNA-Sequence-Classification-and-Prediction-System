"""
Strict Location Filtering and Intent Detection Service for Hospital Search.
Enforces hard geographic boundary filtering across all queries.
"""
import re
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Canonical State Taxonomy
INDIAN_STATES = {
    "karnataka": "Karnataka",
    "maharashtra": "Maharashtra",
    "delhi": "Delhi",
    "goa": "Goa",
    "telangana": "Telangana",
    "tamil nadu": "Tamil Nadu",
    "west bengal": "West Bengal",
    "kerala": "Kerala",
    "gujarat": "Gujarat",
    "rajasthan": "Rajasthan",
    "uttar pradesh": "Uttar Pradesh",
    "punjab": "Punjab",
    "haryana": "Haryana",
    "andhra pradesh": "Andhra Pradesh",
    "madhya pradesh": "Madhya Pradesh",
    "bihar": "Bihar",
    "odisha": "Odisha",
    "assam": "Assam",
    "chandigarh": "Chandigarh",
    "jharkhand": "Jharkhand",
    "chhattisgarh": "Chhattisgarh",
    "uttarakhand": "Uttarakhand",
    "himachal pradesh": "Himachal Pradesh",
    "jammu and kashmir": "Jammu and Kashmir",
    "tripura": "Tripura",
    "meghalaya": "Meghalaya",
    "manipur": "Manipur",
    "nagaland": "Nagaland",
    "mizoram": "Mizoram",
    "arunachal pradesh": "Arunachal Pradesh",
    "sikkim": "Sikkim",
    "puducherry": "Puducherry",
    "ladakh": "Ladakh"
}

# State to Cities mapping (covers major cities, districts, and towns across India)
STATE_CITIES: Dict[str, Set[str]] = {
    "karnataka": {
        "bengaluru", "bangalore", "karwar", "manipal", "mangalore", "mangaluru",
        "mysore", "mysuru", "hubli", "hubballi", "dharwad", "belgaum", "belagavi",
        "udupi", "shimoga", "shivamogga", "ankola", "kumta", "honnavar", "bhatkal",
        "bellary", "ballari", "kalaburagi", "gulbarga", "davangere", "bidar", "hassan",
        "tumkur", "tumakuru", "raichur", "koppal", "bagalkot", "bijapur", "vijayapura",
        "gadag", "chikkamagaluru", "chitradurga", "kolar", "mandya", "yadgir", "chamarajanagar"
    },
    "maharashtra": {
        "mumbai", "bombay", "navi mumbai", "pune", "poona", "nagpur", "nashik",
        "thane", "aurangabad", "chhatrapati sambhajinagar", "kolhapur", "solapur",
        "amravati", "nanded", "alibag", "sangli", "jalgaon", "akola", "latur",
        "dhule", "ahmednagar", "chandrapur", "parbhani", "panvel", "satara", "beed",
        "yavatmal", "gondia", "wardha", "bhandara", "buldhana", "jalna", "ratnagiri",
        "sindhudurg", "palghar", "raigad"
    },
    "delhi": {
        "delhi", "new delhi", "ncr", "central delhi", "south delhi", "north delhi",
        "east delhi", "west delhi", "dwarka", "rohini", "saket", "connaught place",
        "hauz khas", "vasant kunj", "lajpat nagar", "janakpuri", "pitampura"
    },
    "goa": {
        "goa", "panaji", "panjim", "margao", "madgaon", "vasco", "vasco da gama",
        "mapusa", "ponda", "bambolim", "dona paula", "porvorim", "canacona", "quepem", "sanguem"
    },
    "telangana": {
        "hyderabad", "secunderabad", "warangal", "nizamabad", "karimnagar", "khammam",
        "ramagundam", "mahbubnagar", "nalgonda", "adilabad", "suryapet", "siddipet"
    },
    "tamil nadu": {
        "chennai", "madras", "coimbatore", "madurai", "tiruchirappalli", "salem",
        "tirunelveli", "tiruppur", "ranipet", "vellore", "erode", "thoothukudi",
        "dindigul", "thanjavur", "hosur", "nagercoil", "kanchipuram", "cuddalore"
    },
    "west bengal": {
        "kolkata", "calcutta", "newtown", "howrah", "durgapur", "asansol", "siliguri",
        "bardhaman", "malda", "kharagpur", "haldia", "habra", "shantipur", "dankuni",
        "dhulian", "ranaghat", "darjeeling", "jalpaiguri", "alipurduar", "cooch behar",
        "purulia", "bankura", "birbhum", "midnapore"
    },
    "kerala": {
        "kochi", "cochin", "thiruvananthapuram", "trivandrum", "kozhikode", "calicut",
        "thrissur", "kollam", "kannur", "alappuzha", "kottayam", "palakkad",
        "malappuram", "kasaragod", "pathanamthitta", "idukki", "wayanad"
    },
    "gujarat": {
        "ahmedabad", "surat", "vadodara", "baroda", "rajkot", "bhavnagar", "jamnagar",
        "junagadh", "gandhinagar", "anand", "navsari", "morbi", "nadiad", "surendranagar",
        "bharuch", "mehsana", "bhuj", "porbandar", "valsad", "vapi"
    },
    "rajasthan": {
        "jaipur", "jodhpur", "kota", "bikaner", "ajmer", "udaipur", "bhilwara",
        "alwar", "bharatpur", "sikar", "pali", "sri ganganagar", "chittorgarh",
        "kishangarh", "baran", "dholpur", "sawai madhopur", "churu", "jhunjhunu"
    },
    "uttar pradesh": {
        "lucknow", "kanpur", "varanasi", "agra", "prayagraj", "allahabad", "ghaziabad",
        "noida", "greater noida", "meerut", "bareilly", "aligarh", "moradabad",
        "saharanpur", "gorakhpur", "firozabad", "jhansi", "muzaffarnagar", "mathura",
        "ayodhya", "faizabad", "rampur", "shahjahanpur", "farrukhabad", "hapur"
    },
    "punjab": {
        "chandigarh", "amritsar", "ludhiana", "jalandhar", "patiala", "bathinda",
        "mohali", "hoshiarpur", "batala", "pathankot", "moga", "abohar"
    },
    "haryana": {
        "gurgaon", "gurugram", "faridabad", "panipat", "ambala", "rohtak", "hisar",
        "karnal", "sonipat", "panchkula", "bhiwani", "sirsa", "bahadurgarh"
    },
    "andhra pradesh": {
        "visakhapatnam", "vizag", "vijayawada", "guntur", "nellore", "kurnool",
        "rajahmundry", "tirupati", "kakinada", "kadapa", "anantapur", "eluru",
        "ongole", "vizianagaram", "machilipatnam", "srikakulam"
    },
    "madhya pradesh": {
        "bhopal", "indore", "jabalpur", "gwalior", "ujjain", "sagar", "dewas",
        "satna", "ratlam", "rewa", "katni", "singrauli", "burhanpur", "khandwa",
        "chhindwara", "shivpuri", "vidisha", "damoh"
    },
    "bihar": {
        "patna", "gaya", "muzaffarpur", "darbhanga", "bhagalpur", "purnia",
        "bihar sharif", "ara", "begusarai", "katihar", "munger", "chhapra",
        "motihari", "sasaram", "dehir", "hajipur", "samastipur", "siwan",
        "buxar", "saharsa", "madhubani", "bettiah", "sitamarhi", "kishanganj",
        "jamui", "nawada", "arwal", "jehanabad", "aurangabad", "khagaria",
        "lakhisarai", "sheikhpura", "supaul", "banka", "gopalganj"
    },
    "jharkhand": {
        "ranchi", "jamshedpur", "dhanbad", "bokaro", "deoghar", "hazaribagh",
        "giridih", "ramgarh", "medininagar", "chirkunda", "chaibasa", "dumka",
        "godda", "sahebganj", "koderma", "chatra", "gumla", "simdega", "khunti"
    },
    "odisha": {
        "bhubaneswar", "cuttack", "rourkela", "berhampur", "sambalpur", "puri",
        "balasore", "bhadrak", "baripada", "jharsuguda", "jeypore", "angul"
    },
    "assam": {
        "guwahati", "silchar", "dibrugarh", "jorhat", "nagaon", "tinsukia",
        "tezpur", "bongaigaon", "dhubri", "diphu", "north lakhimpur", "karimganj"
    },
    "chhattisgarh": {
        "raipur", "bhilai", "bilaspur", "korba", "durg", "rajnandgaon", "jagdalpur"
    },
    "uttarakhand": {
        "dehradun", "haridwar", "roorkee", "haldwani", "rudrapur", "kashipur", "rishikesh"
    },
    "himachal pradesh": {
        "shimla", "dharamshala", "solan", "mandi", "palampur", "baddi", "kullu"
    },
    "jammu and kashmir": {
        "srinagar", "jammu", "anantnag", "baramulla", "kathua", "udhampur", "sopore"
    }
}

# City Aliases & Display Names (covering all user search targets and major hubs)
CITY_METADATA: Dict[str, Dict[str, Any]] = {
    "kolkata": {
        "display": "Kolkata",
        "state": "West Bengal",
        "aliases": ["kolkata", "calcutta", "newtown", "कोलकाता", "কলকাতা"]
    },
    "patna": {
        "display": "Patna",
        "state": "Bihar",
        "aliases": ["patna", "पटना", "पाटलिपुत्र"]
    },
    "gaya": {
        "display": "Gaya",
        "state": "Bihar",
        "aliases": ["gaya", "bodhgaya", "bodh gaya", "गया", "बोधगया"]
    },
    "muzaffarpur": {
        "display": "Muzaffarpur",
        "state": "Bihar",
        "aliases": ["muzaffarpur", "मुजफ्फरपुर"]
    },
    "darbhanga": {
        "display": "Darbhanga",
        "state": "Bihar",
        "aliases": ["darbhanga", "दरभंगा"]
    },
    "bhagalpur": {
        "display": "Bhagalpur",
        "state": "Bihar",
        "aliases": ["bhagalpur", "भागलपुर"]
    },
    "ranchi": {
        "display": "Ranchi",
        "state": "Jharkhand",
        "aliases": ["ranchi", "रांची", "राँची"]
    },
    "jamshedpur": {
        "display": "Jamshedpur",
        "state": "Jharkhand",
        "aliases": ["jamshedpur", "tatanagar", "जमशेदपुर"]
    },
    "karwar": {
        "display": "Karwar",
        "state": "Karnataka",
        "aliases": ["karwar", "ಕಾರವಾರ", "कारवार"]
    },
    "bengaluru": {
        "display": "Bengaluru",
        "state": "Karnataka",
        "aliases": ["bengaluru", "bangalore", "ಬೆಂಗಳೂರು", "बैंगलोर", "बेंगलोर", "बेंगलुरु"]
    },
    "manipal": {
        "display": "Manipal",
        "state": "Karnataka",
        "aliases": ["manipal", "ಮಣಿಪಾಲ"]
    },
    "mangalore": {
        "display": "Mangalore",
        "state": "Karnataka",
        "aliases": ["mangalore", "mangaluru", "ಮಂಗಳೂರು"]
    },
    "mysore": {
        "display": "Mysore",
        "state": "Karnataka",
        "aliases": ["mysore", "mysuru", "ಮೈಸೂರು"]
    },
    "hubli": {
        "display": "Hubli",
        "state": "Karnataka",
        "aliases": ["hubli", "hubballi", "ಹುಬ್ಬಳ್ಳಿ"]
    },
    "belgaum": {
        "display": "Belgaum",
        "state": "Karnataka",
        "aliases": ["belgaum", "belagavi", "ಬೆಳಗಾವಿ"]
    },
    "mumbai": {
        "display": "Mumbai",
        "state": "Maharashtra",
        "aliases": ["mumbai", "bombay", "navi mumbai", "मुंबई"]
    },
    "pune": {
        "display": "Pune",
        "state": "Maharashtra",
        "aliases": ["pune", "poona", "पुणे"]
    },
    "nagpur": {
        "display": "Nagpur",
        "state": "Maharashtra",
        "aliases": ["nagpur", "नागपुर"]
    },
    "delhi": {
        "display": "Delhi",
        "state": "Delhi",
        "aliases": ["delhi", "new delhi", "delhi ncr", "दिल्ली", "ದೆಹಲಿ"]
    },
    "chennai": {
        "display": "Chennai",
        "state": "Tamil Nadu",
        "aliases": ["chennai", "madras", "चेन्नई", "ಚೆನ್ನೈ"]
    },
    "hyderabad": {
        "display": "Hyderabad",
        "state": "Telangana",
        "aliases": ["hyderabad", "secunderabad", "हैदराबाद", "ಹೈದರಾಬಾದ್"]
    },
    "thiruvananthapuram": {
        "display": "Thiruvananthapuram",
        "state": "Kerala",
        "aliases": ["thiruvananthapuram", "trivandrum", "तिरुवनंतपुरम"]
    },
    "kochi": {
        "display": "Kochi",
        "state": "Kerala",
        "aliases": ["kochi", "cochin", "कोच्चि"]
    },
    "lucknow": {
        "display": "Lucknow",
        "state": "Uttar Pradesh",
        "aliases": ["lucknow", "लखनऊ"]
    },
    "varanasi": {
        "display": "Varanasi",
        "state": "Uttar Pradesh",
        "aliases": ["varanasi", "banaras", "kashi", "वाराणसी"]
    },
    "kanpur": {
        "display": "Kanpur",
        "state": "Uttar Pradesh",
        "aliases": ["kanpur", "कानपुर"]
    },
    "ahmedabad": {
        "display": "Ahmedabad",
        "state": "Gujarat",
        "aliases": ["ahmedabad", "amdavad", "अहमदाबाद"]
    },
    "surat": {
        "display": "Surat",
        "state": "Gujarat",
        "aliases": ["surat", "सूरत"]
    },
    "jaipur": {
        "display": "Jaipur",
        "state": "Rajasthan",
        "aliases": ["jaipur", "जयपुर"]
    },
    "jodhpur": {
        "display": "Jodhpur",
        "state": "Rajasthan",
        "aliases": ["jodhpur", "जोधपुर"]
    },
    "bhopal": {
        "display": "Bhopal",
        "state": "Madhya Pradesh",
        "aliases": ["bhopal", "भोपाल"]
    },
    "indore": {
        "display": "Indore",
        "state": "Madhya Pradesh",
        "aliases": ["indore", "इंदौर"]
    },
    "bhubaneswar": {
        "display": "Bhubaneswar",
        "state": "Odisha",
        "aliases": ["bhubaneswar", "भुवनेश्वर"]
    },
    "cuttack": {
        "display": "Cuttack",
        "state": "Odisha",
        "aliases": ["cuttack", "कटक"]
    },
    "guwahati": {
        "display": "Guwahati",
        "state": "Assam",
        "aliases": ["guwahati", "gauhati", "गुवाहाटी"]
    },
    "visakhapatnam": {
        "display": "Visakhapatnam",
        "state": "Andhra Pradesh",
        "aliases": ["visakhapatnam", "vizag", "विशाखापत्तनम"]
    },
    "chandigarh": {
        "display": "Chandigarh",
        "state": "Punjab",
        "aliases": ["chandigarh", "चंडीगढ़"]
    },
    "goa": {
        "display": "Goa",
        "state": "Goa",
        "aliases": ["goa", "panaji", "panjim", "margao", "madgaon", "vasco", "गोवा", "ಗೋವಾ"]
    }
}

NEARBY_PHRASES = [
    "near me", "near my location", "near our location", "near the location",
    "near current location", "near my current location", "near registered location",
    "nearby", "nearby hospitals", "close to me", "around me", "nearest",
    "closest to me", "close by", "near here", "मेरे पास", "ನನ್ನ ಹತ್ತಿರ", "ಹತ್ತಿರದ",
    "அருகில்", "దగ్గర"
]

SPECIALTY_KEYWORDS = {
    "cancer": "Oncology",
    "oncology": "Oncology",
    "oncologist": "Oncology",
    "tumor": "Oncology",
    "chemotherapy": "Oncology",
    "radiation": "Radiation Oncology",
    "surgical oncology": "Surgical Oncology",
    "medical oncology": "Medical Oncology",
    "cardiology": "Cardiologist",
    "cardiologist": "Cardiologist",
    "cardio": "Cardiologist",
    "heart": "Cardiologist",
    "pediatric": "Pediatrician",
    "pediatrician": "Pediatrician",
    "pediatrics": "Pediatrician",
    "child": "Pediatrician",
    "neurology": "Neurologist",
    "neurologist": "Neurologist",
    "neuro": "Neurologist",
    "brain": "Neurologist",
    "orthopedic": "Orthopedic Doctor",
    "orthopedics": "Orthopedic Doctor",
    "dermatology": "Dermatologist & Oncologist",
    "dermatologist": "Dermatologist & Oncologist",
    "skin": "Dermatologist & Oncologist",
    "general physician": "General Physician",
    "physician": "General Physician"
}

HOSPITAL_BRANDS = [
    "apollo", "fortis", "tata", "aiims", "kidwai", "manipal", "ruby hall",
    "jehangir", "max", "narayana", "hcg", "basavatarakam", "yashoda", "kims",
    "rajiv gandhi", "cnci", "lilavati", "kokilaben", "gmc", "rims", "anmmch",
    "skmch", "krims", "dmch", "mcsc", "mahavir", "igims", "bbci"
]


def detect_location_intent(query: str, user_default_location: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract location from user query with strict priority:
    1. Explicit location in user query (City, District or State) -> HARD FILTER
    2. 'Near me / nearby' intent -> radius search
    3. User registered location ONLY if query asks for nearby or no explicit location is provided.
    """
    if not query:
        return {"type": "none", "is_nearby": False, "name": None, "display_name": None}

    q_lower = query.strip().lower()

    # Step 1: Detect explicit city in query (Priority 1)
    # Check multi-word aliases first, then single words
    detected_city_key = None
    for city_key, meta in CITY_METADATA.items():
        for alias in meta["aliases"]:
            pattern = r'(?:\b|_)' + re.escape(alias.lower()) + r'(?:\b|_)'
            if re.search(pattern, q_lower):
                detected_city_key = city_key
                break
        if detected_city_key:
            break

    # Step 2: Detect explicit state in query (Priority 1)
    detected_state_key = None
    for state_key, state_name in INDIAN_STATES.items():
        pattern = r'(?:\b|_)' + re.escape(state_key) + r'(?:\b|_)'
        if re.search(pattern, q_lower):
            detected_state_key = state_key
            break

    # If city detected:
    if detected_city_key:
        meta = CITY_METADATA[detected_city_key]
        return {
            "type": "city",
            "key": detected_city_key,
            "name": meta["display"],
            "display_name": meta["display"],
            "state": meta["state"],
            "is_nearby": False,
            "is_explicit": True
        }

    # If state detected:
    if detected_state_key:
        state_name = INDIAN_STATES[detected_state_key]
        return {
            "type": "state",
            "key": detected_state_key,
            "name": state_name,
            "display_name": state_name,
            "state": state_name,
            "is_nearby": False,
            "is_explicit": True
        }

    # Step 2b: Check all towns/cities registered across STATE_CITIES
    for st_k, c_set in STATE_CITIES.items():
        for town in c_set:
            pattern = r'(?:\b|_)' + re.escape(town) + r'(?:\b|_)'
            if re.search(pattern, q_lower):
                clean_name = town.title()
                st_name = INDIAN_STATES.get(st_k, st_k.title())
                return {
                    "type": "city",
                    "key": town,
                    "name": clean_name,
                    "display_name": clean_name,
                    "state": st_name,
                    "is_nearby": False,
                    "is_explicit": True
                }

    # Step 2c: Check prepositioned location e.g. "in <Location>", "near <Location>", "at <Location>", "around <Location>"
    m_prep = re.search(r'\b(?:in|at|near|around|from|to|for|within)\s+([a-zA-Z\s]{2,25})\b', query, re.IGNORECASE)
    if m_prep:
        candidate = m_prep.group(1).strip().lower()
        stopwords = {
            "india", "hospital", "hospitals", "doctor", "doctors", "the hospital",
            "cancer", "icu", "opd", "emergency", "the country", "near me", "nearby",
            "me", "my", "our", "current location"
        }
        if candidate not in stopwords and not any(sw in candidate for sw in ["hospital", "doctor"]):
            for c_k, c_m in CITY_METADATA.items():
                if candidate in [a.lower() for a in c_m["aliases"]]:
                    return {
                        "type": "city",
                        "key": c_k,
                        "name": c_m["display"],
                        "display_name": c_m["display"],
                        "state": c_m["state"],
                        "is_nearby": False,
                        "is_explicit": True
                    }
            for s_k, s_n in INDIAN_STATES.items():
                if candidate == s_k or candidate == s_n.lower():
                    return {
                        "type": "state",
                        "key": s_k,
                        "name": s_n,
                        "display_name": s_n,
                        "state": s_n,
                        "is_nearby": False,
                        "is_explicit": True
                    }
            for st_k, c_set in STATE_CITIES.items():
                if candidate in c_set:
                    st_name = INDIAN_STATES.get(st_k, st_k.title())
                    return {
                        "type": "city",
                        "key": candidate,
                        "name": candidate.title(),
                        "display_name": candidate.title(),
                        "state": st_name,
                        "is_nearby": False,
                        "is_explicit": True
                    }

            clean_name = candidate.title()
            return {
                "type": "city",
                "key": candidate,
                "name": clean_name,
                "display_name": clean_name,
                "state": "",
                "is_nearby": False,
                "is_explicit": True
            }

    # Step 2d: Dynamic place recognition via clean place query
    # If user entered a short query (<= 4 words) that is not a pure medical term,
    # test if geocoding resolves it to a valid real place!
    clean_q = query.strip()
    pure_medical_terms = {
        "hospital", "hospitals", "doctor", "doctors", "cancer", "oncology",
        "cardiologist", "physician", "appointment", "book", "find", "search",
        "help", "opd", "icu", "emergency", "treatment", "clinic", "specialist",
        "me", "nearby", "near me"
    }
    words = [w.lower() for w in re.findall(r'[a-zA-Z]+', clean_q)]
    if words and len(words) <= 4 and not all(w in pure_medical_terms for w in words):
        place_words = [w for w in words if w not in pure_medical_terms]
        candidate_place = " ".join(place_words) if place_words else clean_q
        if candidate_place and len(candidate_place) >= 2:
            from app.services.maps_service import geocode_address
            geo = geocode_address(candidate_place)
            if geo:
                clean_name = candidate_place.title()
                return {
                    "type": "city",
                    "key": candidate_place.lower(),
                    "name": clean_name,
                    "display_name": clean_name,
                    "state": "",
                    "is_nearby": False,
                    "is_explicit": True
                }

    # Step 3: Detect Nearby Intent (Priority 2)
    is_nearby = any(p in q_lower for p in NEARBY_PHRASES)
    if is_nearby:
        return {
            "type": "nearby",
            "key": "nearby",
            "name": "Nearby",
            "display_name": "Current / Registered Location",
            "is_nearby": True,
            "is_explicit": False
        }

    # Step 4: No location specified in query
    return {
        "type": "none",
        "key": None,
        "name": None,
        "display_name": None,
        "is_nearby": False,
        "is_explicit": False
    }


def is_hospital_matching_location(hospital: Dict[str, Any], location_intent: Dict[str, Any]) -> bool:
    """
    HARD LOCATION FILTER VALIDATION.
    Determines with absolute certainty if a hospital is physically located within the specified location.
    Rejects any hospital belonging to a different city or state.
    """
    if not location_intent or location_intent.get("is_nearby") or location_intent.get("type") == "none":
        return True

    h_city = (hospital.get("city") or "").strip().lower()
    h_state = (hospital.get("state") or "").strip().lower()
    h_addr = (hospital.get("address") or "").strip().lower()
    h_name = (hospital.get("name") or hospital.get("hospital_name") or "").strip().lower()

    loc_type = location_intent.get("type")

    # 1. Target is a CITY (e.g. Mumbai, Bengaluru, Delhi, Goa, Pune, Hyderabad, etc.)
    if loc_type == "city":
        target_city_key = location_intent.get("key", "").lower()
        target_name = location_intent.get("name", "").lower()
        meta = CITY_METADATA.get(target_city_key, {})
        aliases = [a.lower() for a in meta.get("aliases", [target_city_key, target_name])]

        # Ensure hospital does NOT belong to an explicitly different known city
        for other_key, other_meta in CITY_METADATA.items():
            if other_key != target_city_key:
                if h_city in [a.lower() for a in other_meta["aliases"]] or h_city == other_key:
                    if any(oa in h_addr for oa in other_meta["aliases"]):
                        return False

        # Now verify that hospital's address, city, or name matches target city
        addr_matches = any(re.search(r'\b' + re.escape(a) + r'\b', h_addr) for a in aliases)
        name_matches = any(re.search(r'\b' + re.escape(a) + r'\b', h_name) for a in aliases)
        city_matches = any(a in h_city for a in aliases)

        if addr_matches or name_matches or city_matches:
            return True

        # If target city is an arbitrary location not in hardcoded taxonomy,
        # also match if target name is contained in city or address or vice versa
        if target_city_key not in CITY_METADATA:
            if target_city_key in h_city or target_city_key in h_addr or target_name in h_city or target_name in h_addr:
                return True
            if h_city and (h_city in target_city_key or h_city in target_name):
                return True

        return False

    # 2. Target is a STATE (e.g. Karnataka, Maharashtra, Delhi, Goa, etc.)
    if loc_type == "state":
        target_state_key = location_intent.get("key", "").lower()
        target_state_name = location_intent.get("name", "").lower()

        # If hospital explicitly has a state defined, and it's a DIFFERENT known state, REJECT
        for other_state_key, other_state_name in INDIAN_STATES.items():
            if other_state_key != target_state_key:
                if h_state == other_state_key or h_state == other_state_name.lower():
                    return False
                # Also if hospital's city belongs to an outside state, REJECT
                outside_cities = STATE_CITIES.get(other_state_key, set())
                if h_city in outside_cities:
                    return False

        # Positive check: state matches target OR city is in target state's cities OR address contains state
        valid_cities = STATE_CITIES.get(target_state_key, set())
        state_matches = (h_state == target_state_key or target_state_key in h_state or target_state_name in h_state)
        city_matches = (h_city in valid_cities)
        addr_matches = (target_state_key in h_addr or target_state_name in h_addr)

        if state_matches or city_matches or addr_matches:
            return True

        return False

    return True


def filter_hospitals_strictly(
    hospitals: List[Dict[str, Any]],
    location_intent: Optional[Dict[str, Any]] = None,
    specialty: Optional[str] = None,
    brand: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Applies hard location, specialty, and brand filters to hospital records.
    Never returns out-of-location hospitals.
    """
    if not hospitals:
        return []

    filtered = []
    for h in hospitals:
        # 1. Hard Location Filter
        if location_intent and location_intent.get("is_explicit"):
            if not is_hospital_matching_location(h, location_intent):
                continue

        # 2. Brand / Name Filter (e.g. Apollo, Manipal)
        if brand and brand.strip():
            b_clean = brand.strip().lower()
            h_name = (h.get("name") or h.get("hospital_name") or "").lower()
            if b_clean not in h_name:
                continue

        # 3. Specialty Filter (e.g. Oncology, Cardiology, Pediatrician)
        if specialty and specialty.strip():
            spec_clean = specialty.strip().lower()
            # Check hospital services
            services = h.get("services") or []
            services_text = " ".join([str(s) for s in services]).lower()

            # Check hospital doctors
            doctors = h.get("doctors") or []
            has_matching_doc = any(
                spec_clean in (d.get("specialty") or d.get("specialization") or "").lower()
                for d in doctors
            )
            has_matching_service = spec_clean in services_text

            # For oncology/cancer requests:
            if "oncolog" in spec_clean or "cancer" in spec_clean:
                has_matching_service = has_matching_service or any(
                    k in services_text for k in ["cancer", "oncology", "chemotherapy", "radiation"]
                ) or "cancer" in (h.get("name") or "").lower() or "oncology" in (h.get("name") or "").lower()

            if not (has_matching_doc or has_matching_service):
                continue

        filtered.append(h)

    return filtered


def extract_specialty_and_brand(query: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract requested medical specialty and hospital brand from query."""
    q_lower = query.lower()
    spec = None
    for kw, title in SPECIALTY_KEYWORDS.items():
        if re.search(r'\b' + re.escape(kw) + r'\b', q_lower):
            spec = title
            break

    brand = None
    for b in HOSPITAL_BRANDS:
        if re.search(r'\b' + re.escape(b) + r'\b', q_lower):
            brand = b
            break

    return spec, brand
