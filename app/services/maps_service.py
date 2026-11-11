import json
import logging
import math
import os
import time
import threading
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_GEOCODE_CACHE: Dict[str, Any] = {}
_REVERSE_GEOCODE_CACHE: Dict[tuple, Any] = {}
_NEARBY_HOSPITALS_CACHE: Dict[tuple, Any] = {}

GEOCODE_CACHE_TTL = 3600  # 1 hour
REVERSE_CACHE_TTL = 3600  # 1 hour
NEARBY_CACHE_TTL = 900    # 15 minutes


KNOWN_LOCATIONS = {
    # Karnataka
    'bengaluru': {'lat': 12.9716, 'lng': 77.5946},
    'bangalore': {'lat': 12.9716, 'lng': 77.5946},
    'karnataka': {'lat': 12.9716, 'lng': 77.5946},
    'manipal': {'lat': 13.3525, 'lng': 74.7874},
    'mangalore': {'lat': 12.9141, 'lng': 74.8560},
    'mangaluru': {'lat': 12.9141, 'lng': 74.8560},
    'karwar': {'lat': 14.8122, 'lng': 74.1323},
    'ankola': {'lat': 14.6653, 'lng': 74.3054},
    'mysore': {'lat': 12.2958, 'lng': 76.6394},
    'mysuru': {'lat': 12.2958, 'lng': 76.6394},
    'hubli': {'lat': 15.3647, 'lng': 75.1240},
    'hubballi': {'lat': 15.3647, 'lng': 75.1240},
    'dharwad': {'lat': 15.4589, 'lng': 75.0078},
    'belgaum': {'lat': 15.8497, 'lng': 74.4977},
    'belagavi': {'lat': 15.8497, 'lng': 74.4977},
    'udupi': {'lat': 13.3409, 'lng': 74.7421},
    'shimoga': {'lat': 13.9299, 'lng': 75.5681},
    'shivamogga': {'lat': 13.9299, 'lng': 75.5681},
    'bellary': {'lat': 15.1394, 'lng': 76.9214},
    'ballari': {'lat': 15.1394, 'lng': 76.9214},
    'kalaburagi': {'lat': 17.3297, 'lng': 76.8343},
    'gulbarga': {'lat': 17.3297, 'lng': 76.8343},

    # Maharashtra
    'mumbai': {'lat': 19.0760, 'lng': 72.8777},
    'bombay': {'lat': 19.0760, 'lng': 72.8777},
    'pune': {'lat': 18.5204, 'lng': 73.8567},
    'nagpur': {'lat': 21.1458, 'lng': 79.0882},
    'nashik': {'lat': 19.9975, 'lng': 73.7898},
    'thane': {'lat': 19.2183, 'lng': 72.9781},
    'aurangabad': {'lat': 19.8762, 'lng': 75.3433},
    'chhatrapati sambhajinagar': {'lat': 19.8762, 'lng': 75.3433},
    'maharashtra': {'lat': 19.0760, 'lng': 72.8777},

    # Delhi / NCR
    'delhi': {'lat': 28.6139, 'lng': 77.2090},
    'new delhi': {'lat': 28.6139, 'lng': 77.2090},
    'gurgaon': {'lat': 28.4595, 'lng': 77.0266},
    'gurugram': {'lat': 28.4595, 'lng': 77.0266},
    'noida': {'lat': 28.5355, 'lng': 77.3910},
    'ghaziabad': {'lat': 28.6692, 'lng': 77.4538},
    'faridabad': {'lat': 28.4089, 'lng': 77.3178},

    # Tamil Nadu
    'chennai': {'lat': 13.0827, 'lng': 80.2707},
    'madras': {'lat': 13.0827, 'lng': 80.2707},
    'coimbatore': {'lat': 11.0168, 'lng': 76.9558},
    'madurai': {'lat': 9.9252, 'lng': 78.1198},
    'tiruchirappalli': {'lat': 10.7905, 'lng': 78.7047},
    'salem': {'lat': 11.6643, 'lng': 78.1460},
    'tamil nadu': {'lat': 13.0827, 'lng': 80.2707},

    # Telangana & Andhra Pradesh
    'hyderabad': {'lat': 17.3850, 'lng': 78.4867},
    'telangana': {'lat': 17.3850, 'lng': 78.4867},
    'warangal': {'lat': 17.9689, 'lng': 79.5941},
    'visakhapatnam': {'lat': 17.6868, 'lng': 83.2185},
    'vizag': {'lat': 17.6868, 'lng': 83.2185},
    'vijayawada': {'lat': 16.5062, 'lng': 80.6480},
    'guntur': {'lat': 16.3067, 'lng': 80.4365},
    'andhra pradesh': {'lat': 16.5062, 'lng': 80.6480},

    # West Bengal
    'kolkata': {'lat': 22.5726, 'lng': 88.3639},
    'calcutta': {'lat': 22.5726, 'lng': 88.3639},
    'howrah': {'lat': 22.5958, 'lng': 88.2636},
    'west bengal': {'lat': 22.5726, 'lng': 88.3639},

    # Goa
    'goa': {'lat': 15.4909, 'lng': 73.8278},
    'panaji': {'lat': 15.4909, 'lng': 73.8278},
    'margao': {'lat': 15.2832, 'lng': 73.9862},
    'vasco': {'lat': 15.3982, 'lng': 73.8113},

    # Gujarat
    'ahmedabad': {'lat': 23.0225, 'lng': 72.5714},
    'surat': {'lat': 21.1702, 'lng': 72.8311},
    'vadodara': {'lat': 22.3072, 'lng': 73.1812},
    'rajkot': {'lat': 22.3039, 'lng': 70.8022},
    'gujarat': {'lat': 23.0225, 'lng': 72.5714},

    # Rajasthan
    'jaipur': {'lat': 26.9124, 'lng': 75.7873},
    'jodhpur': {'lat': 26.2389, 'lng': 73.0243},
    'udaipur': {'lat': 24.5854, 'lng': 73.7125},
    'rajasthan': {'lat': 26.9124, 'lng': 75.7873},

    # Uttar Pradesh
    'lucknow': {'lat': 26.8467, 'lng': 80.9462},
    'kanpur': {'lat': 26.4499, 'lng': 80.3319},
    'varanasi': {'lat': 25.3176, 'lng': 82.9739},
    'agra': {'lat': 27.1767, 'lng': 78.0081},
    'uttar pradesh': {'lat': 26.8467, 'lng': 80.9462},

    # Kerala
    'kochi': {'lat': 9.9312, 'lng': 76.2673},
    'cochin': {'lat': 9.9312, 'lng': 76.2673},
    'thiruvananthapuram': {'lat': 8.5241, 'lng': 76.9366},
    'trivandrum': {'lat': 8.5241, 'lng': 76.9366},
    'kozhikode': {'lat': 11.2588, 'lng': 75.7804},
    'kerala': {'lat': 9.9312, 'lng': 76.2673},

    # Punjab & Haryana & Chandigarh
    'chandigarh': {'lat': 30.7333, 'lng': 76.7794},
    'amritsar': {'lat': 31.6340, 'lng': 74.8723},
    'ludhiana': {'lat': 30.9010, 'lng': 75.8573},
    'punjab': {'lat': 30.7333, 'lng': 76.7794},
    'haryana': {'lat': 28.4595, 'lng': 77.0266},

    # Madhya Pradesh
    'bhopal': {'lat': 23.2599, 'lng': 77.4126},
    'indore': {'lat': 22.7196, 'lng': 75.8577},
    'madhya pradesh': {'lat': 23.2599, 'lng': 77.4126},

    # Bihar & Jharkhand
    'patna': {'lat': 25.5941, 'lng': 85.1376},
    'bihar': {'lat': 25.5941, 'lng': 85.1376},
    'gaya': {'lat': 24.7955, 'lng': 84.9753},
    'muzaffarpur': {'lat': 26.1558, 'lng': 85.3942},
    'darbhanga': {'lat': 26.1264, 'lng': 85.8974},
    'bhagalpur': {'lat': 25.2425, 'lng': 86.9842},
    'ranchi': {'lat': 23.3441, 'lng': 85.3096},
    'jharkhand': {'lat': 23.3441, 'lng': 85.3096},
    'jamshedpur': {'lat': 22.8046, 'lng': 86.2029},
    'dhanbad': {'lat': 23.7957, 'lng': 86.4304},

    # Odisha & Chhattisgarh
    'bhubaneswar': {'lat': 20.2961, 'lng': 85.8245},
    'odisha': {'lat': 20.2961, 'lng': 85.8245},
    'raipur': {'lat': 21.2514, 'lng': 81.6296},

    # Assam & Northeast
    'guwahati': {'lat': 26.1445, 'lng': 91.7362},
    'assam': {'lat': 26.1445, 'lng': 91.7362},

    # Uttarakhand & Himachal
    'dehradun': {'lat': 30.3165, 'lng': 78.0322},
    'uttarakhand': {'lat': 30.3165, 'lng': 78.0322},
    'shimla': {'lat': 31.1048, 'lng': 77.1734},
    'himachal pradesh': {'lat': 31.1048, 'lng': 77.1734},

    # Jammu & Kashmir
    'srinagar': {'lat': 34.0837, 'lng': 74.7973},
    'jammu': {'lat': 32.7266, 'lng': 74.8570},
}


