import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import re

BASE_URL = "http://127.0.0.1:5000"

def run_tests():
    session = requests.Session()
    try:
        session.get(f"{BASE_URL}/", timeout=2.0)
    except Exception:
        print(f"[NOTE] DNAura server is not running on {BASE_URL}. Please start 'python run.py' before running live integration tests.")
        return

    print("--- 1. Testing Login ---")
    login_resp = session.post(f"{BASE_URL}/auth/login", data={"identifier": "tanvi", "password": "password123"}, allow_redirects=True)
    assert login_resp.status_code == 200, f"Login failed with status {login_resp.status_code}"
    print("Logged in successfully.")

    print("\n--- 2. Verifying 'Verified RAG Knowledge Base' is REMOVED from hospitals.html ---")
    hosp_resp = session.get(f"{BASE_URL}/hospitals/")
    assert hosp_resp.status_code == 200
    html_content = hosp_resp.text
    forbidden_terms = [
        "Verified RAG Knowledge Base",
        "Verified AI Recommendations",
        "Grounded in verified oncology knowledge base and hospital directories"
    ]
    for term in forbidden_terms:
        if term in html_content:
            raise AssertionError(f"Forbidden term '{term}' still found in hospitals.html!")
    print("PASS: No 'Verified RAG Knowledge Base' or related branding found in UI.")

    print("\n--- 3. Testing Doctor A vs Doctor B Availability & Fees ---")
    # Doctor 782: Dr. Jagjit Kumar Pandey (AIIMS Patna, Mon/Wed/Fri, 500 fee)
    res_a = session.get(f"{BASE_URL}/appointments/api/doctor-availability?doctor_id=782&date=2026-10-14")
    assert res_a.status_code == 200, f"Doctor 782 API failed: {res_a.text}"
    data_a = res_a.json()
    assert data_a['doctor_name'] == "Dr. Jagjit Kumar Pandey"
    assert data_a['consultation_fee'] == 500
    assert data_a['is_day_available'] is True  # 2026-10-14 is Wednesday
    assert len(data_a['available_slots']) > 0
    assert "09:00 AM" in data_a['available_slots']
    assert data_a['recommended_slot']['slot'] == data_a['available_slots'][0]
    print(f"Doctor A (Dr. Jagjit Kumar Pandey): Fee = {data_a['consultation_fee']}, Day Available = {data_a['is_day_available']}, Recommended = {data_a['recommended_slot']['slot']}, Slots Count = {len(data_a['available_slots'])}")

    # Doctor 783: Dr. Pritanjali Singh (AIIMS Patna, Tue/Thu/Sat, 600 fee)
    res_b = session.get(f"{BASE_URL}/appointments/api/doctor-availability?doctor_id=783&date=2026-10-14")
    assert res_b.status_code == 200, f"Doctor 783 API failed: {res_b.text}"
    data_b = res_b.json()
    assert data_b['doctor_name'] == "Dr. Pritanjali Singh"
    assert data_b['consultation_fee'] == 600
    # On Wednesday, Doctor B is NOT available
    assert data_b['is_day_available'] is False
    assert len(data_b['available_slots']) == 0
    print(f"Doctor B (Dr. Pritanjali Singh on Wednesday): Fee = {data_b['consultation_fee']}, Day Available = {data_b['is_day_available']}, Slots Count = {len(data_b['available_slots'])}")

    # Check Doctor B on Thursday (2026-10-15)
    res_b_thu = session.get(f"{BASE_URL}/appointments/api/doctor-availability?doctor_id=783&date=2026-10-15")
    data_b_thu = res_b_thu.json()
    assert data_b_thu['is_day_available'] is True
    assert len(data_b_thu['available_slots']) > 0
    print(f"Doctor B (Dr. Pritanjali Singh on Thursday): Day Available = {data_b_thu['is_day_available']}, Recommended = {data_b_thu['recommended_slot']['slot']}")
    print("PASS: Doctor A and Doctor B have distinct availability schedules and distinct consultation fees.")

    print("\n--- 4. Testing Booking Creation & Double Booking Prevention ---")
    test_date = "2026-10-14"
    test_slot = "10:30 AM"

    # Clean up existing test appointment if present
    from app.database.connection import get_db
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM appointments WHERE doctor_id = 782 AND appointment_date = %s AND appointment_time = %s", (test_date, test_slot))
        cur.close()

    # Book the slot
    book_post = session.post(f"{BASE_URL}/appointments/book", data={
        "hospital_id": 104,
        "doctor_id": 782,
        "appointment_date": test_date,
        "appointment_time": test_slot,
        "patient_name": "Test Patient",
        "phone": "+91 9876543210",
        "reason_for_visit": "Oncology Consultation",
        "notes": "Testing slot booking"
    }, allow_redirects=True)
    assert book_post.status_code == 200
    print(f"Booked slot {test_slot} on {test_date} for Doctor 782.")

    # Now verify that doctor availability reports this slot as BOOKED
    res_check = session.get(f"{BASE_URL}/appointments/api/doctor-availability?doctor_id=782&date={test_date}")
    check_data = res_check.json()
    assert test_slot in check_data['booked_slots'], f"{test_slot} should be in booked_slots"
    assert test_slot not in check_data['available_slots'], f"{test_slot} should NOT be in available_slots"
    print(f"PASS: Slot {test_slot} is now in booked_slots and omitted from available_slots.")

    # Attempt to book the exact same slot again (Double booking prevention)
    dup_post = session.post(f"{BASE_URL}/appointments/book", data={
        "hospital_id": 104,
        "doctor_id": 782,
        "appointment_date": test_date,
        "appointment_time": test_slot,
        "patient_name": "Another Patient",
        "phone": "+91 9999999999",
        "reason_for_visit": "Duplicate attempt",
        "notes": "Should fail"
    }, allow_redirects=True)
    assert "already booked" in dup_post.text or "Booking Error" in dup_post.text
    print("PASS: Double booking successfully blocked by backend validation.")

    print("\n--- 5. Testing Booking Page Template (Doctor Selected & Not Selected) ---")
    # Step 1: No doctor selected -> renders clean 2-column cards
    step1_resp = session.get(f"{BASE_URL}/appointments/book?hospital_id=104")
    assert step1_resp.status_code == 200
    assert "doctor-clean-card" in step1_resp.text
    assert "col-12 col-md-6" in step1_resp.text
    assert "View Profile" in step1_resp.text
    assert "Book Appointment" in step1_resp.text
    print("PASS: Step 1 renders clean 2-column doctor cards with [View Profile] and [Book Appointment].")

    # Step 2: Doctor selected -> renders doctor-specific availability and form
    step2_resp = session.get(f"{BASE_URL}/appointments/book?hospital_id=104&doctor_id=782")
    assert step2_resp.status_code == 200
    assert "Dr. Jagjit Kumar Pandey" in step2_resp.text
    assert "Doctor Availability" in step2_resp.text
    assert "Consultation Fee" in step2_resp.text
    assert "500" in step2_resp.text
    assert "Recommended Appointment" in step2_resp.text
    assert "Confirm Appointment" in step2_resp.text
    print("PASS: Step 2 renders doctor-specific details, availability breakdown, consultation fee, recommended slot section, and confirmation flow.")

    print("\n=======================================================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=======================================================")

if __name__ == "__main__":
    run_tests()
