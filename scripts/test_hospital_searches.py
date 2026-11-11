import requests
import json
import sys

BASE_URL = "http://127.0.0.1:5000"

# Target searches
SEARCH_QUERIES = [
    ("Kolkata", "Hospitals in Kolkata"),
    ("Bihar", "Hospitals in Bihar"),
    ("Patna", "Hospitals in Patna"),
    ("Gaya", "Find hospitals near Gaya"),
    ("Muzaffarpur", "Hospitals in Muzaffarpur"),
    ("Ranchi", "Hospitals in Ranchi"),
    ("Karwar", "Hospital in Karwar"),
    ("Mumbai", "Hospitals in Mumbai"),
    ("Bengaluru", "Hospitals in Bengaluru"),
    ("Delhi", "Hospitals in Delhi"),
    ("Darbhanga", "Hospitals in Darbhanga (Small Town)"),
]

DEMO_KEYWORDS = ["marcus vance", "demo", "placeholder", "fictional", "dr. john smith"]

def run_tests():
    session = requests.Session()
    try:
        session.get(f"{BASE_URL}/", timeout=2.0)
    except Exception:
        print(f"[NOTE] DNAura server is not running on {BASE_URL}. Please start 'python run.py' before running live integration tests.")
        return

    # Log in first to have full access if required
    login_res = session.post(f"{BASE_URL}/auth/login", data={"identifier": "tanvi", "password": "password123"})
    print(f"Login status: {login_res.status_code}, URL: {login_res.url}")

    all_passed = True
    all_doctor_ids = set()
    hospital_doctor_map = {}

    print("\n" + "="*80)
    print("STARTING COMPREHENSIVE VERIFICATION FOR 11 REQUIRED SEARCH LOCATIONS")
    print("="*80 + "\n")

    for loc_name, query_str in SEARCH_QUERIES:
        print(f"\n--- TESTING QUERY: '{query_str}' (Expected: {loc_name}) ---")
        res = session.post(f"{BASE_URL}/hospitals/api/ai_search", json={"query": query_str})
        if res.status_code != 200:
            print(f"FAILED: HTTP {res.status_code} - {res.text}")
            all_passed = False
            continue

        data = res.json()
        hospitals = data.get("hospitals", [])
        total_hosp = len(hospitals)
        print(f"Hospitals returned: {total_hosp}")

        if total_hosp == 0:
            print(f"FAILED: No hospitals returned for {loc_name}!")
            all_passed = False
            continue

        for h in hospitals:
            h_id = h.get("id")
            h_name = h.get("name")
            h_city = h.get("city")
            h_state = h.get("state")
            h_addr = h.get("address")
            doctors = h.get("doctors", [])
            doc_count = len(doctors)

            print(f"\n  * Hospital: {h_name} [ID: {h_id}]")
            print(f"    Location: City='{h_city}', State='{h_state}'")
            print(f"    Address: {h_addr[:60]}...")
            print(f"    Doctors count: {doc_count}")

            # Verify location relevance
            loc_low = loc_name.lower()
            if loc_low == "bihar":
                is_loc_valid = (
                    "bihar" in (h_state or "").lower() or
                    any(c in (h_city or "").lower() for c in ["patna", "gaya", "muzaffarpur", "darbhanga", "bhagalpur"])
                )
            else:
                is_loc_valid = (
                    loc_low in (h_city or "").lower() or
                    loc_low in (h_addr or "").lower() or
                    loc_low in (h_name or "").lower()
                )

            if not is_loc_valid:
                print(f"    ERROR: Hospital {h_name} does not match requested location {loc_name}!")
                all_passed = False
            else:
                print(f"    Location match: PASS")

            # Verify 3-doctor minimum rule
            if doc_count < 3:
                print(f"    ERROR: Hospital {h_name} has only {doc_count} doctors (< 3)!")
                all_passed = False
            else:
                print(f"    3-Doctor Rule (>=3): PASS ({doc_count} doctors)")

            # Check doctors
            hospital_doctor_map[h_id] = [d["name"] for d in doctors]
            for doc in doctors:
                doc_id = doc.get("id")
                doc_name = doc.get("name")
                doc_spec = doc.get("specialization")
                all_doctor_ids.add(doc_id)

                # Check for fake/demo names
                is_demo = any(k in doc_name.lower() for k in DEMO_KEYWORDS)
                if is_demo:
                    print(f"    ERROR: Demo doctor detected: {doc_name}!")
                    all_passed = False
                
                print(f"      - Dr. {doc_name} | {doc_spec} [ID: {doc_id}]")

    print("\n" + "="*80)
    print("VERIFYING DOCTOR ROSTER UNIQUENESS BETWEEN HOSPITALS")
    print("="*80)

    # Verify that doctors are distinct between hospitals
    unique_check_passed = True
    hospital_ids = list(hospital_doctor_map.keys())
    for i in range(len(hospital_ids)):
        for j in range(i + 1, len(hospital_ids)):
            h1 = hospital_ids[i]
            h2 = hospital_ids[j]
            docs1 = set(hospital_doctor_map[h1])
            docs2 = set(hospital_doctor_map[h2])
            overlap = docs1.intersection(docs2)
            if overlap:
                print(f"ERROR: Doctors shared between Hospital {h1} and Hospital {h2}: {overlap}")
                unique_check_passed = False
                all_passed = False

    if unique_check_passed:
        print("ALL DOCTOR ROSTERS ARE 100% UNIQUE TO THEIR RESPECTIVE HOSPITALS: PASS")

    print("\n" + "="*80)
    if all_passed:
        print("ALL 11 USER TEST CASES PASSED WITH 100% COMPLIANCE!")
    else:
        print("SOME TESTS FAILED! Check log above.")
    print("="*80 + "\n")

    return all_passed

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
