from app.database import db
import json
import re
from app.utils.send_message import send_message
from app.helper.promptHelper import generate_message_for_nurse_ai
import asyncio
from datetime import datetime
from fastapi import HTTPException
from app.helper.promptHelper import generateReplyFromAINurse
from app.utils.normalizeDate import normalize_date
from fastapi.responses import JSONResponse
import math
from app.utils.geo_lat_lng import geo_lat_lng
from datetime import datetime
from fastapi import Request, Response, HTTPException
import logging
from app.utils.serialize_row import serialize_row
from app.utils.convert_mm_dd_yyyy_to_mm_dd import convert_to_md
import traceback
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from app.utils.cache import cache
import re

logger = logging.getLogger(__name__)

async def search_nurses(nurse_type: str, shift: str, shift_id: int):
    try:
        # Get shift info including facility_id
        shift_row = await db.fetchrow(
            "SELECT facility_id FROM shift_tracker WHERE id = $1", shift_id
        )
        if not shift_row:
            raise ValueError("Shift not found.")
        facility_id = shift_row["facility_id"]

        # Get facility location
        facility = await db.fetchrow(
            "SELECT lat, lng FROM facilities WHERE id = $1", facility_id
        )
        if not facility or not facility["lat"] or not facility["lng"]:
            raise ValueError("Facility does not have valid coordinates.")

        lat = float(facility["lat"])
        lng = float(facility["lng"])

        # Search nurses within 50 miles radius using Haversine
        query = """
            SELECT n.*
            FROM nurses n
            WHERE n.nurse_type ILIKE $1
              AND (
                3959 * acos(
                  cos(radians($2)) * cos(radians(n.lat)) *
                  cos(radians(n.lng) - radians($3)) +
                  sin(radians($2)) * sin(radians(n.lat))
                )
              ) <= 50
        """
        nurses = await db.fetch(query, nurse_type, lat, lng)
        return nurses

    except Exception as e:
        print("Error searching nurses:", e)
        return []

async def send_nurses_message(nurses, nurse_type: str, shift: str, shift_id: int, date: str, additional_instructions: str):
    for nurse in nurses:
        phone_number = nurse["mobile_number"]
        print(f"Sending message to nurse: {phone_number}")
        nurse_availability = await check_nurse_availability(nurse["id"], shift_id)
        if not nurse_availability:
            continue

        past_messages = await get_nurse_chat_data(phone_number)

        raw_response = await generate_message_for_nurse_ai(
            nurse_type=nurse_type,
            shift=shift,
            date=date,
            past_messages=past_messages,
            shift_id=shift_id,
            additional_instructions=additional_instructions
        )

        message_text = raw_response.strip()
        # Clean ```json or ``` if present
        if message_text.startswith("```json"):
            message_text = re.sub(r"```json|```", "", message_text).strip()
        elif message_text.startswith("```"):
            message_text = re.sub(r"```", "", message_text).strip()

        try:
            message_data = json.loads(message_text)
            ai_message = message_data.get("message", "")
        except json.JSONDecodeError as e:
            print("Failed to parse AI reply:", e)
            continue

        if ai_message:
            await update_nurse_chat_history(phone_number, ai_message, "sent")
            asyncio.create_task(send_message(phone_number, ai_message)) 


async def check_nurse_availability(nurse_id: int, shift_id: int) -> tuple[bool, str]:
    try:
        # Get shift info (date and shift_value)
        new_shift = await db.fetchrow("""
            SELECT date, shift
            FROM shift_tracker
            WHERE id = $1
        """, shift_id)

        if not new_shift:
            return False, "Shift not found."

        shift_date = new_shift["date"]
        new_shift_value = new_shift["shift"]

        # Get nurse type
        nurse = await db.fetchrow("""
            SELECT nurse_type
            FROM nurses
            WHERE id = $1
        """, nurse_id)

        if not nurse:
            return False, "Nurse not found."

        nurse_type = nurse["nurse_type"].strip().upper()
        existing_shifts = await db.fetch("""
            SELECT st.shift, st.nurse_type, f.name AS facility_name
            FROM shift_tracker st
            JOIN facilities f ON st.facility_id = f.id
            WHERE st.nurse_id = $1 AND st.date = $2 AND st.is_deleted = FALSE
        """, nurse_id, shift_date)

        # If already 2 shifts -> block
        if len(existing_shifts) >= 2:
                assigned = "\n".join(
                [
                    f"{idx + 1}. Shift: {s['shift']}, Nurse Type: {s['nurse_type']}, Facility: {s['facility_name']}"
                    for idx, s in enumerate(existing_shifts)
                ]
                )
                msg = (
                "You can only accept up to 2 shifts in a day.\n\n"
                "You are already assigned the following shifts:\n"
                f"{assigned}\n"
            )
                assigned = "\n".join(
                [
                    f"{idx + 1}. Shift: {s['shift']}, Nurse Type: {s['nurse_type']}, Facility: {s['facility_name']}"
                    for idx, s in enumerate(existing_shifts)
                ]
                )

                return False, msg
        
        # Prevent same shift double-booking
        assigned_shift_values = [s["shift"].strip().upper() for s in existing_shifts]
        if new_shift_value.strip().upper() in assigned_shift_values:
            return False, f"You already have a {new_shift_value.upper()} shift assigned on this day."

        return True, "Available"

    except Exception as error:
        print("Error occurred while checking nurse availability:", error)
        return False, "An internal error occurred while checking your availability."

