import json
import logging
from typing import Any, Dict, List, Optional
from app.tools.base_tool import BaseTool, ToolResult
from app.database.connection import get_db

logger = logging.getLogger(__name__)


class DoctorSearchTool(BaseTool):
    """Tool to search and find doctors by specialty, qualification, experience, or hospital."""

    name = "search_doctors"
    description = (
        "Find verified doctors based on specialty (e.g. Cardiologist, Oncologist, Neurologist), "
        "hospital ID, doctor name, or minimum years of experience."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "specialty": {
                "type": "string",
                "description": "Medical specialty (e.g. 'Cardiologist', 'Neurologist', 'Dermatologist', 'General Physician')"
            },
            "hospital_id": {
                "type": "integer",
                "description": "Optional specific hospital ID to filter doctors by"
            },
            "doctor_name": {
                "type": "string",
                "description": "Optional partial or full name of the doctor"
            },
            "min_experience_years": {
                "type": "integer",
                "description": "Optional minimum years of clinical experience",
                "default": 0
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of doctors to return (default 6)",
                "default": 6
            }
        },
        "required": []
    }

    def execute(self, specialty: Optional[str] = None, hospital_id: Optional[int] = None,
                doctor_name: Optional[str] = None, min_experience_years: int = 0,
                limit: int = 6, **kwargs) -> ToolResult:
        try:
            sql = """
                SELECT d.id, d.hospital_id, d.full_name, d.specialty, d.qualification,
                       d.experience_years, d.availability_days, d.available_slots_json,
                       d.consultation_type, h.name as hospital_name, h.city as hospital_city
                FROM doctors d
                JOIN hospitals h ON d.hospital_id = h.id
                WHERE 1=1
            """
            params: List[Any] = []

            if specialty and specialty.strip():
                sql += " AND (LOWER(d.specialty) LIKE %s OR LOWER(d.qualification) LIKE %s)"
                s_pattern = f"%{specialty.strip().lower()}%"
                params.extend([s_pattern, s_pattern])

            if hospital_id:
                sql += " AND d.hospital_id = %s"
                params.append(hospital_id)

            if doctor_name and doctor_name.strip():
                sql += " AND LOWER(d.full_name) LIKE %s"
                params.append(f"%{doctor_name.strip().lower()}%")

            if min_experience_years > 0:
                sql += " AND d.experience_years >= %s"
                params.append(min_experience_years)

            sql += " ORDER BY d.experience_years DESC LIMIT %s"
            params.append(limit)

            with get_db() as conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(sql, tuple(params))
                rows = cur.fetchall() or []
                cur.close()

            doctors = []
            for r in rows:
                slots = []
                try:
                    if r.get("available_slots_json"):
                        slots = json.loads(r["available_slots_json"])
                except Exception:
                    slots = ["09:00 AM", "11:00 AM", "02:00 PM", "04:00 PM"]

                doctors.append({
                    "id": r["id"],
                    "name": r["full_name"],
                    "specialty": r["specialty"],
                    "qualification": r["qualification"],
                    "experience_years": r["experience_years"],
                    "availability_days": r["availability_days"],
                    "available_slots": slots,
                    "consultation_type": r["consultation_type"],
                    "hospital_id": r["hospital_id"],
                    "hospital_name": r["hospital_name"],
                    "hospital_city": r["hospital_city"]
                })

            return ToolResult(
                success=True,
                data={
                    "count": len(doctors),
                    "doctors": doctors,
                    "filters": {
                        "specialty": specialty,
                        "hospital_id": hospital_id,
                        "min_experience": min_experience_years
                    }
                }
            )
        except Exception as exc:
            logger.error("DoctorSearchTool error: %s", exc)
            return ToolResult(success=False, data=None, error=str(exc))
