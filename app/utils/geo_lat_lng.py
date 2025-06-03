import httpx
import os
import logging

OPENCAGE_API_KEY = os.getenv("GEO_LOCATION_API_KEY")

logging.basicConfig(level=logging.INFO)

async def geo_lat_lng(city_state_zip: str):
    if not OPENCAGE_API_KEY:
        logging.error("GEO_LOCATION_API_KEY not set in environment.")
        raise Exception("GEO_LOCATION_API_KEY not set in environment.")

    url = "https://api.opencagedata.com/geocode/v1/json"
    params = {
        "q": city_state_zip,
        "key": OPENCAGE_API_KEY,
        "language": "en"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()  # Raise an exception for 4xx or 5xx status codes
            data = response.json()

        logging.info("API response: %s", data)

        if data.get("status", {}).get("code") == 200 and data.get("results"):
            result = data["results"][0]
            return {
                "lat": result["geometry"]["lat"],
                "lng": result["geometry"]["lng"]
            }
        else:
            logging.warning("No geolocation results found.")
            return None
    except httpx.HTTPError as e:
        logging.error("HTTP error: %s", e)
    except Exception as e:
        logging.error("Geolocation error: %s", e)
    return None