async def update_nurse_chat_history(sender: str, text: str, msg_type: str) -> None:
    try:
        await db.execute("""
            INSERT INTO nurse_chat_data
            (mobile_number, message, message_type)
            VALUES ($1, $2, $3)
        """, sender, text, msg_type)
    except Exception as err:
        print('Error updating nurse chat history:', err)
    
async def get_nurse_chat_data(sender: str) -> list[str]:
    try:
        rows = await db.fetch("""
            SELECT message
            FROM nurse_chat_data
            WHERE mobile_number = $1
            LIMIT 50
        """, sender)
        return [row['message'] for row in rows]
    except Exception as error:
        print("Error getting nurse chat data:", error)
        return []

async def follow_up_reply(sender: str, message: str) -> dict:
    try:
        # Step 1: Get nurse_id using sender (mobile number)
        nurse = await db.fetchrow("""
            SELECT id
            FROM nurses
            WHERE mobile_number = $1
        """, sender)
        if not nurse:
            raise ValueError("Nurse not found for the given phone number.")

        nurse_id = nurse['id']

        # Step 2: Get coordinator_id from today's shift for this nurse
        shift = await db.fetchrow("""
            SELECT coordinator_id
            FROM shift_tracker
            WHERE nurse_id = $1
              AND date = CURRENT_DATE
        """, nurse_id)
        if not shift:
            raise ValueError("No shift found for this nurse today.")

        coordinator_id = shift['coordinator_id']

        # Step 3: Get coordinator contact details
        coordinator = await db.fetchrow("""
            SELECT coordinator_email, coordinator_phone
            FROM coordinator
            WHERE id = $1
        """, coordinator_id)
        if not coordinator:
            raise ValueError("Coordinator not found.")

        coordinator_email = coordinator['coordinator_email']
        coordinator_phone = coordinator['coordinator_phone']

        # Step 4: Send message
        asyncio.create_task(send_message(coordinator_phone, message)) 

        return {
            "coordinator_email": coordinator_email,
            "coordinator_phone": coordinator_phone
        }

    except Exception as e:
        print("Error in follow_up_reply:", e)
        return {}

async def get_nurse_info(nurse_phone: str) -> dict:
    try:
        print(nurse_phone)
        print(len(nurse_phone))

        nurse = await db.fetchrow("""
            SELECT nurse_type, shift
            FROM nurses
            WHERE mobile_number = $1
        """, nurse_phone)

        if not nurse:
            raise ValueError("Nurse not found.")

        return {
            "nurse_type": nurse["nurse_type"],
            "shift": nurse["shift"]
        }

    except Exception as e:
        print("Error in get_nurse_info:", e)
        return {}
    
async def admin_get_nurses(request: Request, response: Response):
    conn = db
    try:
        params = request.query_params
        page = int(params.get("page", 1))
        limit = int(params.get("limit", 10))
        offset = (page - 1) * limit
        search = params.get("search", "").strip()

        base_query = "SELECT * FROM nurses"
        count_query = "SELECT COUNT(*) FROM nurses"
        query_params = []
        conditions = []

        if search:
            conditions.append("""
                (first_name ILIKE $1 OR last_name ILIKE $1 OR email ILIKE $1 
                OR mobile_number ILIKE $1 OR shift ILIKE $1 OR nurse_type ILIKE $1)
            """)
            query_params.append(f"%{search}%")

        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)
            base_query += where_clause
            count_query += where_clause

        # Add LIMIT & OFFSET
        base_query += f" ORDER BY last_name ASC, first_name ASC LIMIT ${len(query_params)+1} OFFSET ${len(query_params)+2}"
        query_params += [limit, offset]

        # Total count
        count_result = await conn.fetchrow(count_query, *query_params[:1] if conditions else [])
        total = int(count_result["count"])

        # Data
        rows = await conn.fetch(base_query, *query_params)
        nurses = [dict(row) for row in rows]

        return {
            "nurses": nurses,
            "pagination": {
                "total": total,
                "page": page,
                "limit": limit,
                "totalPages": math.ceil(total / limit)
            },
            "status": 200
        }

    except Exception as e:
        print("Error fetching nurses:", e)
        return {"message": "Server error", "status": 500}

async def admin_get_nurse_by_id(request: Request, response: Response, id: int):
    conn = db
    try:
        row = await conn.fetchrow("SELECT * FROM nurses WHERE id = $1", id)
        return {"nurseData": dict(row) if row else None, "status": 200}
    except Exception as e:
        print("Error fetching nurse by ID:", e)
        return {"message": "Server error", "status": 500}
    
