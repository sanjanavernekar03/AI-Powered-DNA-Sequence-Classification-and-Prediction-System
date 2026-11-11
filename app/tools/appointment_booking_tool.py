import logging
from typing import Any, Dict, Optional
from app.tools.base_tool import BaseTool, ToolResult
from app.services.booking_service import create_appointment

logger = logging.getLogger(__name__)


class AppointmentBookingTool(BaseTool):
    """Tool to create and confirm an appointment with a doctor at a hospital."""

    name = "book_appointment"
    description = (
        "Book a medical consultation appointment with a doctor. "
        "Requires user_id, hospital_id, doctor_id, appointment_date (YYYY-MM-DD), "
        "appointment_time (e.g. '10:00 AM'), patient_name, and contact phone."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "user_id": {
                "type": "integer",
                "description": "ID of the registered patient user"
            },
            "hospital_id": {
                "type": "integer",
                "description": "Hospital ID where consultation is scheduled"
            },
            "doctor_id": {
                "type": "integer",
                "description": "Doctor ID"
            },
            "appointment_date": {
                "type": "string",
                "description": "Consultation date in YYYY-MM-DD format"
            },
            "appointment_time": {
                "type": "string",
                "description": "Time slot string (e.g. '09:00 AM', '11:00 AM', '02:00 PM')"
            },
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient"
            },
            "phone": {
                "type": "string",
                "description": "Patient telephone/mobile number"
            },
            "patient_email": {
                "type": "string",
                "description": "Patient email address for confirmations"
            },
            "reason_for_visit": {
                "type": "string",
                "description": "Clinical concern, symptoms, or genetic analysis follow-up reason"
            },
            "notes": {
                "type": "string",
                "description": "Optional additional clinical or special notes"
            }
        },
        "required": ["user_id", "hospital_id", "doctor_id", "appointment_date", "appointment_time", "patient_name", "phone"]
    }

    def execute(self, user_id: int, hospital_id: int, doctor_id: int,
                appointment_date: str, appointment_time: str,
                patient_name: str, phone: str,
                patient_email: Optional[str] = "",
                reason_for_visit: Optional[str] = "Medical Consultation",
                notes: Optional[str] = "", **kwargs) -> ToolResult:
        try:
            result = create_appointment(
                user_id=int(user_id),
                hospital_id=int(hospital_id),
                doctor_id=int(doctor_id),
                appointment_date_str=str(appointment_date).strip(),
                appointment_time=str(appointment_time).strip(),
                reason_for_visit=str(reason_for_visit or "Consultation").strip(),
                patient_name=str(patient_name).strip(),
                phone=str(phone).strip(),
                patient_email=str(patient_email or "").strip(),
                notes=str(notes or "").strip()
            )

            if result.get("success"):
                return ToolResult(
                    success=True,
                    data={
                        "appointment_id": result.get("appointment_id"),
                        "status": "Confirmed",
                        "doctor_id": doctor_id,
                        "hospital_id": hospital_id,
                        "date": appointment_date,
                        "time": appointment_time,
                        "patient_name": patient_name,
                        "message": "Appointment booked and confirmed successfully."
                    }
                )
            else:
                return ToolResult(
                    success=False,
                    data=None,
                    error=result.get("error", "Unable to complete booking.")
                )
        except Exception as exc:
            logger.error("AppointmentBookingTool error: %s", exc)
            return ToolResult(success=False, data=None, error=str(exc))
