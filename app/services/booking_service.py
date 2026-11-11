import datetime
import json
import logging
from typing import Dict, Any, List, Optional
from app.database.connection import get_db

logger = logging.getLogger(__name__)

def create_appointment(
    user_id: int,
    hospital_id: int,
    doctor_id: int,
    appointment_date_str: str,
    appointment_time: str,
    reason_for_visit: str,
    patient_name: str,
    phone: str,
    patient_email: Optional[str] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a new doctor appointment with validation.
    Checks for past dates and duplicate bookings for the same doctor at the same date & time slot.
    """
    # 1. Date Validation
    appt_date = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            appt_date = datetime.datetime.strptime(str(appointment_date_str).strip(), fmt).date()
            break
        except ValueError:
            pass
    if not appt_date:
        return {"success": False, "error": "Invalid date format. Please choose a valid date from the calendar."}
    if appt_date < datetime.date.today():
        return {"success": False, "error": "Appointment date cannot be in the past."}

    # If patient_email is empty, attempt to resolve from user table
    if not patient_email or not patient_email.strip():
        try:
            with get_db() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
                user_rec = cursor.fetchone()
                cursor.close()
                if user_rec and user_rec.get('email'):
                    patient_email = user_rec['email']
        except Exception as exc:
            logger.warning("Could not fetch user email: %s", exc)
    final_email = (patient_email or "").strip()

    # 2. Check for duplicate booking for same doctor, date, and slot
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)

        # Check that doctor belongs to the requested hospital
        cursor.execute("SELECT id, hospital_id, full_name, schedule_json, consultation_fee, availability_days FROM doctors WHERE id = %s", (doctor_id,))
        doc_rec = cursor.fetchone()
        if not doc_rec:
            cursor.close()
            return {"success": False, "error": "Doctor not found."}
        if doc_rec.get("hospital_id") != hospital_id:
            cursor.close()
            return {"success": False, "error": "Selected doctor does not belong to the chosen hospital."}

        # Validate doctor schedule for weekday
        weekday_name = appt_date.strftime("%A")
        sched = {}
        if doc_rec.get("schedule_json"):
            try:
                sched = json.loads(doc_rec["schedule_json"])
            except Exception:
                sched = {}
        if not sched:
            avail_str = (doc_rec.get("availability_days") or "Monday - Saturday").strip()
            all_weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            if 'Monday - Saturday' in avail_str or 'Mon - Sat' in avail_str:
                w_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            elif 'Monday - Friday' in avail_str or 'Mon - Fri' in avail_str:
                w_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
            else:
                w_days = [d for d in all_weekdays if d.lower() in avail_str.lower()] or ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            standard_slots = [
                "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM",
                "11:30 AM", "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM", "04:00 PM"
            ]
            sched = {d: list(standard_slots) for d in w_days}

        day_slots = sched.get(weekday_name, [])
        if weekday_name not in sched or not day_slots:
            cursor.close()
            avail_days = doc_rec.get("availability_days") or "other days"
            return {"success": False, "error": f"{doc_rec['full_name']} is not scheduled on {weekday_name}s. Available days: {avail_days}."}
        if appointment_time not in day_slots:
            cursor.close()
            return {"success": False, "error": f"The selected time slot ({appointment_time}) is not in {doc_rec['full_name']}'s schedule for {weekday_name}."}

        cursor.execute(
            """
            SELECT id FROM appointments 
            WHERE doctor_id = %s AND appointment_date = %s AND appointment_time = %s AND status != 'Cancelled'
            """,
            (doctor_id, appt_date, appointment_time)
        )
        existing = cursor.fetchone()
        if existing:
            cursor.close()
            return {"success": False, "error": f"{doc_rec['full_name']} is already booked for {appointment_time} on {appt_date.strftime('%d %B %Y')}. Please choose another slot."}

        # 3. Create Appointment with fee
        fee = doc_rec.get("consultation_fee")
        query = """
            INSERT INTO appointments (user_id, hospital_id, doctor_id, appointment_date, appointment_time, reason_for_visit, patient_name, patient_email, phone, notes, status, consultation_fee)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Confirmed', %s)
        """
        cursor = conn.cursor()
        cursor.execute(query, (
            user_id,
            hospital_id,
            doctor_id,
            appt_date,
            appointment_time,
            reason_for_visit.strip(),
            patient_name.strip(),
            final_email,
            phone.strip(),
            notes.strip() if notes else None,
            fee
        ))
        appt_id = cursor.lastrowid
        cursor.close()

        return {"success": True, "appointment_id": appt_id, "consultation_fee": fee}


def check_and_update_past_appointments(user_id: Optional[int] = None) -> None:
    """
    Checks appointments whose date/time has passed.
    If the status is active ('Confirmed', 'Pending', 'Scheduled', 'Approved'),
    automatically updates the status to 'Completed'.
    """
    now = datetime.datetime.now()
    today = now.date()

    query = """
        SELECT id, appointment_date, appointment_time, status 
        FROM appointments 
        WHERE status IN ('Confirmed', 'Pending', 'Scheduled', 'Approved')
    """
    params = []
    if user_id:
        query += " AND user_id = %s"
        params.append(user_id)

    try:
        with get_db() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            cursor.close()

            completed_ids = []
            for r in rows:
                appt_date = r.get('appointment_date')
                if isinstance(appt_date, str):
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                        try:
                            appt_date = datetime.datetime.strptime(appt_date.strip(), fmt).date()
                            break
                        except Exception:
                            pass

                is_past = False
                if appt_date and isinstance(appt_date, datetime.date):
                    if appt_date < today:
                        is_past = True
                    elif appt_date == today:
                        time_str = (r.get('appointment_time') or '').strip()
                        parsed_time = None
                        for t_fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%H:%M"):
                            try:
                                parsed_time = datetime.datetime.strptime(time_str, t_fmt).time()
                                break
                            except Exception:
                                pass
                        if parsed_time and parsed_time <= now.time():
                            is_past = True

                if is_past:
                    completed_ids.append(r['id'])

            if completed_ids:
                format_strings = ','.join(['%s'] * len(completed_ids))
                cursor_up = conn.cursor()
                cursor_up.execute(
                    f"UPDATE appointments SET status = 'Completed' WHERE id IN ({format_strings})",
                    tuple(completed_ids)
                )
                cursor_up.close()
                logger.info("Automatically marked past appointments as Completed: %s", completed_ids)
    except Exception as exc:
        logger.warning("Error checking and updating past appointments: %s", exc)


def get_user_appointments(user_id: int) -> List[Dict[str, Any]]:
    # 1. Automatically reconcile past appointments to 'Completed' in MySQL
    check_and_update_past_appointments(user_id)

    query = """
        SELECT a.*, h.name as hospital_name, h.address as hospital_address, d.full_name as doctor_name, d.specialty as doctor_specialty, d.photo_url as doctor_photo
        FROM appointments a
        JOIN hospitals h ON a.hospital_id = h.id
        JOIN doctors d ON a.doctor_id = d.id
        WHERE a.user_id = %s
        ORDER BY a.appointment_date DESC, a.created_at DESC
    """
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (user_id,))
        results = cursor.fetchall()
        cursor.close()

    now = datetime.datetime.now()
    today = now.date()

    for a in results:
        appt_date = a.get('appointment_date')
        if isinstance(appt_date, str):
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    appt_date = datetime.datetime.strptime(appt_date.strip(), fmt).date()
                    break
                except Exception:
                    pass

        is_past = False
        if appt_date and isinstance(appt_date, datetime.date):
            if appt_date < today:
                is_past = True
            elif appt_date == today:
                time_str = (a.get('appointment_time') or '').strip()
                parsed_time = None
                for t_fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%H:%M"):
                    try:
                        parsed_time = datetime.datetime.strptime(time_str, t_fmt).time()
                        break
                    except Exception:
                        pass
                if parsed_time and parsed_time <= now.time():
                    is_past = True

        a['is_past'] = is_past
        # If date/time has passed and not cancelled, display status as Completed
        if is_past and (a.get('status') or '').strip().lower() in ['confirmed', 'approved', 'pending', 'scheduled']:
            a['status'] = 'Completed'

    return results


def cancel_user_appointment(appointment_id: int, user_id: int) -> bool:
    # Cannot cancel an appointment whose date/time has already passed or is Completed
    now = datetime.datetime.now()
    today = now.date()
    try:
        with get_db() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT appointment_date, appointment_time, status FROM appointments WHERE id = %s AND user_id = %s", (appointment_id, user_id))
            row = cursor.fetchone()
            cursor.close()
            if not row:
                return False
            if (row.get('status') or '').strip().lower() in ['completed', 'cancelled']:
                return False
            appt_date = row.get('appointment_date')
            if isinstance(appt_date, str):
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                    try:
                        appt_date = datetime.datetime.strptime(appt_date.strip(), fmt).date()
                        break
                    except Exception:
                        pass
            if appt_date and isinstance(appt_date, datetime.date) and appt_date < today:
                return False

            cursor_up = conn.cursor()
            cursor_up.execute("UPDATE appointments SET status = 'Cancelled' WHERE id = %s AND user_id = %s", (appointment_id, user_id))
            affected = cursor_up.rowcount > 0
            cursor_up.close()
            return affected
    except Exception as exc:
        logger.error("Error cancelling appointment: %s", exc)
        return False