async def admin_add_nurse(request: Request, response: Response):
    data = await request.json()
    try:
        email = data["email"]
        phone = data["phone"]
        talent_id = str(data["talentId"])

        existing = await db.fetch("""
            SELECT * FROM nurses WHERE email ILIKE $1 OR mobile_number = $2
        """, email, phone)

        if existing:
            email_conflict = any(row["email"].lower() == email.lower() for row in existing)
            phone_conflict = any(row["mobile_number"] == phone for row in existing)

            if email_conflict and phone_conflict:
                message = "Nurse with this email and phone number already exists"
            elif email_conflict:
                message = "Nurse with this email already exists"
            elif phone_conflict:
                message = "Nurse with this phone number already exists"
            else:
                message = "Nurse already exists"

            return JSONResponse(
                content={
                    "message": message,
                    "status": 400,
                },
                status_code=400
            )

         # 🔹 Check in coordinator table as well
        existing_coordinator = await db.fetch("""
            SELECT * FROM coordinator WHERE coordinator_email ILIKE $1 OR coordinator_phone = $2
        """, email, phone)

        if existing_coordinator:
            existing = dict(existing_coordinator[0])

            phone_conflict = existing.get("coordinator_phone") == phone
            email_conflict = existing.get("coordinator_email") == email

            if phone_conflict and email_conflict:
                message = "Email and mobile number already exist."
            elif email_conflict:
                message = "Email already exists."
            elif phone_conflict:
                message = "Mobile number already exists."
            else:
                message = "Coordinator already exists."

            return JSONResponse(
                content={
                    "message": message,
                    "status": 400,
                    # "coordinator": existing
                },
                status_code=400
            )
        
        # Minimum check (only talent_id)
        existing_talent = await db.fetchval(
            "SELECT talent_id FROM nurses WHERE talent_id = $1",
            talent_id
        )
        if existing_talent:
            return JSONResponse(
                content={
                    "message": f"Talent ID {talent_id} already exists",
                    "status": 400,
                    # "coordinator": existing_talent  # <-- fixed variable name
                },
                status_code=400
            )

        geo = await geo_lat_lng(data["location"])
        lat, lng = geo["lat"], geo["lng"]

        await db.execute("""
            INSERT INTO nurses
            (first_name, last_name, schedule_name, rate, shift_dif, ot_rate,
             email, talent_id, nurse_type, mobile_number, location, shift, lat, lng)
            VALUES ($1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10, $11, $12, $13, $14)
        """,
            data["firstName"],
            data["lastName"],
            data["scheduleName"],
            data["rate"],
            data["shiftDif"],
            data["otRate"],
            email,
            str(data["talentId"]),  # Ensure it's a string
            data["position"],
            phone,
            data["location"],
            data["shift"],
            lat,
            lng
        )

        return JSONResponse(
            content={"message": "Nurse added successfully", "status": 200},
            status_code=200
        )

    except Exception as e:
        logger.exception("Add Nurse Error")
        return JSONResponse(
            content={"message": "An error has occurred", "status": 500},
            status_code=500
        )

async def admin_edit_nurse(request: Request, response: Response, id: int):
    data = await request.json()
    try:
        email = data["email"]
        phone = data["phone"]
        talent_id = str(data["talentId"])

        # Check for duplicate email or phone
        existing_conflict = await db.fetch("""
            SELECT * FROM nurses
            WHERE (email ILIKE $1 OR mobile_number = $2) AND id != $3
        """, email, phone, id)

        if existing_conflict:
            email_conflict = any(row["email"].lower() == email.lower() for row in existing_conflict)
            phone_conflict = any(row["mobile_number"] == phone for row in existing_conflict)

            if email_conflict and phone_conflict:
                message = "Nurse with this email and phone number already exists"
            elif email_conflict:
                message = "Nurse with this email already exists"
            elif phone_conflict:
                message = "Nurse with this phone number already exists"
            else:
                message = "Nurse already exists"

            return JSONResponse(
                content={"message": message, "status": 400},
                status_code=400
            )

        # 🔹 Check in coordinator table (both email + phone)
        existing_coordinator = await db.fetch("""
            SELECT * FROM coordinator
            WHERE coordinator_email ILIKE $1 OR coordinator_phone = $2
        """, email, phone)

        if existing_coordinator:
            existing = dict(existing_coordinator[0])
            phone_conflict = existing.get("coordinator_phone") == phone
            email_conflict = existing.get("coordinator_email").lower() == email.lower()

            if phone_conflict and email_conflict:
                message = "This email and phone number are already used by a coordinator"
            elif email_conflict:
                message = "This email is already used by a coordinator"
            elif phone_conflict:
                message = "This phone number is already used by a coordinator"
            else:
                message = "Coordinator already exists"

            return JSONResponse(
                content={"message": message, "status": 400},
                status_code=400
            )
        # 🔹 Check for unique talent_id (excluding self)
        existing_talent = await db.fetchval("""
            SELECT talent_id FROM nurses 
            WHERE talent_id = $1 AND id != $2
        """, talent_id, id)

        if existing_talent:
            return JSONResponse(
                content={"message": f"Talent ID {talent_id} already exists", "status": 400},
                status_code=400
            )

        # 🔹 Check if location changed → update lat/lng
        existing_location = await db.fetchrow("""
            SELECT location FROM nurses WHERE id = $1
        """, id)

        if existing_location and existing_location["location"] != data["location"]:
            geo = await geo_lat_lng(data["location"])
            await db.execute("""
                UPDATE nurses
                SET lat = $1, lng = $2
                WHERE id = $3
            """, geo["lat"], geo["lng"], id)

        # Update nurse details
        await db.execute("""
            UPDATE nurses
            SET first_name = $1, last_name = $2, schedule_name = $3, rate = $4, shift_dif = $5, ot_rate = $6,
                email = $7, talent_id = $8, nurse_type = $9, mobile_number = $10, location = $11, shift = $12
            WHERE id = $13
        """, data["firstName"], data["lastName"], data["scheduleName"], data["rate"], data["shiftDif"], data["otRate"],
             email, str(data["talentId"]), data["position"], phone, data["location"], data["shift"], id)

        return JSONResponse(content={"message": "Nurse updated successfully", "status": 200}, status_code=200)

    except Exception as e:
        logger.exception("Edit Nurse Error")
        return JSONResponse(content={"message": "An error has occurred", "status": 500}, status_code=500)
    
