from fastapi import Request, Response, HTTPException
from jose import jwt
from app.database import db
import os
from dotenv import load_dotenv
from app.utils.geo_lat_lng import geo_lat_lng
from datetime import datetime, time
from typing import Optional
from fastapi.responses import JSONResponse
from app.utils.serialize_row import serialize_row
import logging
load_dotenv()
logger = logging.getLogger(__name__)
SECRET_KEY = os.getenv("JWT_SECRET")

def parse_time(t: str) -> time:
    return datetime.strptime(t, "%H:%M").time() if t else None

def time_str_to_ms(time_str: str) -> int:
    if not time_str:
        return 0
    hours, minutes = map(int, time_str.split(":"))
    return ((hours * 60 + minutes) * 60) * 1000

async def admin_add_facility(request: Request, response: Response):
    conn = db
    try:
        body = await request.json()

        name = body.get("name")
        address = body.get("address")
        cityStateZip = body.get("cityStateZip")
        multiplier = body.get("multiplier")
        nurses = body.get("nurses", [])
        coordinators = body.get("coordinators", [])

        await conn.execute("BEGIN")

        # Check for duplicate coordinator phone/email
        for coordinator in coordinators:
            phone = coordinator.get("phone")
            email = coordinator.get("email")
            exists = await conn.fetchrow("""
                SELECT 1 FROM coordinator
                WHERE coordinator_phone = $1 OR coordinator_email ILIKE $2
            """, phone, email)
            if exists:
                await conn.execute("ROLLBACK")
                return {"message": "Facility with this phone or email already exists", "status": 400}

        geo = await geo_lat_lng(cityStateZip)
        lat, lng = geo.get("lat"), geo.get("lng")

        facility_row = await conn.fetchrow("""
            INSERT INTO facilities (name, address, city_state_zip, overtime_multiplier, lat, lng)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, name, address, cityStateZip, multiplier, lat, lng)
        facility_id = facility_row["id"]

        for nurse in nurses:
            work_ms = time_str_to_ms(nurse["amTimeEnd"]) - time_str_to_ms(nurse["amTimeStart"])
            meal_ms = time_str_to_ms(nurse["amMealEnd"]) - time_str_to_ms(nurse["amMealStart"])
            hours = (work_ms - meal_ms) / (1000 * 60 * 60)

            await conn.execute("""
                INSERT INTO shifts
                (facility_id, role, am_time_start, am_time_end, pm_time_start, pm_time_end,
                noc_time_start, noc_time_end, am_meal_start, am_meal_end, pm_meal_start,
                pm_meal_end, noc_meal_start, noc_meal_end, rate, hours)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            """, 
                facility_id, nurse["nurseType"],
                parse_time(nurse["amTimeStart"]), parse_time(nurse["amTimeEnd"]),
                parse_time(nurse["pmTimeStart"]), parse_time(nurse["pmTimeEnd"]),
                parse_time(nurse["nocTimeStart"]), parse_time(nurse["nocTimeEnd"]),
                parse_time(nurse["amMealStart"]), parse_time(nurse["amMealEnd"]),
                parse_time(nurse["pmMealStart"]), parse_time(nurse["pmMealEnd"]),
                parse_time(nurse["nocMealStart"]), parse_time(nurse["nocMealEnd"]),
                nurse["rate"], hours
            )

        for coordinator in coordinators:
            await conn.execute("""
                INSERT INTO coordinator (facility_id, coordinator_first_name, coordinator_last_name, coordinator_phone, coordinator_email)
                VALUES ($1, $2, $3, $4, $5)
            """, 
                facility_id, coordinator["firstName"], coordinator["lastName"],
                coordinator["phone"], coordinator["email"]
            )

        await conn.execute("COMMIT")
        return {"message": "Facility added successfully", "status": 200}

    except Exception as e:
        await conn.execute("ROLLBACK")
        print("Facility add error:", e)
        return {"message": "Server error", "status": 500}

def time_str_to_ms(time_str: Optional[str]) -> int:
    if not time_str:
        return 0
    hours, minutes = map(int, time_str.split(":"))
    return ((hours * 60 + minutes) * 60) * 1000

def parse_time(t: Optional[str]):
    return datetime.strptime(t, "%H:%M").time() if t else None

async def admin_edit_facility(request: Request, response: Response, facility_id: int):
    conn = db
    try:
        body = await request.json()
        name = body.get("name")
        address = body.get("address")
        cityStateZip = body.get("cityStateZip")
        multiplier = body.get("multiplier")
        nurses = body.get("nurses", [])
        coordinators = body.get("coordinators", [])

        await conn.execute("BEGIN")

        # Check for duplicate coordinator phone/email
        for coordinator in coordinators:
            check = await conn.fetchrow("""
                SELECT 1 FROM coordinator
                WHERE (coordinator_phone = $1 OR coordinator_email ILIKE $2) AND id != $3
            """, coordinator["phone"], coordinator["email"], coordinator.get("id"))
            if check:
                await conn.execute("ROLLBACK")
                return {"message": "Facility with this phone number or email already exists", "status": 400}

        # Check if cityStateZip has changed → update lat/lng
        existing = await conn.fetchrow("SELECT city_state_zip FROM facilities WHERE id = $1", facility_id)
        if existing and existing["city_state_zip"] != cityStateZip:
            geo = await geo_lat_lng(cityStateZip)
            print("Geo data:", geo)
            lat = geo.get("lat")
            lng = geo.get("lng")
            await conn.execute("""
                UPDATE facilities
                SET lat = $1, lng = $2
                WHERE id = $3
            """, lat, lng, facility_id)

        # Update facility main fields
        await conn.execute("""
            UPDATE facilities
            SET name = $1, address = $2, city_state_zip = $3, overtime_multiplier = $4
            WHERE id = $5
        """, name, address, cityStateZip, multiplier, facility_id)

        # Update or insert shifts
        for nurse in nurses:
            work_ms = time_str_to_ms(nurse["amTimeEnd"]) - time_str_to_ms(nurse["amTimeStart"])
            meal_ms = time_str_to_ms(nurse["amMealEnd"]) - time_str_to_ms(nurse["amMealStart"])
            hours = (work_ms - meal_ms) / (1000 * 60 * 60)

            shift = await conn.fetchrow("""
                SELECT id FROM shifts
                WHERE facility_id = $1 AND role = $2
            """, facility_id, nurse["nurseType"])

            shift_params = [
                parse_time(nurse["amTimeStart"]), parse_time(nurse["amTimeEnd"]),
                parse_time(nurse["pmTimeStart"]), parse_time(nurse["pmTimeEnd"]),
                parse_time(nurse["nocTimeStart"]), parse_time(nurse["nocTimeEnd"]),
                parse_time(nurse["amMealStart"]), parse_time(nurse["amMealEnd"]),
                parse_time(nurse["pmMealStart"]), parse_time(nurse["pmMealEnd"]),
                parse_time(nurse["nocMealStart"]), parse_time(nurse["nocMealEnd"]),
                nurse["rate"], hours, facility_id, nurse["nurseType"]
            ]

            if shift:
                await conn.execute("""
                    UPDATE shifts
                    SET am_time_start = $1, am_time_end = $2,
                        pm_time_start = $3, pm_time_end = $4,
                        noc_time_start = $5, noc_time_end = $6,
                        am_meal_start = $7, am_meal_end = $8,
                        pm_meal_start = $9, pm_meal_end = $10,
                        noc_meal_start = $11, noc_meal_end = $12,
                        rate = $13, hours = $14
                    WHERE facility_id = $15 AND role = $16
                """, *shift_params)
            else:
                await conn.execute("""
                    INSERT INTO shifts (
                        am_time_start, am_time_end, pm_time_start, pm_time_end,
                        noc_time_start, noc_time_end, am_meal_start, am_meal_end,
                        pm_meal_start, pm_meal_end, noc_meal_start, noc_meal_end,
                        rate, hours, facility_id, role
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        $9, $10, $11, $12, $13, $14, $15, $16
                    )
                """, *shift_params)

        # Update or insert coordinators
        for coordinator in coordinators:
            if coordinator.get("id"):
                await conn.execute("""
                    UPDATE coordinator
                    SET coordinator_first_name = $2, coordinator_last_name = $3,
                        coordinator_phone = $4, coordinator_email = $5
                    WHERE id = $1
                """, coordinator["id"], coordinator["firstName"], coordinator["lastName"],
                     coordinator["phone"], coordinator["email"])
            else:
                await conn.execute("""
                    INSERT INTO coordinator (
                        facility_id, coordinator_first_name, coordinator_last_name,
                        coordinator_phone, coordinator_email
                    ) VALUES ($1, $2, $3, $4, $5)
                """, facility_id, coordinator["firstName"], coordinator["lastName"],
                     coordinator["phone"], coordinator["email"])

        await conn.execute("COMMIT")
        return {"message": "Facility edited successfully", "status": 200}

    except Exception as e:
        await conn.execute("ROLLBACK")
        print("Edit Facility Error:", e)
        return {"message": "Server error", "status": 500}


async def admin_get_facilities(request: Request, response: Response):
    conn = db

    try:
        query_params = request.query_params
        search = query_params.get("search")
        page = int(query_params.get("page", 1))
        limit = int(query_params.get("limit", 10))
        no_pagination = query_params.get("noPagination") == "true"

        search_term = f"%{search}%" if search else None

        base_query = """
            FROM facilities
        """
        if search_term:
            base_query += """
                WHERE name ILIKE $1 OR city_state_zip ILIKE $1 OR address ILIKE $1
            """

        if no_pagination:
            query = f"SELECT * {base_query} ORDER BY name ASC"
            rows = await conn.fetch(query, search_term) if search_term else await conn.fetch(query)
            return JSONResponse(content={"facilities": [serialize_row(row) for row in rows], "status": 200, "noPagination": True})

        offset = (page - 1) * limit

        # Total count query
        count_query = f"SELECT COUNT(*) {base_query}"
        count_row = await conn.fetchrow(count_query, search_term) if search_term else await conn.fetchrow(count_query)
        total = int(count_row["count"])

        # Paginated data query
        data_query = f"""
            SELECT * {base_query}
            ORDER BY name ASC
            LIMIT ${2 if search_term else 1} OFFSET ${3 if search_term else 2}
        """
        values = [search_term, limit, offset] if search_term else [limit, offset]
        rows = await conn.fetch(data_query, *values)

        return JSONResponse(content={
            "facilities": [serialize_row(row) for row in rows],
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "totalPages": (total + limit - 1) // limit
            },
            "status": 200
        })

    except Exception as e:
        print("Error fetching facilities:", str(e))
        return JSONResponse(status_code=500, content={"message": "Server error", "status": 500})

async def admin_get_facility_by_id(request: Request, response: Response, id: int):
    try:
        facility = await db.fetchrow("SELECT * FROM facilities WHERE id = $1", id)
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")

        shifts = await db.fetch("SELECT * FROM shifts WHERE facility_id = $1", id)
        coordinators = await db.fetch("SELECT * FROM coordinator WHERE facility_id = $1", id)

        return JSONResponse(content={
            "facilities": serialize_row(facility),
            "services": [serialize_row(s) for s in shifts],
            "coordinators": [serialize_row(c) for c in coordinators],
            "status": 200
        })
    except Exception as e:
        print("Error fetching facility:", e)
        return JSONResponse(status_code=500, content={"message": "Server error", "status": 500})

async def admin_delete_facility(request: Request, response: Response, id: int):
    try:
        await db.execute("DELETE FROM facilities WHERE id = $1", id)
        return JSONResponse(content={"message": "Facility deleted successfully", "status": 200})
    except Exception as e:
        print("Error deleting facility:", e)
        return JSONResponse(status_code=500, content={"message": "An error has occurred", "status": 500})

