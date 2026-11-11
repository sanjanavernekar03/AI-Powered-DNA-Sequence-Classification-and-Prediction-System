import logging
from typing import Any, Dict, List, Optional
from app.tools.base_tool import BaseTool, ToolResult
from app.database.connection import get_db
from app.services.maps_service import geocode_address, search_nearby_hospitals
from app.services.hospital_service import save_or_get_hospitals_batch

logger = logging.getLogger(__name__)


class HospitalSearchTool(BaseTool):
    """Tool to search hospitals by city, address, coordinates, or specialty."""

    name = "search_hospitals"
    description = (
        "Search for hospitals near a city, address, or GPS coordinates. "
        "Optionally filters or ranks by medical specialty."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City or address to search near (e.g. 'Bengaluru', 'Manipal', 'Mumbai')"
            },
            "lat": {
                "type": "number",
                "description": "Optional latitude float"
            },
            "lng": {
                "type": "number",
                "description": "Optional longitude float"
            },
            "specialty": {
                "type": "string",
                "description": "Optional medical specialty required (e.g. 'Cardiology', 'Oncology', 'Neurology')"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5)",
                "default": 5
            }
        },
        "required": []
    }

    def execute(self, location: Optional[str] = None, lat: Optional[float] = None,
                lng: Optional[float] = None, specialty: Optional[str] = None,
                limit: int = 5, **kwargs) -> ToolResult:
        try:
            from app.services.location_filter import detect_location_intent, is_hospital_matching_location

            loc_intent = detect_location_intent(location) if location else None
            is_explicit = loc_intent and loc_intent.get("is_explicit")

            coords = None
            if lat is not None and lng is not None:
                coords = {"lat": float(lat), "lng": float(lng)}
            elif location and location.strip() and not is_explicit:
                coords = geocode_address(location.strip())

            hospitals: List[Dict[str, Any]] = []

            # 1. Search via maps/OSM/Google if coordinates are available (for nearby searches)
            if coords and not is_explicit:
                try:
                    nearby = search_nearby_hospitals(coords["lat"], coords["lng"])
                    if nearby:
                        hospitals = save_or_get_hospitals_batch(nearby)
                except Exception as e:
                    logger.warning("External hospital search fallback to DB: %s", e)

            # 2. Direct DB search (Hard filtered for explicit locations)
            with get_db() as conn:
                cur = conn.cursor(dictionary=True)
                if is_explicit:
                    if loc_intent["type"] == "city":
                        cur.execute(
                            "SELECT id, name, address, city, state, phone, opening_hours, latitude, longitude "
                            "FROM hospitals WHERE LOWER(city) = %s OR LOWER(city) LIKE %s OR LOWER(address) LIKE %s LIMIT %s",
                            (loc_intent["name"].lower(), f"%{loc_intent['name'].lower()}%", f"%{loc_intent['name'].lower()}%", limit * 3)
                        )
                    else:
                        cur.execute(
                            "SELECT id, name, address, city, state, phone, opening_hours, latitude, longitude "
                            "FROM hospitals WHERE LOWER(state) = %s OR LOWER(state) LIKE %s OR LOWER(address) LIKE %s LIMIT %s",
                            (loc_intent["name"].lower(), f"%{loc_intent['name'].lower()}%", f"%{loc_intent['name'].lower()}%", limit * 3)
                        )
                    db_hosp = cur.fetchall() or []
                    hospitals = list(hospitals) + db_hosp
                elif not hospitals:
                    if location:
                        cur.execute(
                            "SELECT id, name, address, city, state, phone, opening_hours, latitude, longitude "
                            "FROM hospitals WHERE city LIKE %s OR address LIKE %s LIMIT %s",
                            (f"%{location}%", f"%{location}%", limit)
                        )
                    else:
                        cur.execute(
                            "SELECT id, name, address, city, state, phone, opening_hours, latitude, longitude "
                            "FROM hospitals ORDER BY id DESC LIMIT %s",
                            (limit,)
                        )
                    hospitals = cur.fetchall() or []
                cur.close()

            # 3. Hard Location Validation Filter
            if is_explicit:
                hospitals = [h for h in hospitals if is_hospital_matching_location(h, loc_intent)]

            # 4. Filter by specialty if requested
            if specialty and specialty.strip() and hospitals:
                spec_clean = specialty.strip().lower()
                hosp_ids = [h.get("id") or h.get("db_id") for h in hospitals if (h.get("id") or h.get("db_id"))]
                if hosp_ids:
                    format_strings = ','.join(['%s'] * len(hosp_ids))
                    with get_db() as conn:
                        cur = conn.cursor(dictionary=True)
                        cur.execute(
                            f"SELECT DISTINCT hospital_id FROM doctors "
                            f"WHERE hospital_id IN ({format_strings}) AND LOWER(specialty) LIKE %s",
                            (*hosp_ids, f"%{spec_clean}%")
                        )
                        matched_hosp_ids = {r["hospital_id"] for r in cur.fetchall()}
                        cur.close()

                    if matched_hosp_ids:
                        hospitals = [
                            h for h in hospitals
                            if (h.get("id") in matched_hosp_ids or h.get("db_id") in matched_hosp_ids)
                        ]

            # 5. Format results
            results = []
            seen_ids = set()
            for h in hospitals:
                hid = h.get("id") or h.get("db_id")
                if hid in seen_ids:
                    continue
                seen_ids.add(hid)
                results.append({
                    "id": hid,
                    "name": h.get("name"),
                    "address": h.get("address"),
                    "city": h.get("city"),
                    "state": h.get("state"),
                    "phone": h.get("phone") or "Available at reception",
                    "opening_hours": h.get("opening_hours") or "24/7",
                    "latitude": h.get("latitude") or h.get("lat"),
                    "longitude": h.get("longitude") or h.get("lng")
                })
                if len(results) >= limit:
                    break

            msg = ""
            if is_explicit and len(results) == 0:
                msg = f"No hospitals found in {loc_intent['display_name']}."

            return ToolResult(
                success=True,
                data={
                    "count": len(results),
                    "hospitals": results,
                    "searched_location": location,
                    "specialty_filter": specialty,
                    "message": msg
                }
            )
        except Exception as exc:
            logger.error("HospitalSearchTool error: %s", exc)
            return ToolResult(success=False, data=None, error=str(exc))
