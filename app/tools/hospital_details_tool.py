import logging
from typing import Any, Dict, List, Optional
from app.tools.base_tool import BaseTool, ToolResult
from app.database.connection import get_db

logger = logging.getLogger(__name__)


class HospitalDetailsTool(BaseTool):
    """Tool to retrieve full details, contact information, facilities, and departments for a specific hospital."""

    name = "get_hospital_details"
    description = (
        "Get detailed information for a specific hospital by ID or exact name. "
        "Returns address, contact phone, operating hours, geolocation, and list of available specialties."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "hospital_id": {
                "type": "integer",
                "description": "Unique ID of the hospital in the database"
            },
            "hospital_name": {
                "type": "string",
                "description": "Optional name of the hospital if ID is not known"
            }
        },
        "required": []
    }

    def execute(self, hospital_id: Optional[int] = None, hospital_name: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            if not hospital_id and not hospital_name:
                return ToolResult(
                    success=False,
                    data=None,
                    error="Either hospital_id or hospital_name must be provided."
                )

            with get_db() as conn:
                cur = conn.cursor(dictionary=True)
                if hospital_id:
                    cur.execute("SELECT * FROM hospitals WHERE id = %s", (hospital_id,))
                else:
                    cur.execute(
                        "SELECT * FROM hospitals WHERE LOWER(name) LIKE %s LIMIT 1",
                        (f"%{hospital_name.strip().lower()}%",)
                    )
                hosp = cur.fetchone()

                if not hosp:
                    cur.close()
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"Hospital not found for id={hospital_id} name={hospital_name}"
                    )

                h_id = hosp["id"]
                # Fetch specialties and doctor count
                cur.execute(
                    "SELECT specialty, COUNT(*) as doc_count FROM doctors WHERE hospital_id = %s GROUP BY specialty",
                    (h_id,)
                )
                departments = cur.fetchall() or []

                cur.close()

            details = {
                "id": hosp["id"],
                "name": hosp["name"],
                "address": hosp["address"],
                "city": hosp.get("city") or "",
                "state": hosp.get("state") or "",
                "postal_code": hosp.get("postal_code") or "",
                "phone": hosp.get("phone") or "Available at front desk",
                "opening_hours": hosp.get("opening_hours") or "24/7",
                "latitude": hosp.get("latitude"),
                "longitude": hosp.get("longitude"),
                "departments": departments,
                "total_doctors": sum(d["doc_count"] for d in departments)
            }

            return ToolResult(success=True, data=details)
        except Exception as exc:
            logger.error("HospitalDetailsTool error: %s", exc)
            return ToolResult(success=False, data=None, error=str(exc))
