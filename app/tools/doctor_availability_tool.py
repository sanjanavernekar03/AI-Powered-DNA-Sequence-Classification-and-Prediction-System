import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from app.tools.base_tool import BaseTool, ToolResult
from app.database.connection import get_db

logger = logging.getLogger(__name__)


class DoctorAvailabilityTool(BaseTool):
    """Tool to check available booking slots for a doctor on a specific date."""

    name = "check_doctor_availability"
    description = (
        "Check real-time slot availability for a doctor on a specified date (YYYY-MM-DD). "
        "Returns available slots and flags any conflicting already-booked times."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "doctor_id": {
                "type": "integer",
                "description": "Unique ID of the doctor"
            },
            "date": {
                "type": "string",
                "description": "Appointment date in YYYY-MM-DD format (defaults to tomorrow if omitted)"
            }
        },
        "required": ["doctor_id"]
    }

    def execute(self, doctor_id: int, date_str: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            target_date = date_str or kwargs.get("date")
            if not target_date:
                # default tomorrow
                from datetime import timedelta
                target_date = (date.today() + timedelta(days=1)).isoformat()
            else:
                # normalize/validate format
                try:
                    dt = datetime.strptime(target_date.strip(), "%Y-%m-%d").date()
                    target_date = dt.isoformat()
                except ValueError:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"Invalid date format '{target_date}'. Please use YYYY-MM-DD."
                    )

            with get_db() as conn:
                cur = conn.cursor(dictionary=True)
                # Fetch doctor details
                cur.execute(
                    "SELECT d.*, h.name as hospital_name FROM doctors d "
                    "JOIN hospitals h ON d.hospital_id = h.id WHERE d.id = %s",
                    (doctor_id,)
                )
                doctor = cur.fetchone()
                if not doctor:
                    cur.close()
                    return ToolResult(success=False, data=None, error=f"Doctor with ID {doctor_id} not found.")

                all_slots = []
                try:
                    if doctor.get("available_slots_json"):
                        all_slots = json.loads(doctor["available_slots_json"])
                except Exception:
                    all_slots = ["09:00 AM", "10:30 AM", "02:00 PM", "03:30 PM", "05:00 PM"]

                # Fetch already booked slots for this doctor on this date
                cur.execute(
                    "SELECT appointment_time, status FROM appointments "
                    "WHERE doctor_id = %s AND appointment_date = %s AND status != 'Cancelled'",
                    (doctor_id, target_date)
                )
                booked_rows = cur.fetchall() or []
                cur.close()

            booked_times = {r["appointment_time"].strip().upper() for r in booked_rows}

            available_slots = [s for s in all_slots if s.strip().upper() not in booked_times]

            return ToolResult(
                success=True,
                data={
                    "doctor_id": doctor["id"],
                    "doctor_name": doctor["full_name"],
                    "specialty": doctor["specialty"],
                    "hospital_id": doctor["hospital_id"],
                    "hospital_name": doctor["hospital_name"],
                    "date": target_date,
                    "available_slots": available_slots,
                    "booked_slots": list(booked_times),
                    "is_fully_booked": len(available_slots) == 0
                }
            )
        except Exception as exc:
            logger.error("DoctorAvailabilityTool error: %s", exc)
            return ToolResult(success=False, data=None, error=str(exc))