async def admin_delete_nurse(request: Request, response: Response, id: int):
    try:
        await db.execute("""
            DELETE FROM nurses
            WHERE id = $1
        """, id)
        return JSONResponse(content={"message": "Nurse deleted successfully", "status": 200}, status_code=200)
    except Exception as e:
        logger.exception("Delete Nurse Error")
        return JSONResponse(content={"message": "An error has occurred", "status": 500}, status_code=500)
    
async def admin_get_available_nurses(request: Request, response: Response):
    try:
        params = dict(request.query_params)
        facility_id = params.get("facility_id")
        facility_id = int(facility_id) if facility_id else None
        nurse_type = params.get("nurse_type")
        date_str = params.get("date")
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        shift = params.get("shift")

        print("FETCH AVAILABLE NURSES", params)

        # Get facility location
        facility_rows = await db.fetch("""
            SELECT lat, lng FROM facilities WHERE id = $1
        """, facility_id)

        if not facility_rows:
            return JSONResponse(content={"message": "Facility not found."}, status_code=400)

        facility = facility_rows[0]
        if not facility["lat"] or not facility["lng"]:
            return JSONResponse(content={"message": "Facility location incomplete."}, status_code=400)

        facility_lat = float(facility["lat"])
        facility_lng = float(facility["lng"])

        # Step 1: Find nurses within 50 miles using Haversine formula
        nurse_rows = await db.fetch("""
            SELECT * FROM nurses n
            WHERE nurse_type ILIKE $1
              AND shift ILIKE $2
              AND lat IS NOT NULL AND lng IS NOT NULL
              AND (
                3959 * acos(
                  cos(radians($3)) * cos(radians(n.lat)) *
                  cos(radians(n.lng) - radians($4)) +
                  sin(radians($3)) * sin(radians(n.lat))
                )
              ) <= 50
        """, nurse_type, shift, facility_lat, facility_lng)

        nurse_ids = [n["id"] for n in nurse_rows]
        print("NURSE IDS", nurse_ids)

        if not nurse_ids:
            return JSONResponse(content={"nurses": [], "status": 200}, status_code=200)

        # Step 2: Filter out nurses already booked for that date
        available_nurses = await db.fetch("""
            SELECT n.*
            FROM nurses n
            LEFT JOIN shift_tracker st ON n.id = st.nurse_id AND st.date = $2
            WHERE n.id = ANY($1::int[])
            AND st.nurse_id IS NULL
        """, nurse_ids, date)

        print("AVAILABLE NURSES", available_nurses)

        # Optionally convert Decimals, dates to strings
        serialized = [serialize_row(row) for row in available_nurses]

        return JSONResponse(content={"nurses": serialized, "status": 200}, status_code=200)

    except Exception as e:
        print("Error fetching nurses:", e)
        return JSONResponse(content={"message": "Server error", "status": 500}, status_code=500)

async def admin_add_nurse_type(request: Request, response: Response):
    try:
        data = await request.json()
        nurse_type = data.get("nurse_type")

        await db.execute("""
            INSERT INTO nurse_type (nurse_type)
            VALUES ($1)
        """, nurse_type)

        return JSONResponse(content={"message": "Position added successfully", "status": 200})

    except Exception as error:
        print("Add Nurse Type Error:", error)
        return JSONResponse(content={"message": "An error has occurred", "status": 500}, status_code=500)
    
async def admin_get_nurse_type (request: Request, response: Response):
    try:
        query = "SELECT * FROM nurse_type"
        nurse_types = await db.fetch(query)
        return {"message": "Nurse types fetched successfully", "nurse_types": [serialize_row(row) for row in nurse_types], "status": 200}
    except Exception as error:
        print("Get Nurse Type Error:", error)
        return {"message": "An error has occurred", "status": 500}
