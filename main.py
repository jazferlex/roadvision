from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import os
import math
from collections import Counter
from dotenv import load_dotenv

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

app = FastAPI()


# Approximate degree change for 10 meters
METER_TO_LAT = round(10 / 111320, 6)  # ~0.000089° latitude change
METER_TO_LNG = round(10 / (111320 * math.cos(math.radians(10.300125))), 6)  # Adjust for latitude

# Define request model
class LatLng(BaseModel):
    latitude: float
    longitude: float

class RouteRequest(BaseModel):
    origin: LatLng

async def get_route_data(origin: LatLng, destination: LatLng):
    """Call Google Routes API to get route information."""
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline,routes.travelAdvisory"
    }
    payload = {
        "origin": {"location": {"latLng": {"latitude": round(origin.latitude, 6), "longitude": round(origin.longitude, 6)}}},
        "destination": {"location": {"latLng": {"latitude": round(destination.latitude, 6), "longitude": round(destination.longitude, 6)}}},
        "travelMode": "DRIVE",
        "extraComputations": ["TRAFFIC_ON_POLYLINE"],
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()

def most_common_speed(speed_intervals):
    """Find the most common speed category."""
    speed_counts = Counter(interval["speed"] for interval in speed_intervals)
    return speed_counts.most_common(1)[0][0] if speed_counts else "UNKNOWN"

def extract_duration(duration_str):
    """Extract duration in seconds from a string like '14s'."""
    try:
        return int(duration_str.rstrip("s"))
    except (ValueError, AttributeError):
        return None

@app.post("/get-route")
async def get_route(request: RouteRequest):
    origin = request.origin

    # Define four destination points (N, S, E, W) with 6 decimal places
    destinations = {
        "N": LatLng(latitude=round(origin.latitude + METER_TO_LAT, 6), longitude=round(origin.longitude, 6)),
        "S": LatLng(latitude=round(origin.latitude - METER_TO_LAT, 6), longitude=round(origin.longitude, 6)),
        "E": LatLng(latitude=round(origin.latitude, 6), longitude=round(origin.longitude + METER_TO_LNG, 6)),
        "W": LatLng(latitude=round(origin.latitude, 6), longitude=round(origin.longitude - METER_TO_LNG, 6)),
    }

    route_results = {}
    filtered_speeds = []
    total_duration = 0
    valid_durations = 0

    # Process each direction
    for direction, destination in destinations.items():
        route_info = await get_route_data(origin, destination)
        route = route_info.get("routes", [{}])[0]

        # Extract distance and duration
        distance = route.get("distanceMeters", 0)
        duration_str = route.get("duration", "0s")
        duration_seconds = extract_duration(duration_str)

        # Extract speed intervals
        speed_intervals = route.get("travelAdvisory", {}).get("speedReadingIntervals", [])
        common_speed = most_common_speed(speed_intervals)

        # Exclude routes with distance > 20 meters
        if distance <= 20:
            if common_speed != "UNKNOWN":
                filtered_speeds.append(common_speed)

            if duration_seconds is not None:
                total_duration += duration_seconds
                valid_durations += 1

            route_results[direction] = {
                "destination": destination,
                "route_info": route_info,
                "most_common_speed": common_speed,
            }

    # Find the overall most common speed across filtered routes
    overall_speed = most_common_speed([{"speed": s} for s in filtered_speeds])
    
    # Calculate the average duration (excluding routes > 20m)
    average_duration = round(total_duration / valid_durations, 6) if valid_durations > 0 else None

    return {
        "origin": {
            "latitude": round(origin.latitude, 6),
            "longitude": round(origin.longitude, 6)
        },
        "routes": route_results,
        "overall_most_common_speed": overall_speed,
        "average_duration_seconds": average_duration
    }
