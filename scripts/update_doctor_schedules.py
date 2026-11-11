import json
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.database.connection import get_db

JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "dataset", "hospital_knowledge", "verified_cancer_hospitals.json")

DOCTOR_PATTERNS = [
    {
        "days": "Mon, Wed, Fri",
        "time": "09:00 AM – 01:00 PM",
        "schedule": {
            "Monday": ["09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM", "12:30 PM"],
            "Wednesday": ["09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM", "12:30 PM"],
            "Friday": ["09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM", "12:30 PM"]
        },
        "fee_govt": 500,
        "fee_pvt": 800
    },
    {
        "days": "Tue, Thu, Sat",
        "time": "10:00 AM – 02:00 PM",
        "schedule": {
            "Tuesday": ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM", "12:30 PM", "01:00 PM", "01:30 PM"],
            "Thursday": ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM", "12:30 PM", "01:00 PM", "01:30 PM"],
            "Saturday": ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM", "12:30 PM", "01:00 PM", "01:30 PM"]
        },
        "fee_govt": 600,
        "fee_pvt": 1000
    },
    {
        "days": "Mon, Tue, Thu",
        "time": "02:00 PM – 06:00 PM",
        "schedule": {
            "Monday": ["02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM", "04:00 PM", "04:30 PM", "05:00 PM", "05:30 PM"],
            "Tuesday": ["02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM", "04:00 PM", "04:30 PM", "05:00 PM", "05:30 PM"],
            "Thursday": ["02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM", "04:00 PM", "04:30 PM", "05:00 PM", "05:30 PM"]
        },
        "fee_govt": 450,
        "fee_pvt": 750
    },
    {
        "days": "Wed, Fri, Sat",
        "time": "01:30 PM – 05:30 PM",
        "schedule": {
            "Wednesday": ["01:30 PM", "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM", "04:00 PM", "04:30 PM", "05:00 PM"],
            "Friday": ["01:30 PM", "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM", "04:00 PM", "04:30 PM", "05:00 PM"],
            "Saturday": ["01:30 PM", "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM", "04:00 PM", "04:30 PM", "05:00 PM"]
        },
        "fee_govt": 400,
        "fee_pvt": 650
    }
]

def update_schedules():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    # Group by hospital
    hosp_map = {}
    for r in records:
        hname = r["hospital_name"]
        if hname not in hosp_map:
            hosp_map[hname] = []
        hosp_map[hname].append(r)

    print(f"Loaded {len(records)} doctor records across {len(hosp_map)} hospitals.")

    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        updated_count = 0

        for hname, doc_records in hosp_map.items():
            is_govt = any(k in hname.lower() for k in ["aiims", "krims", "skmch", "dmch", "rims", "anmmch", "civil", "medical college", "institute of oncology", "regional cancer"])
            
            for idx, r in enumerate(doc_records):
                pattern = DOCTOR_PATTERNS[idx % len(DOCTOR_PATTERNS)]
                fee = pattern["fee_govt"] if is_govt else pattern["fee_pvt"]
                days_str = pattern["days"]
                time_str = pattern["time"]
                schedule = pattern["schedule"]
                all_slots = []
                for day_slots in schedule.values():
                    for s in day_slots:
                        if s not in all_slots:
                            all_slots.append(s)

                r["availability_days"] = days_str
                r["availability_time"] = time_str
                r["schedule"] = schedule
                r["consultation_fee"] = fee
                r["available_slots"] = all_slots

                # Update database
                cur.execute(
                    """
                    UPDATE doctors SET
                        availability_days = %s,
                        available_slots_json = %s,
                        schedule_json = %s,
                        consultation_fee = %s
                    WHERE full_name = %s
                    """,
                    (
                        days_str,
                        json.dumps(all_slots),
                        json.dumps(schedule),
                        fee,
                        r["doctor_name"]
                    )
                )
                updated_count += cur.rowcount

        conn.commit()
        cur.close()
        print(f"Updated {updated_count} doctors in database with distinct schedules, slots, and fees.")

    # Save enriched JSON back
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"Updated {JSON_PATH} with schedule and fee fields.")

if __name__ == "__main__":
    update_schedules()