def geocode_address(address_str: str) -> Optional[Dict[str, float]]:
    """Resolve a supplied address through Google, OSM, or fast location map with caching."""
    if not address_str or not address_str.strip():
        return None

    clean_key = address_str.strip().lower()
    now = time.time()
    with _CACHE_LOCK:
        if clean_key in _GEOCODE_CACHE:
            ts, val = _GEOCODE_CACHE[clean_key]
            if now - ts < GEOCODE_CACHE_TTL:
                return val

    # Fast Path: Check known city dictionary
    for city, coords in KNOWN_LOCATIONS.items():
        if city in clean_key:
            with _CACHE_LOCK:
                _GEOCODE_CACHE[clean_key] = (now, coords)
            return coords

    result = None
    google_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if google_key:
        try:
            params = urllib.parse.urlencode({"address": address_str, "key": google_key})
            with urllib.request.urlopen(
                f"https://maps.googleapis.com/maps/api/geocode/json?{params}",
                timeout=2,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
            results = data.get("results")
            if results and isinstance(results, list) and len(results) > 0:
                location = results[0].get("geometry", {}).get("location")
                if location and "lat" in location and "lng" in location:
                    result = {"lat": float(location["lat"]), "lng": float(location["lng"])}
        except Exception as exc:
            logger.warning("Google geocoding failed: %s", type(exc).__name__)

    if not result:
        try:
            params = urllib.parse.urlencode({"q": address_str, "format": "json", "limit": 1})
            request = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/search?{params}",
                headers={"User-Agent": "GENOMIX-AI-Health/1.0"},
            )
            with urllib.request.urlopen(request, timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data:
                result = {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])}
        except Exception as exc:
            logger.warning("OSM geocoding failed: %s", type(exc).__name__)

    if result:
        with _CACHE_LOCK:
            _GEOCODE_CACHE[clean_key] = (now, result)

    return result


