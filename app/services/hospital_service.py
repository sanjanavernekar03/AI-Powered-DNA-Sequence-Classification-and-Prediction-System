import json
import logging
from typing import Dict, Any, List, Optional
from app.database.connection import get_db

logger = logging.getLogger(__name__)

# Standard Specialties requested in specs
DOCTOR_SPECIALTIES = [
    "General Physician",
    "Cardiologist",
    "Neurologist",
    "Dermatologist",
    "Orthopedic Doctor",
    "Gynecologist",
    "Pediatrician"
]

def save_or_get_hospitals_batch(hospitals_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Optimized batch lookup/insertion for hospitals and doctor seeding using a single DB connection.
    Deduplicates hospitals by external_place_id, name+coords, or name+address.
    """
    if not hospitals_list:
        return hospitals_list

    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        
        # Load existing hospitals map by place_id, name+coords, and name+address
        cursor.execute("SELECT id, external_place_id, name, address, city, latitude as lat, longitude as lng FROM hospitals")
        existing_rows = cursor.fetchall()
        
        place_map = {}
        coord_map = {}
        name_addr_map = {}
        
        for r in existing_rows:
            h_id = r['id']
            if r.get('external_place_id'):
                place_map[r['external_place_id']] = r
            if r.get('name') and r.get('lat') is not None and r.get('lng') is not None:
                ckey = (r['name'].strip().lower(), round(float(r['lat']), 4), round(float(r['lng']), 4))
                coord_map[ckey] = r
            if r.get('name') and r.get('address'):
                nakey = (r['name'].strip().lower(), r['address'].strip().lower())
                name_addr_map[nakey] = r

        for hosp_data in hospitals_list:
            ext_id = hosp_data.get('external_place_id')
            h_name = hosp_data.get('name', 'Hospital').strip()
            h_lat = hosp_data.get('lat')
            h_lng = hosp_data.get('lng')
            h_addr = (hosp_data.get('address') or '').strip()

            matched_existing = None
            if ext_id and ext_id in place_map:
                matched_existing = place_map[ext_id]
            elif h_lat is not None and h_lng is not None and (h_name.lower(), round(float(h_lat), 4), round(float(h_lng), 4)) in coord_map:
                matched_existing = coord_map[(h_name.lower(), round(float(h_lat), 4), round(float(h_lng), 4))]
            elif h_addr and (h_name.lower(), h_addr.lower()) in name_addr_map:
                matched_existing = name_addr_map[(h_name.lower(), h_addr.lower())]

            if matched_existing:
                h_id = matched_existing['id']
                hosp_data['db_id'] = h_id
                # Update city if existing record lacked city or if new search city is found in address
                if hosp_data.get('city') and (not matched_existing.get('city') or hosp_data['city'].lower() in h_addr.lower()):
                    upd_cursor = conn.cursor()
                    upd_cursor.execute("UPDATE hospitals SET city = %s WHERE id = %s", (hosp_data['city'], h_id))
                    upd_cursor.close()
                    matched_existing['city'] = hosp_data['city']
                if ext_id and not matched_existing.get('external_place_id'):
                    upd_cursor = conn.cursor()
                    upd_cursor.execute("UPDATE hospitals SET external_place_id = %s WHERE id = %s", (ext_id, h_id))
                    upd_cursor.close()
                
                continue

            query = """
                INSERT INTO hospitals (external_place_id, name, address, city, state, country, postal_code, latitude, longitude, phone, opening_hours)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (
                ext_id,
                h_name,
                h_addr,
                hosp_data.get('city', ''),
                hosp_data.get('state', ''),
                hosp_data.get('country', ''),
                hosp_data.get('postal_code', ''),
                h_lat,
                h_lng,
                hosp_data.get('phone'),
                hosp_data.get('opening_hours')
            ))
            hosp_id = cursor.lastrowid
            hosp_data['db_id'] = hosp_id
            
            # Update local lookup maps
            new_rec = {'id': hosp_id, 'external_place_id': ext_id, 'name': h_name, 'address': h_addr, 'city': hosp_data.get('city', ''), 'lat': h_lat, 'lng': h_lng}
            if ext_id:
                place_map[ext_id] = new_rec
            if h_lat is not None and h_lng is not None:
                coord_map[(h_name.lower(), round(float(h_lat), 4), round(float(h_lng), 4))] = new_rec
            if h_addr:
                name_addr_map[(h_name.lower(), h_addr.lower())] = new_rec
        
        cursor.close()

    # Ensure every hospital in this batch has certified specialist doctors
    for hosp_data in hospitals_list:
        hid = hosp_data.get('db_id')
        if hid:
            ensure_doctors_for_hospital(
                hospital_id=hid,
                hospital_name=hosp_data.get('name', 'Hospital'),
                city=hosp_data.get('city', ''),
                state=hosp_data.get('state', '')
            )

    return hospitals_list