async def admin_get_nurse_types(request: Request, response: Response):
    try:
        rows = await db.fetch("SELECT * FROM nurse_type")
        nurse_types = [serialize_row(row) for row in rows]
        return JSONResponse(content={
            "message": "Nurse types fetched successfully",
            "nurse_types": nurse_types,
            "status": 200
        })
    except Exception as error:
        print("Get Nurse Types Error:", error)
        return JSONResponse(content={
            "message": "An error has occurred",
            "status": 500
        }, status_code=500)
    
async def admin_delete_nurse_type(request: Request, response: Response, id: int):
    try:
        row = await db.fetchrow("SELECT * FROM nurse_type WHERE id = $1", id)
        if not row:
            raise HTTPException(status_code=404, detail="Nurse type not found")

        nurse_type = row["nurse_type"]

        await db.execute("DELETE FROM nurse_type WHERE id = $1", id)
        await db.execute("DELETE FROM shifts WHERE role ILIKE $1", nurse_type)
        await db.execute("DELETE FROM nurses WHERE nurse_type ILIKE $1", nurse_type)
        await db.execute("DELETE FROM shift_tracker WHERE nurse_type ILIKE $1", nurse_type)

        return JSONResponse(content={
            "message": "Nurse type deleted successfully",
            "status": 200
        })
    except Exception as error:
        print("Delete Nurse Type Error:", error)
        return JSONResponse(content={
            "message": "An error has occurred",
            "status": 500
        }, status_code=500)

async def admin_edit_nurse_type(request: Request, response: Response,id: int):
    try:
        data = await request.json()
        nurse_type = data.get("nurse_type")

        row = await db.fetchrow("SELECT * FROM nurse_type WHERE id = $1", id)
        if not row:
            raise HTTPException(status_code=404, detail="Nurse type not found")

        old_nurse_type = row["nurse_type"]

        await db.execute(
            "UPDATE nurse_type SET nurse_type = $1 WHERE id = $2",
            nurse_type, id
        )
        await db.execute(
            "UPDATE shifts SET role = $1 WHERE role ILIKE $2",
            nurse_type, old_nurse_type
        )
        await db.execute(
            "UPDATE nurses SET nurse_type = $1 WHERE nurse_type ILIKE $2",
            nurse_type, old_nurse_type
        )
        await db.execute(
            "UPDATE shift_tracker SET nurse_type = $1 WHERE nurse_type ILIKE $2",
            nurse_type, old_nurse_type
        )

        return JSONResponse(
            content={"message": "Nurse type updated successfully", "status": 200},
            status_code=200
        )

    except Exception as e:
        print("Edit Nurse Type Error:", str(e))
        return JSONResponse(
            content={"message": "An error has occurred", "status": 500},
            status_code=500
        )

async def admin_delete_service(request: Request, response: Response, id: int, role: str):
    try:
        await db.execute(
            "DELETE FROM shifts WHERE facility_id = $1 AND role ILIKE $2",
            id, role
        )

        return JSONResponse(
            content={"message": "Service deleted successfully", "status": 200},
            status_code=200
        )

    except Exception as e:
        print("Delete Service Error:", str(e))
        return JSONResponse(
            content={"message": "An Error has occurred", "status": 500},
            status_code=500
        )
    
shift_index_storage = {}

async def save_shift_index_map(sender: str, shift_index_map: dict):
    """Save the shift index map for a given sender."""
    shift_index_storage[sender] = shift_index_map

async def get_shift_index_map(sender: str) -> dict:
    """Retrieve the shift index map for a given sender."""
    return shift_index_storage.get(sender, {})

# def parse_dates_from_text(text: str) -> list:
#     """
#     Extracts valid date strings from the nurse's input using fuzzy matching.
#     Returns a list of strings in 'YYYY-MM-DD' format.
#     """
#     words = re.split(r"[.,;:\s]+", text)
#     potential_dates = []

#     for i in range(len(words)):
#         chunk = " ".join(words[i:i+3])  # check trigrams like "10 July", "7/10", etc.
#         parsed = dateparser.parse(chunk, settings={"PREFER_DATES_FROM": "future"})
#         if parsed:
#             potential_dates.append(parsed.strftime("%Y-%m-%d"))

#     return list(set(potential_dates))  # remove duplicates
def parse_dates_from_text(text: str, current_year: int = datetime.now().year):
    # Match common date formats: 7/12, 12-07, July 13, etc.
    date_patterns = re.findall(r'(?:(?:\d{1,2}[/-]\d{1,2})|(?:\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}))', text, re.IGNORECASE)
    parsed_dates = []
    for date_str in date_patterns:
        try:
            # If input is like 7/13, assume year = current year
            parsed = date_parser.parse(date_str, default=datetime(current_year, 1, 1))
            parsed_dates.append(parsed.strftime('%Y-%m-%d'))
        except Exception as e:
            print(f"Failed to parse: {date_str} -> {e}")
    return parsed_dates

def is_past_halfway(start_str, end_str, shift_date_str):
    start_time = datetime.strptime(f"{shift_date_str} {start_str}", "%Y-%m-%d %H:%M")
    end_time = datetime.strptime(f"{shift_date_str} {end_str}", "%Y-%m-%d %H:%M")

    # Handle overnight shift
    if end_time <= start_time:
        end_time += timedelta(days=1)

    shift_mid = start_time + (end_time - start_time) / 2
    current_time = datetime.now()

    return current_time > shift_mid