def reverse_geocode(lat: float, lng: float) -> Optional[str]:
    """Reverse geocode coordinates to an address/location string with caching."""
    key = (round(float(lat), 3), round(float(lng), 3))
    now = time.time()
    with _CACHE_LOCK:
        if key in _REVERSE_GEOCODE_CACHE:
            ts, val = _REVERSE_GEOCODE_CACHE[key]
            if now - ts < REVERSE_CACHE_TTL:
                return val

    result = None
    google_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if google_key:
        try:
            params = urllib.parse.urlencode({"latlng": f"{lat},{lng}", "key": google_key})
            with urllib.request.urlopen(
                f"https://maps.googleapis.com/maps/api/geocode/json?{params}",
                timeout=2,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
            results = data.get("results")
            if results and isinstance(results, list) and len(results) > 0:
                formatted = results[0].get("formatted_address")
                if formatted:
                    result = formatted
        except Exception as exc:
            logger.warning("Google reverse geocoding failed: %s", type(exc).__name__)

    if not result:
        try:
            params = urllib.parse.urlencode({"lat": str(lat), "lon": str(lng), "format": "json"})
            request = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/reverse?{params}",
                headers={"User-Agent": "GENOMIX-AI-Health/1.0"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data and isinstance(data, dict):
                display_name = data.get("display_name")
                if display_name:
                    result = display_name
        except Exception as exc:
            logger.warning("OSM reverse geocoding failed: %s", type(exc).__name__)

    if result:
        with _CACHE_LOCK:
            _REVERSE_GEOCODE_CACHE[key] = (now, result)

    return result


def search_nearby_hospitals(lat: float, lng: float, radius_km: float = 50.0) -> List[Dict[str, Any]]:
    """Search real hospital providers and return facilities nearest first with caching."""
    key = (round(float(lat), 2), round(float(lng), 2))
    now = time.time()
    with _CACHE_LOCK:
        if key in _NEARBY_HOSPITALS_CACHE:
            ts, val = _NEARBY_HOSPITALS_CACHE[key]
            if now - ts < NEARBY_CACHE_TTL:
                return [dict(h) for h in val]

    # Fast Path 1: Google Places API if key configured
    google_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if google_key:
        google_results = _search_google_places(lat, lng, google_key)
        if google_results:
            with _CACHE_LOCK:
                _NEARBY_HOSPITALS_CACHE[key] = (now, google_results)
            return google_results

    # Fast Path 2: Check if DB already has hospitals near these coordinates within radius_km
    try:
        from app.services.hospital_service import get_hospitals_from_db_near
        db_hospitals = get_hospitals_from_db_near(lat, lng, radius_km=radius_km)

        if db_hospitals and len(db_hospitals) >= 5:
            with _CACHE_LOCK:
                _NEARBY_HOSPITALS_CACHE[key] = (now, db_hospitals)
            return db_hospitals
    except Exception as exc:
        logger.warning("DB nearby hospital lookup skipped: %s", exc)

    # Path 3: Single optimized Overpass API query (radius_km, 5s timeout)
    hospitals: List[Dict[str, Any]] = []
    try:
        radius_m = int(radius_km * 1000)
        query = f"""
        [out:json][timeout:5];
        (node["amenity"="hospital"](around:{radius_m},{lat},{lng});
         way["amenity"="hospital"](around:{radius_m},{lat},{lng}););
        out center 50;
        """
        request = urllib.request.Request(
            "https://overpass-api.de/api/interpreter",
            data=query.encode("utf-8"),
            headers={"User-Agent": "GENOMIX-AI-Health/1.0"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        for element in data.get("elements", []):
            tags = element.get("tags", {})
            h_lat = element.get("lat") or element.get("center", {}).get("lat")
            h_lng = element.get("lon") or element.get("center", {}).get("lon")
            if h_lat is None or h_lng is None or not tags.get("name"):
                continue
            hospitals.append(_hospital_record(
                f"osm_{element.get('type')}_{element.get('id')}",
                tags["name"],
                tags.get("addr:full") or tags.get("addr:street") or tags.get("addr:city") or "",
                float(h_lat),
                float(h_lng),
                lat,
                lng,
                tags.get("phone") or tags.get("contact:phone"),
                tags.get("opening_hours") or "24/7 Emergency & OPD",
            ))
        
        hospitals = _deduplicate_and_sort(hospitals)
    except Exception as exc:
        logger.warning("Overpass hospital search failed: %s", type(exc).__name__)

    # Path 4: OpenStreetMap Nominatim Nearby Bounding Box Fallback
    if not hospitals:
        try:
            params = urllib.parse.urlencode({
                "q": "hospital",
                "format": "json",
                "limit": 30,
                "viewbox": f"{lng-0.35},{lat+0.35},{lng+0.35},{lat-0.35}",
                "bounded": 1
            })
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/search?{params}",
                headers={"User-Agent": "GENOMIX-AI-Health/1.0"}
            )
            with urllib.request.urlopen(req, timeout=4) as response:
                nom_data = json.loads(response.read().decode("utf-8"))
            for item in nom_data:
                h_lat = float(item["lat"])
                h_lng = float(item["lon"])
                disp = item.get("display_name", "")
                raw_name = item.get("name") or disp.split(",")[0].strip()
                h_name = raw_name.split(",")[0].strip() or "Hospital"
                hospitals.append(_hospital_record(
                    f"nom_{item.get('osm_type', 'node')}_{item.get('osm_id', '')}",
                    h_name,
                    disp,
                    h_lat,
                    h_lng,
                    lat,
                    lng,
                    None,
                    "24/7 Emergency & OPD"
                ))
            hospitals = _deduplicate_and_sort(hospitals)
        except Exception as exc:
            logger.warning("Nominatim nearby hospital lookup fallback failed: %s", exc)

    # Fallback to DB hospitals strictly within radius_km if external lookups had no results
    if not hospitals:
        try:
            from app.services.hospital_service import get_hospitals_from_db_near
            hospitals = get_hospitals_from_db_near(lat, lng, radius_km=radius_km)
        except Exception:
            pass

    if hospitals:
        with _CACHE_LOCK:
            _NEARBY_HOSPITALS_CACHE[key] = (now, hospitals)

    return hospitals


def search_hospitals_by_place_name(place_name: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search real hospital facilities directly in any place or region worldwide by name.
    """
    if not place_name or not place_name.strip():
        return []

    clean_place = place_name.strip()
    hospitals: List[Dict[str, Any]] = []

    try:
        params = urllib.parse.urlencode({
            "q": f"hospital in {clean_place}",
            "format": "json",
            "limit": limit
        })
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/search?{params}",
            headers={"User-Agent": "GENOMIX-AI-Health/1.0"}
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))

        for item in data:
            lat = float(item["lat"])
            lng = float(item["lon"])
            disp = item.get("display_name", "")
            raw_name = item.get("name") or disp.split(",")[0].strip()
            h_name = raw_name.split(",")[0].strip() or "Hospital"
            hospitals.append(_hospital_record(
                f"nom_{item.get('osm_type', 'node')}_{item.get('osm_id', '')}",
                h_name,
                disp,
                lat,
                lng,
                lat,
                lng,
                None,
                "24/7 Emergency & OPD"
            ))
    except Exception as exc:
        logger.warning("Nominatim place hospital search failed for %s: %s", clean_place, exc)

    return _deduplicate_and_sort(hospitals)



def _search_google_places(lat: float, lng: float, api_key: str, radius_km: float = 50.0) -> List[Dict[str, Any]]:
    try:
        params = urllib.parse.urlencode({
            "location": f"{lat},{lng}",
            "radius": int(radius_km * 1000),
            "type": "hospital",
            "key": api_key,
        })
        with urllib.request.urlopen(
            f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?{params}",
            timeout=5,
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("status") not in {"OK", "ZERO_RESULTS"}:
            logger.warning("Google Places returned status %s", data.get("status"))
        hospitals = []
        for place in data.get("results", []):
            location = place.get("geometry", {}).get("location", {})
            if not location.get("lat") or not location.get("lng"):
                continue
            hospitals.append(_hospital_record(
                f"google_{place.get('place_id')}",
                place.get("name"),
                place.get("vicinity", ""),
                float(location["lat"]),
                float(location["lng"]),
                lat,
                lng,
                None,
                "Open now" if place.get("opening_hours", {}).get("open_now") else None,
            ))
        return _deduplicate_and_sort(hospitals)
    except Exception as exc:
        logger.warning("Google Places search failed: %s", type(exc).__name__)
        return []


def _hospital_record(external_id: str, name: Optional[str], address: str, h_lat: float, h_lng: float, user_lat: float, user_lng: float, phone: Optional[str], opening_hours: Optional[str]) -> Dict[str, Any]:
    return {
        "external_place_id": external_id,
        "name": name or "Hospital",
        "address": address,
        "lat": h_lat,
        "lng": h_lng,
        "distance_km": round(_haversine_distance(user_lat, user_lng, h_lat, h_lng), 1),
        "phone": phone,
        "opening_hours": opening_hours,
    }


def _deduplicate_and_sort(hospitals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for hospital in hospitals:
        key = (round(hospital["lat"], 4), round(hospital["lng"], 4))
        if key not in seen:
            seen.add(key)
            unique.append(hospital)
    return sorted(unique, key=lambda item: item["distance_km"])


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    value = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))