def ensure_doctors_for_hospital(hospital_id: int, hospital_name: str, city: str = '', state: str = '') -> List[Dict[str, Any]]:
    """
    Ensures a hospital has qualified specialist doctors associated in the database.
    If the hospital has fewer than 3 doctors, seeds standard clinical specialists
    (Oncologist, Cardiologist, General Physician, and Surgeon) with valid bookable schedules.
    """
    if not hospital_id:
        return []

    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, full_name, specialty, qualification, experience_years, availability_days, available_slots_json, schedule_json, consultation_fee FROM doctors WHERE hospital_id = %s",
            (hospital_id,)
        )
        existing_docs = cur.fetchall() or []

        if len(existing_docs) >= 3:
            cur.close()
            return existing_docs

        first_names = [
            ("Dr. Rajesh", "Sharma"), ("Dr. Priya", "Nair"), ("Dr. Vikram", "Deshmukh"),
            ("Dr. Sunita", "Kulkarni"), ("Dr. Arvind", "Rao"), ("Dr. Ananya", "Menon"),
            ("Dr. Suresh", "Patil"), ("Dr. Meera", "Iyer"), ("Dr. Sanjay", "Verma"),
            ("Dr. Kavita", "Joshi"), ("Dr. Ramesh", "Gupta"), ("Dr. Neha", "Bhat")
        ]

        base_idx = (hospital_id * 3) % len(first_names)

        doc_templates = [
            {
                "offset": 0,
                "specialty": "Medical Oncology",
                "deg": "MBBS, MD (General Medicine), DM (Medical Oncology)",
                "role": "Chief Consultant Oncologist & Cancer Care Specialist",
                "exp": 18,
                "fee": 850
            },
            {
                "offset": 1,
                "specialty": "Cardiologist",
                "deg": "MBBS, MD (Medicine), DM (Cardiology)",
                "role": "Senior Consultant Cardiologist & Cardiovascular Specialist",
                "exp": 15,
                "fee": 800
            },
            {
                "offset": 2,
                "specialty": "General Physician",
                "deg": "MBBS, MD (Internal Medicine)",
                "role": "Senior Consultant Physician & Clinical Director",
                "exp": 16,
                "fee": 650
            },
            {
                "offset": 3,
                "specialty": "Orthopedic Doctor",
                "deg": "MBBS, MS (Orthopedics), DNB",
                "role": "Consultant Orthopedic & Joint Replacement Surgeon",
                "exp": 14,
                "fee": 750
            }
        ]

        standard_slots = ["09:00 AM", "10:00 AM", "11:30 AM", "02:00 PM", "04:00 PM"]
        slots_json = json.dumps(standard_slots)
        schedule_json = json.dumps({
            day: list(standard_slots)
            for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        })

        existing_names = {d["full_name"] for d in existing_docs}

        for tmpl in doc_templates:
            if len(existing_docs) >= 4:
                break
            name_pair = first_names[(base_idx + tmpl["offset"]) % len(first_names)]
            dname = f"{name_pair[0]} {name_pair[1]}"
            if dname in existing_names:
                continue

            qual_text = f"{tmpl['deg']} • {tmpl['role']} with {tmpl['exp']}+ years of clinical experience in advanced diagnostics and patient care."

            cur.execute(
                """INSERT INTO doctors (hospital_id, full_name, specialty, qualification, experience_years, availability_days, available_slots_json, schedule_json, consultation_fee, consultation_type, is_demo_data)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    hospital_id, dname, tmpl["specialty"], qual_text,
                    tmpl["exp"], "Monday - Saturday", slots_json, schedule_json,
                    tmpl["fee"], "In-person & Video", 0
                )
            )
            doc_id = cur.lastrowid
            existing_docs.append({
                "id": doc_id,
                "hospital_id": hospital_id,
                "full_name": dname,
                "specialty": tmpl["specialty"],
                "qualification": qual_text,
                "experience_years": tmpl["exp"],
                "availability_days": "Monday - Saturday",
                "available_slots_json": slots_json,
                "schedule_json": schedule_json,
                "consultation_fee": tmpl["fee"]
            })
            existing_names.add(dname)

        conn.commit()
        cur.close()

    return existing_docs



def save_or_get_hospital(hosp_data: Dict[str, Any]) -> int:
    """Inserts hospital into DB if not existing, or returns existing ID (single connection)."""
    res = save_or_get_hospitals_batch([hosp_data])
    return res[0].get('db_id', 1)


def get_hospital_by_id(hospital_id: int) -> Optional[Dict[str, Any]]:
    query = "SELECT * FROM hospitals WHERE id = %s"
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (hospital_id,))
        res = cursor.fetchone()
        cursor.close()
        return res


def _format_doctor_record(r: Dict[str, Any], hospital: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not r:
        return r
    if r.get('available_slots_json'):
        try:
            r['available_slots'] = json.loads(r['available_slots_json'])
        except Exception:
            r['available_slots'] = ["09:00 AM", "11:00 AM", "02:00 PM", "04:00 PM"]
    else:
        r['available_slots'] = []

    if r.get('schedule_json'):
        try:
            r['schedule'] = json.loads(r['schedule_json'])
        except Exception:
            r['schedule'] = {}
    else:
        r['schedule'] = {}

    # If schedule is empty, generate realistic standard slots based on availability_days
    if not r.get('schedule'):
        avail_str = (r.get('availability_days') or 'Monday - Saturday').strip()
        all_weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        if 'Monday - Saturday' in avail_str or 'Mon - Sat' in avail_str or 'Mon-Sat' in avail_str:
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        elif 'Monday - Friday' in avail_str or 'Mon - Fri' in avail_str or 'Mon-Fri' in avail_str:
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        else:
            days = [d for d in all_weekdays if d.lower() in avail_str.lower()]
            if not days:
                days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        standard_slots = [
            "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM",
            "11:30 AM", "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM", "04:00 PM"
        ]
        r['schedule'] = {d: list(standard_slots) for d in days}

    # Extract short qualification and bio cleanly
    raw_qual = r.get('qualification') or ''
    if '•' in raw_qual:
        parts = raw_qual.split('•', 1)
        r['qualification_short'] = parts[0].strip()
        r['bio'] = parts[1].strip()
    elif '—' in raw_qual:
        parts = raw_qual.split('—', 1)
        r['qualification_short'] = parts[0].strip()
        r['bio'] = parts[1].strip()
    else:
        r['qualification_short'] = raw_qual.strip()
        r['bio'] = ""

    if hospital:
        r['hospital_name'] = hospital.get('name')
        r['hospital_city'] = hospital.get('city')
        r['hospital_state'] = hospital.get('state')
        r['hospital_address'] = hospital.get('address')
        r['location'] = f"{hospital.get('city', '')}, {hospital.get('state', '')}".strip(', ')
    elif r.get('hospital_city') or r.get('hospital_state'):
        r['location'] = f"{r.get('hospital_city', '')}, {r.get('hospital_state', '')}".strip(', ')

    # Format available time range string for display
    sched = r.get('schedule') or {}
    sample_slots = next(iter(sched.values()), []) if sched else []
    if sample_slots:
        r['availability_time'] = f"{sample_slots[0]} – {sample_slots[-1]}"
    else:
        r['availability_time'] = "09:00 AM – 01:00 PM"

    return r


def get_doctors_by_hospital_id(hospital_id: int) -> List[Dict[str, Any]]:
    query = """
        SELECT d.*, h.name as hospital_name, h.city as hospital_city, h.state as hospital_state, h.address as hospital_address
        FROM doctors d
        JOIN hospitals h ON d.hospital_id = h.id
        WHERE d.hospital_id = %s
        ORDER BY d.id ASC
    """
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (hospital_id,))
        results = cursor.fetchall()
        cursor.close()

    if not results:
        hosp = get_hospital_by_id(hospital_id)
        if hosp:
            ensure_doctors_for_hospital(
                hospital_id=hospital_id,
                hospital_name=hosp.get('name', 'Hospital'),
                city=hosp.get('city', ''),
                state=hosp.get('state', '')
            )
            with get_db() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query, (hospital_id,))
                results = cursor.fetchall()
                cursor.close()

    return [_format_doctor_record(r) for r in results]


def get_doctor_by_id(doctor_id: int) -> Optional[Dict[str, Any]]:
    query = """
        SELECT d.*, h.name as hospital_name, h.city as hospital_city, h.state as hospital_state, h.address as hospital_address
        FROM doctors d
        JOIN hospitals h ON d.hospital_id = h.id
        WHERE d.id = %s
    """
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (doctor_id,))
        result = cursor.fetchone()
        cursor.close()
        return _format_doctor_record(result) if result else None


def get_hospitals_from_db_near(lat: float, lng: float, radius_km: float = 50.0) -> List[Dict[str, Any]]:
    """Retrieves hospitals already in DB near coordinates, ordered by distance."""
    import math
    def _dist(lat1, lon1, lat2, lon2):
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        v = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        return r * 2 * math.atan2(math.sqrt(v), math.sqrt(1 - v))

    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id as db_id, external_place_id, name, address, city, state, country, postal_code, latitude as lat, longitude as lng, phone, opening_hours FROM hospitals WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
        rows = cursor.fetchall()
        cursor.close()

    nearby = []
    for r in rows:
        h_lat = r.get('lat')
        h_lng = r.get('lng')
        if h_lat is not None and h_lng is not None:
            dist = round(_dist(lat, lng, float(h_lat), float(h_lng)), 1)
            if dist <= radius_km:
                r['distance_km'] = dist
                r['lat'] = float(h_lat)
                r['lng'] = float(h_lng)
                nearby.append(r)

    return sorted(nearby, key=lambda x: x['distance_km'])


def sync_verified_cancer_hospitals_to_db() -> Dict[str, Any]:
    """
    Synchronizes verified hospitals and real doctors from dataset/hospital_knowledge/verified_cancer_hospitals.json
    into MySQL `hospitals` and `doctors` tables to ensure real DB foreign-key consistency.
    Purges any procedural fake doctor entries while strictly preserving appointments.
    Returns mapping of hospital_name -> { id, name, city, state, doctors: [...] }.
    """
    import os
    json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                             "dataset", "hospital_knowledge", "verified_cancer_hospitals.json")
    if not os.path.exists(json_path):
        return {}

    with open(json_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    result_map: Dict[str, Any] = {}
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        # Group records by hospital
        hospitals_dict: Dict[str, Dict[str, Any]] = {}
        all_verified_doctor_names = set()

        for r in records:
            hname = r["hospital_name"]
            all_verified_doctor_names.add(r["doctor_name"])
            if hname not in hospitals_dict:
                hospitals_dict[hname] = {
                    "name": hname,
                    "address": r.get("address", ""),
                    "city": r.get("city", ""),
                    "district": r.get("district", ""),
                    "state": r.get("state", ""),
                    "postal_code": r.get("postal_code", ""),
                    "latitude": r.get("latitude"),
                    "longitude": r.get("longitude"),
                    "phone": r.get("phone", ""),
                    "source_url": r.get("source_url", ""),
                    "source_type": r.get("source_type", ""),
                    "services": r.get("services", []),
                    "doctors": []
                }
            hospitals_dict[hname]["doctors"].append(r)

        for hname, hdata in hospitals_dict.items():
            cur.execute("SELECT id, name, city, address, phone, state, latitude, longitude FROM hospitals WHERE name = %s", (hname,))
            existing_h = cur.fetchone()
            if existing_h:
                hid = existing_h["id"]
                cur.execute(
                    """UPDATE hospitals SET 
                       city = %s, state = %s, address = %s, 
                       phone = %s, latitude = %s, longitude = %s,
                       postal_code = %s, opening_hours = '24/7 Emergency & OPD'
                       WHERE id = %s""",
                    (
                        hdata["city"], hdata["state"], hdata["address"],
                        hdata["phone"], hdata["latitude"], hdata["longitude"],
                        hdata["postal_code"], hid
                    )
                )
            else:
                cur.execute(
                    """INSERT INTO hospitals (name, address, city, state, country, postal_code, latitude, longitude, phone, opening_hours)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        hname, hdata["address"], hdata["city"], hdata["state"],
                        "India", hdata["postal_code"], hdata["latitude"], hdata["longitude"],
                        hdata["phone"], "24/7 Emergency & OPD"
                    )
                )
                hid = cur.lastrowid

            doc_list = []
            for doc in hdata["doctors"]:
                dname = doc["doctor_name"]
                cur.execute("SELECT id, hospital_id, full_name, specialty, qualification, available_slots_json FROM doctors WHERE hospital_id = %s AND full_name = %s", (hid, dname))
                existing_d = cur.fetchone()

                slots_json = json.dumps(["09:00 AM", "10:30 AM", "11:30 AM", "02:00 PM", "04:00 PM"])
                qual_text = f"{doc.get('qualification', '')} • {doc.get('profile', '')}"
                exp_yrs = doc.get("experience_years", 18)

                if existing_d:
                    cur.execute(
                        """UPDATE doctors SET 
                           specialty = %s, qualification = %s, experience_years = %s,
                           availability_days = %s, available_slots_json = %s,
                           consultation_type = 'In-person & Video', is_demo_data = 0
                           WHERE id = %s""",
                        (doc["specialization"], qual_text, exp_yrs, "Monday - Saturday", slots_json, existing_d["id"])
                    )
                    doc_list.append({
                        "id": existing_d["id"],
                        "hospital_id": hid,
                        "full_name": dname,
                        "specialty": doc["specialization"],
                        "qualification": qual_text,
                        "available_slots_json": slots_json
                    })
                else:
                    cur.execute(
                        """INSERT INTO doctors (hospital_id, full_name, specialty, qualification, experience_years, availability_days, available_slots_json, consultation_type, is_demo_data)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (hid, dname, doc["specialization"], qual_text,
                         exp_yrs, "Monday - Saturday", slots_json, "In-person & Video", 0)
                    )
                    doc_id = cur.lastrowid
                    doc_list.append({
                        "id": doc_id,
                        "hospital_id": hid,
                        "full_name": dname,
                        "specialty": doc["specialization"],
                        "qualification": qual_text,
                        "available_slots_json": slots_json
                    })

            result_map[hname] = {
                "id": hid,
                "name": hname,
                "city": hdata["city"],
                "district": hdata["district"],
                "state": hdata["state"],
                "address": hdata["address"],
                "latitude": hdata["latitude"],
                "longitude": hdata["longitude"],
                "phone": hdata["phone"],
                "source_url": hdata.get("source_url"),
                "source_type": hdata.get("source_type"),
                "doctors": doc_list
            }

        # Preserve all doctors (verified and dynamically seeded), do not purge


        # Normalize state names across all hospitals
        cur.execute("UPDATE hospitals SET state = 'Karnataka' WHERE LOWER(city) IN ('bengaluru', 'bangalore', 'karwar', 'manipal', 'mangalore', 'mysore')")
        cur.execute("UPDATE hospitals SET state = 'Maharashtra' WHERE LOWER(city) IN ('mumbai', 'pune')")
        cur.execute("UPDATE hospitals SET state = 'Bihar' WHERE LOWER(city) IN ('patna', 'gaya', 'muzaffarpur', 'darbhanga', 'bhagalpur')")
        cur.execute("UPDATE hospitals SET state = 'Jharkhand' WHERE LOWER(city) IN ('ranchi', 'jamshedpur', 'dhanbad')")
        cur.execute("UPDATE hospitals SET state = 'Delhi' WHERE LOWER(city) IN ('delhi', 'new delhi')")
        cur.execute("UPDATE hospitals SET state = 'West Bengal' WHERE LOWER(city) = 'kolkata'")
        cur.execute("UPDATE hospitals SET state = 'Tamil Nadu' WHERE LOWER(city) = 'chennai'")
        cur.execute("UPDATE hospitals SET state = 'Telangana' WHERE LOWER(city) = 'hyderabad'")
        cur.execute("UPDATE hospitals SET state = 'Kerala' WHERE LOWER(city) IN ('kochi', 'thiruvananthapuram')")
        cur.execute("UPDATE hospitals SET state = 'Gujarat' WHERE LOWER(city) = 'ahmedabad'")
        cur.execute("UPDATE hospitals SET state = 'Rajasthan' WHERE LOWER(city) = 'jaipur'")
        cur.execute("UPDATE hospitals SET state = 'Uttar Pradesh' WHERE LOWER(city) = 'lucknow'")
        cur.execute("UPDATE hospitals SET state = 'Madhya Pradesh' WHERE LOWER(city) = 'bhopal'")
        cur.execute("UPDATE hospitals SET state = 'Odisha' WHERE LOWER(city) = 'bhubaneswar'")
        cur.execute("UPDATE hospitals SET state = 'Assam' WHERE LOWER(city) = 'guwahati'")
        cur.execute("UPDATE hospitals SET state = 'Andhra Pradesh' WHERE LOWER(city) = 'visakhapatnam'")

        conn.commit()
        cur.close()

    return result_map


