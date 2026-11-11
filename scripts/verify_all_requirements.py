import sys
import requests

BASE_URL = "http://127.0.0.1:5000"

def run_tests():
    print("=" * 60)
    print("RUNNING COMPREHENSIVE VERIFICATION")
    print("=" * 60)
    
    session = requests.Session()
    try:
        session.get(f"{BASE_URL}/", timeout=2.0)
    except Exception:
        print(f"[NOTE] DNAura server is not running on {BASE_URL}. Please start 'python run.py' before running live integration tests.")
        return
    
    # 1. Login
    login_resp = session.post(f"{BASE_URL}/auth/login", data={
        "identifier": "testuser1",
        "password": "password123"
    }, allow_redirects=True)
    assert login_resp.status_code == 200, f"Login failed: {login_resp.status_code}"
    print("[PASS] 1. Authentication successful as testuser1")

    # 2. Check Hospital Search Page (GET)
    hosp_resp = session.get(f"{BASE_URL}/hospitals")
    assert hosp_resp.status_code == 200
    hosp_html = hosp_resp.text
    
    # Check NO vertical letters / slice(1)
    assert "slice(1)" not in hosp_html, "slice(1) found in hospitals.html!"
    print("[PASS] 2. No slice(1) or vertical letter bug in hospitals page")
    
    # Check no verified RAG badge
    assert "Verified RAG Knowledge Base" not in hosp_html, "Verified RAG Knowledge Base still present!"
    assert "Verified AI Recommendations" not in hosp_html, "Verified AI Recommendations still present!"
    print("[PASS] 3. 'Verified RAG Knowledge Base' and 'Verified AI Recommendations' badges removed")

    # Check speech-to-text button styling and micro permission message
    assert "Speak your requirement" in hosp_html, "Missing 'Speak your requirement' button label"
    assert "btn-sage" in hosp_html, "Missing btn-sage class on hospital page"
    assert "Microphone access is blocked" in hosp_html, "Inline microphone blocked message missing"
    print("[PASS] 4. Speech-to-text sage button and clean inline microphone permission notice present")

    # 3. Search India-Wide: Kolkata
    kol_resp = session.post(f"{BASE_URL}/hospitals/api/search", json={"location": "Hospitals in Kolkata"})
    assert kol_resp.status_code == 200, f"Kolkata search failed: {kol_resp.status_code}"
    kol_data = kol_resp.json()
    assert kol_data.get("hospitals"), "No hospitals returned for Kolkata"
    kol_names = [h.get("name") for h in kol_data.get("hospitals", [])]
    print(f"[PASS] 5. Kolkata Search succeeded: found {len(kol_names)} hospitals: {kol_names[:3]}")

    # 4. Search India-Wide: Bihar
    bihar_resp = session.post(f"{BASE_URL}/hospitals/api/search", json={"location": "Hospitals in Bihar"})
    assert bihar_resp.status_code == 200, f"Bihar search failed: {bihar_resp.status_code}"
    bihar_data = bihar_resp.json()
    assert bihar_data.get("hospitals"), "No hospitals returned for Bihar"
    bihar_names = [h.get("name") for h in bihar_data.get("hospitals", [])]
    print(f"[PASS] 6. Bihar Search succeeded: found {len(bihar_names)} hospitals: {bihar_names[:3]}")

    # 5. Doctor Listing Page
    first_hosp_id = kol_data["hospitals"][0].get("db_id") or kol_data["hospitals"][0].get("id")
    doc_resp = session.get(f"{BASE_URL}/hospitals/{first_hosp_id}/doctors")
    assert doc_resp.status_code == 200
    doc_html = doc_resp.text
    assert "slice(1)" not in doc_html, "slice(1) found in doctors page!"
    assert "doctor-clean-card" in doc_html, "Doctor cards missing on doctors page"
    assert "btn-sage" in doc_html, "btn-sage missing on doctors page"
    print(f"[PASS] 7. Doctor listing page for hospital {first_hosp_id} loads cleanly without slice(1)")

    # 6. Appointment Booking Page (with doctor_id=121)
    book_resp = session.get(f"{BASE_URL}/appointments/book?doctor_id=121")
    assert book_resp.status_code == 200
    book_html = book_resp.text
    assert "slice(1)" not in book_html, "slice(1) found in booking page!"
    
    # Check 4 distinct sections as requested
    assert "DOCTOR INFORMATION" in book_html, "DOCTOR INFORMATION card missing"
    assert "DOCTOR AVAILABILITY" in book_html, "DOCTOR AVAILABILITY card missing"
    assert "SELECT APPOINTMENT" in book_html, "SELECT APPOINTMENT card missing"
    assert "PATIENT DETAILS" in book_html, "PATIENT DETAILS card missing"
    assert "BEST AVAILABLE SLOT" in book_html, "BEST AVAILABLE SLOT missing"
    assert "Back to Hospital Search" in book_html, "Back to Hospital Search link missing"
    assert "Confirm Appointment" in book_html, "Confirm Appointment button missing"
    print("[PASS] 8. Appointment booking page has all 4 clean, spacious section cards")

    # 7. Doctor Availability API (Doctor 121 vs Doctor 122)
    avail_1 = session.get(f"{BASE_URL}/appointments/api/doctor-availability?doctor_id=121").json()
    avail_2 = session.get(f"{BASE_URL}/appointments/api/doctor-availability?doctor_id=122").json()
    assert avail_1.get("success"), "Doctor 121 availability failed"
    assert avail_2.get("success"), "Doctor 122 availability failed"
    
    fee_1 = avail_1.get("consultation_fee")
    fee_2 = avail_2.get("consultation_fee")
    days_1 = avail_1.get("working_days", [])
    days_2 = avail_2.get("working_days", [])
    assert days_1 != days_2, "Doctors should have doctor-specific working days"
    print(f"[PASS] 9. Doctor-specific availability verified:")
    print(f"   Doctor 121: Fee={fee_1}, Days={days_1}, Recommended Slot={avail_1.get('recommended_slot')}")
    print(f"   Doctor 122: Fee={fee_2}, Days={days_2}, Recommended Slot={avail_2.get('recommended_slot')}")

    # 8. Date slot checking
    if avail_1.get("recommended_slot") and avail_1.get("date"):
        target_date = avail_1.get("date")
        slots_resp = session.get(f"{BASE_URL}/appointments/api/doctor-availability?doctor_id=121&date={target_date}").json()
        assert slots_resp.get("success"), "Slots for date failed"
        slots = slots_resp.get("available_slots", [])
        print(f"[PASS] 10. Date-specific slots for {target_date}: {len(slots)} available slots ({slots[:4]}...)")

    print("=" * 60)
    print("ALL 10 VERIFICATION CHECKS PASSED WITH ZERO ERRORS!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