async def get_shift_start_end(facility_name, nurse_type, shift_type):
    shift_time_fields = {
        "AM": ("am_time_start", "am_time_end"),
        "PM": ("pm_time_start", "pm_time_end"),
        "NOC": ("noc_time_start", "noc_time_end")
    }
    time_fields = shift_time_fields.get(shift_type.upper())
    if not time_fields:
        return None, None

    facility_row = await db.fetchrow("SELECT id FROM facilities WHERE name ILIKE $1", facility_name)
    if not facility_row:
        return None, None
    facility_id = facility_row["id"]

    shift_start_field, shift_end_field = time_fields
    time_row = await db.fetchrow(
        f"SELECT {shift_start_field}, {shift_end_field} FROM shifts WHERE facility_id = $1 AND role = $2",
        facility_id, nurse_type
    )
    if time_row:
        return time_row[shift_start_field], time_row[shift_end_field]
    return None, None
    
async def nurse_chat_bot(sender, text):
    from app.controller.shiftController import (
    check_shift_status, shift_cancellation_nurse, check_shift_validity,
    get_shift_id_by_name, search_shift_by_id, search_by_date
    )
    from app.controller.coordinatorController import (
    update_coordinator_chat_history, update_coordinator)
    confirmed_dates = []
    try:
        await update_nurse_chat_history(sender, text, "received")
    except Exception as e:
        print("Error updating chat history:", e)

    try:
        past_messages = await get_nurse_chat_data(sender)
        reply_message = await generateReplyFromAINurse(text, past_messages)
        print("Generated reply message:", reply_message)
        if isinstance(reply_message, str):
            reply_message = reply_message.strip()
            if reply_message.startswith("```json"):
                reply_message = reply_message.replace("```json", "").replace("```", "").strip()
            elif reply_message.startswith("```"):
                reply_message = reply_message.replace("```", "").strip()

            try:
                reply_message = json.loads(reply_message)
            except Exception as parse_err:
                print("Failed to parse AI reply:", parse_err)
                raise HTTPException(status_code=500, detail="Invalid AI response format.")

        await update_nurse_chat_history(sender, reply_message["message"], "sent")
        print("replyMessage for nurse:", reply_message)

        resend_shift_id = await cache.get(sender + "_resend_notification_shift_id")
        facility_names = reply_message.get("facility_name")
        print(facility_names,"Hi Priya")
        if resend_shift_id:
            if text.lower().strip() == "yes":
                shift_detail = await search_shift_by_id(resend_shift_id)

                if not shift_detail:
                    await cache.delete(sender + "_resend_notification_shift_id")
                    return {"message": "❌ Sorry, the shift was not found or may have been removed."}

                shift_date = shift_detail["date"]
                facility = shift_detail["facility_name"]  # ✅ Correct key
                nurse_type = shift_detail["nurse_type"]
                shift_val = shift_detail["shift_value"]

                # ✅ Check if shift is still valid for this nurse
                valid_shift = await check_shift_validity(resend_shift_id, sender)
                if not valid_shift:
                    await cache.delete(sender + "_resend_notification_shift_id")
                    return {"message": "❌ Sorry, you're not eligible for this shift anymore."}

                # ✅ Check if shift already filled
                status = await check_shift_status(resend_shift_id, sender)
                if status == "filled":
                    await cache.delete(sender + "_resend_notification_shift_id")
                    return {"message": f"❌ Sorry, the shift on {convert_to_md(shift_date)} is already filled."}

                # ✅ Optional: Add half-shift time passed check if needed
                start_time, end_time = await get_shift_start_end(facility, nurse_type, shift_val)
                if start_time and end_time:
                    start_str = start_time.strftime("%H:%M")
                    end_str = end_time.strftime("%H:%M")
                    if is_past_halfway(start_str, end_str, shift_date.strftime("%Y-%m-%d")):
                        await cache.delete(sender + "_resend_notification_shift_id")
                        return {"message": f"The shift you asked to cover at {facility} on {convert_to_md(shift_date)} cannot be accepted. More than half of the shift has already passed. Please choose a different shift."}

                # ✅ If all checks pass
                await update_coordinator(resend_shift_id, sender)
                await cache.delete(sender + "_resend_notification_shift_id")
                return {"message": f"Thanks! I've marked you for the selected shift on {convert_to_md(shift_date)}."}


            elif text.lower().strip() == "no":
                await cache.delete(sender + "_resend_notification_shift_id")
                return {"message": "❎ No problem. Let us know if you're available for another shift."}

        # Helper function to format date
        def format_date(date_str: str) -> str:
            dt = datetime.strptime(normalize_date(date_str), "%Y-%m-%d")
            return convert_to_md(dt)
        def sanitize_facility_name(name: str) -> str:
            return name.strip()

        # Confirmation section (get shifts by facility, check validity, status, etc.)
        if reply_message.get("confirmation"):
            # facility_names = reply_message["facility_name"]
            # facility_names = facility_names if isinstance(facility_names, list) else [facility_names]
            # facility_names = [sanitize_facility_name(name) for name in facility_names]
            facility_names = reply_message.get("facility_name")
            # If facility_name is not provided directly, extract from confirmed_dates
            if not facility_names and "confirmed_dates" in reply_message:
                facility_names = list(reply_message["confirmed_dates"].keys())
            # Normalize to list and sanitize
            facility_names = facility_names if isinstance(facility_names, list) else [facility_names]
            facility_names = [sanitize_facility_name(name) for name in facility_names]
            nurse_info = await get_nurse_info(sender)
            nurse_type = nurse_info["nurse_type"]
            shift = nurse_info["shift"]
            for facility_name in facility_names:
            # ✅ Get all shift IDs for the facility and nurse type (ignore shift_value)
                shift_ids = await get_shift_id_by_name(facility_name, nurse_type, None, sender)  # shift=None

                if isinstance(shift_ids, list) and shift_ids:
                    details_array = await asyncio.gather(*[search_shift_by_id(id) for id in shift_ids])
                    formatted_items = []
                    shift_index_map = {}
                    for idx, detail in enumerate(details_array, start=1):
                        if detail and detail.get("date"):
                            formatted_date = format_date(detail["date"])
                            shift_val = detail["shift_value"]
                            nurse_t = detail.get("nurse_type", nurse_type)
                            index_display = f"{idx}."

                            formatted_items.append(
                                f"{index_display}️ {formatted_date} – {shift_val} – {facility_name}"
                            )
                            shift_index_map[str(idx)] = {
                                "date": detail["date"].strftime("%Y-%m-%d"),
                                "facility": facility_name,
                                "shift_value": shift_val,
                                "nurse_type": nurse_t
                            }
                    if formatted_items:
                        msg_lines = [
                            f"Thanks! Here are the available {nurse_type} shifts at {facility_name}:",
                            "",  # 👈 adds spacing above shift listing
                            *formatted_items,
                            "",
                            "👉 Reply with the number to grab your shift ✅"
                        ]
                        message = "\n".join(msg_lines)

                    await save_shift_index_map(sender, shift_index_map)
                    asyncio.create_task(send_message(sender, message))
                elif shift_ids:
                    valid_shift = await check_shift_validity(shift_ids, sender)
                    if not valid_shift:
                        continue
                    status = await check_shift_status(shift_ids, sender)
                    if status == "filled":
                        asyncio.create_task(send_message(sender, "Sorry, the shift has already been filled. We will update you when more shifts are available for you.")) 
                        continue
                    shift_detail = await search_shift_by_id(shift_ids)
                    if shift_detail:
                        shift_value = shift_detail["shift_value"]
                        shift_date = shift_detail["date"]
                        start_time, end_time = await get_shift_start_end(facility_name, nurse_type, shift_value)
                        if start_time and end_time:
                            start_str = start_time.strftime("%H:%M")
                            end_str = end_time.strftime("%H:%M")
                            if is_past_halfway(start_str, end_str, shift_date.strftime("%Y-%m-%d")):
                                asyncio.create_task(send_message(sender, f"The shift you asked to cover at {facility_name} on {convert_to_md(shift_date)} cannot be accepted. More than half of the shift has already passed. Please choose a different shift."))
                                continue

                    await update_coordinator(shift_ids, sender)
                    confirmed_dates.append(convert_to_md(shift_date))

                else:
                    print("No shift found")

        # Selection by index
        if reply_message.get("index_selection"):
            index_selection = reply_message["index_selection"]
            shift_index_map = await get_shift_index_map(sender)
            confirmed_dates = []
            for index in index_selection:
                index = str(index)
                if index in shift_index_map:
                    facility_name = sanitize_facility_name(shift_index_map[index]["facility"])
                    date = shift_index_map[index]["date"]
                    nurse_type = shift_index_map[index]["nurse_type"]
                    shift_value = shift_index_map[index]["shift_value"]
                    parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
                    shift_id = await search_by_date(str(parsed_date), facility_name, nurse_type, shift_value)
                    formatted_date = format_date(date)
                    if not shift_id:
                        asyncio.create_task(send_message(sender, f"The shift requested at {facility_name.title()} on {formatted_date} for {nurse_type} {shift_value} does not match your profile."))
                        continue
                    valid_shift = await check_shift_validity(shift_id, sender)
                    if not valid_shift:
                        continue
                    status = await check_shift_status(shift_id, sender)
                    if status == "filled":
                        asyncio.create_task(send_message(sender, f"Sorry, the shift on {formatted_date} at {facility_name.title()} has already been filled."))
                        continue
                    start_time, end_time = await get_shift_start_end(facility_name, nurse_type, shift_value)
                    if start_time and end_time:
                        start_str = start_time.strftime("%H:%M")
                        end_str = end_time.strftime("%H:%M")
                        if is_past_halfway(start_str, end_str, date):
                            asyncio.create_task(send_message(
                                sender,
                                f"The shift you asked to cover at {facility_name.title()} on {formatted_date} cannot be accepted. More than half of the shift has already passed. Please choose a different shift."
                            ))
                            continue
                    await update_coordinator(shift_id, sender)
                    confirmed_dates.append(formatted_date)
            if confirmed_dates:
                if len(confirmed_dates) == 1:
                    reply_message["message"] = f"Thanks! I've marked you for the selected shift on {confirmed_dates[0]}."
                else:
                    dates_str = ", ".join(confirmed_dates)
                    reply_message["message"] = f"Thanks! I've marked you for the selected shifts on {dates_str}."
                return {"message": reply_message["message"]}
            # else:
            #     return {"message": "None of the selected shifts could be booked. Please try different options or dates."}

        # Direct confirmation using detected dates and known nurse type/shift
        if not reply_message.get("index_selection") and not reply_message.get("confirmed_dates"):
            parsed_dates = parse_dates_from_text(text)
            if parsed_dates:
                nurse_info = await get_nurse_info(sender)
                nurse_type = nurse_info["nurse_type"]
                shift = nurse_info["shift"]
                facility_names = reply_message["facility_name"]
                facility_names = facility_names if isinstance(facility_names, list) else [facility_names]
                facility_names = [sanitize_facility_name(name) for name in facility_names]

                for date in parsed_dates:
                    for facility_name in facility_names:
                        shift_id = await search_by_date(date, facility_name, nurse_type, shift)
                        # formatted_date = format_date(date)
                        formatted_date = convert_to_md(date)
                        if not shift_id:
                            asyncio.create_task(send_message(sender, f"No shift found for {formatted_date} at {facility_name} for {nurse_type} {shift} shift"))
                            continue

                        valid_shift = await check_shift_validity(shift_id, sender)
                        if not valid_shift:
                            continue

                        status = await check_shift_status(shift_id, sender)
                        if status == "filled":
                            asyncio.create_task(send_message(sender, f"Sorry, the shift on {formatted_date} has already been filled."))
                            continue

                        await update_coordinator(shift_id, sender)
                        confirmed_dates.append(formatted_date)

                if confirmed_dates:
                    if len(confirmed_dates) == 1:
                        reply_message["message"] = f"Thanks! I've marked you for the selected shift on {confirmed_dates[0]}."
                    else:
                        reply_message["message"] = f"Thanks! I've marked you for the selected shifts on {', '.join(confirmed_dates)}."

        # Confirmation by specific date(s)
        # if reply_message.get("confirmed_dates"):
        #     nurse_info = await get_nurse_info(sender)
        #     nurse_type = nurse_info["nurse_type"]
        #     shift = nurse_info["shift"]
        #     print("Confirmed by date:", reply_message["confirmed_dates"])
        #     for facility_name, dates in reply_message["confirmed_dates"].items():
        #         facility_name = sanitize_facility_name(facility_name)
        #         date_list = dates if isinstance(dates, list) else [dates]
        #         print("Dates:", date_list)
        #         for date in date_list:
        #             shift_id = await search_by_date(date, facility_name, nurse_type, shift)
        #             print("Shift ID checking by date:", shift_id)
        #             formatted_date = format_date(date)
        #             if not shift_id:
        #                 asyncio.create_task(send_message(sender, f"No shift found for {formatted_date} at {facility_name} for {nurse_type} {shift} shift"))
        #                 continue
                
        #             valid_shift = await check_shift_validity(shift_id, sender)
        #             if not valid_shift:
        #                 continue
        #             status = await check_shift_status(shift_id, sender)
        #             if status == "filled":
        #                 asyncio.create_task(send_message(sender, "Sorry, the shift has already been filled. We will update you when more shifts are available for you.")) 
        #                 continue
        #             await update_coordinator(shift_id, sender)
        #             confirmed_dates.append(formatted_date)
        #     if confirmed_dates:
        #         if len(confirmed_dates) == 1:
        #             reply_message["message"] = f"Thanks! I've marked you for the selected shift on {confirmed_dates[0]}."
        #         else:
        #             dates_str = ", ".join(confirmed_dates)
        #             reply_message["message"] = f"Thanks! I've marked you for the selected shifts on {dates_str}."

        # Cancellation
        if reply_message.get("shift_details") and reply_message.get("cancellation"):
            shift_details = reply_message["shift_details"]
            shift_details = shift_details if isinstance(shift_details, list) else [shift_details]
            nurse_info = await get_nurse_info(sender)
            nurse_type = nurse_info["nurse_type"]
            shift = nurse_info["shift"]
            for shift_detail in shift_details:
                await shift_cancellation_nurse(
                    nurse_type,
                    shift,
                    shift_detail["date"],
                    sender
                )

        # Follow-up to coordinator
        if reply_message.get("follow_up_reply"):
            coordinator_email, coordinator_phone = await follow_up_reply(sender, reply_message["coordinator_message"])
            await update_coordinator_chat_history(coordinator_email, reply_message["coordinator_message"], "sent")
            await update_coordinator_chat_history(coordinator_phone, reply_message["coordinator_message"], "sent")

        return {"message": reply_message["message"]}

    except Exception as e:
        print("Error generating response:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Sorry, something went wrong.")
