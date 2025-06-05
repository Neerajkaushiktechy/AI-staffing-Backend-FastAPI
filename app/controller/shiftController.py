from app.database import db
from app.controller.nurseController import search_nurses, send_nurses_message, check_nurse_availability
from app.controller.coordinatorController import update_coordinator_chat_history
from app.utils.send_message import send_message
from app.utils.normalizeDate import normalize_date
from math import radians, sin, cos, sqrt, atan2
import asyncio
from datetime import datetime
from fastapi import Request, Response, HTTPException
from app.utils.serialize_row import serialize_row
from app.utils.convert_mm_dd_yyyy_to_mm_dd import convert_to_md
async def create_shift(
    created_by: str,
    nurse_type: str,
    shift: str,
    date: str,
    additional_instructions: str,
    nurse_id: int = None,
    status: str = "open"
):
    try:
        # Get facility and coordinator ID
        facility = await db.fetchrow("""
            SELECT facility_id, id
            FROM coordinator
            WHERE coordinator_phone = $1 OR coordinator_email = $1
        """, created_by)

        facility_id = facility["facility_id"]
        coordinator_id = facility["id"]
        date = datetime.strptime(date, "%Y-%m-%d").date()
        # Insert shift record
        result = await db.fetchrow("""
            INSERT INTO shift_tracker (
                nurse_type, shift, nurse_id, status, date,
                facility_id, coordinator_id, booked_by, additional_instructions
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, nurse_type, shift, nurse_id, status, date,
             facility_id, coordinator_id, "bot", additional_instructions)

        return result["id"]

    except Exception as err:
        print("Error creating shift:", err)

async def check_shift_status(shift_id: int, phone_number: str):
    try:
        result = await db.fetch(
            """
            SELECT status
            FROM shift_tracker
            WHERE id = $1
            """,
            shift_id
        )

        if result:
            return result[0]["status"]
        else:
            message = "The shift ID you provided does not match any of the shifts. Make sure you have provided the correct ID."
            asyncio.create_task(send_message(phone_number, message))
            return None
    except Exception as e:
        print("Error checking shift status:", e)
        return None

async def search_shift(nurse_type, shift, date, created_by):
    try:
        date = datetime.strptime(date, "%Y-%m-%d").date()
        facility = await db.fetchrow("""
            SELECT facility_id 
            FROM coordinator 
            WHERE coordinator_phone = $1 OR coordinator_email = $1
        """, created_by)
        
        if not facility:
            asyncio.create_task(send_message(created_by, "Coordinator not found."))
            return
        
        facility_id = facility['facility_id']
        rows = await db.fetch("""
            SELECT * FROM shift_tracker
            WHERE nurse_type ILIKE $1
              AND shift ILIKE $2
              AND date = $3
              AND facility_id = $4
        """, nurse_type, shift, date, facility_id)

        if rows:
            facility_info = await db.fetchrow("""
                SELECT city_state_zip, name 
                FROM facilities 
                WHERE id = $1
            """, facility_id)
            location = facility_info['city_state_zip']
            name = facility_info['name']

            if len(rows) == 1:
                shift_id = rows[0]['id']
                nurse_id = rows[0]['nurse_id']
                await delete_shift(shift_id, created_by, nurse_id, nurse_type, shift, location, date, name)
            else:
                message = f"We found multiple shifts matching your request:\n\n"
                for i, shift_row in enumerate(rows):
                    nurse_name = "Not assigned"
                    nurse_id = shift_row['nurse_id']
                    if nurse_id:
                        result = await db.fetchrow("""
                            SELECT first_name 
                            FROM nurses 
                            WHERE id = $1
                        """, nurse_id)
                        if result:
                            nurse_name = result['first_name']
                    formatted_date = normalize_date(shift_row['date'])
                    formatted_date = convert_to_md(formatted_date)
                    message += f"{i + 1}. {shift_row['nurse_type']} nurse ({nurse_name}) at {name}, {location} on {formatted_date}\n ID:{shift_row['id']}\n"
                message += "\nPlease reply with the number of the shift you'd like to cancel."
                await update_coordinator_chat_history(created_by, message, 'sent')
                asyncio.create_task(send_message(created_by, message)) 
        else:
            formatted_date = normalize_date(date)
            message = f"The cancellation request you raised for the {nurse_type} nurse for {shift} shift scheduled on {formatted_date} does not exist or has been deleted already."
            asyncio.create_task(send_message(created_by, message))
    except Exception as e:
        print("Error in search_shift:", e)

async def delete_shift(shift_id, created_by, nurse_id, nurse_type, shift_value, location, date, name):
    try:
        # Delete the shift and check if it was deleted
        result = await db.execute("DELETE FROM shift_tracker WHERE id = $1", shift_id)
        if result == "DELETE 0":
            return False  # No shift deleted

        # Notify nurse, if assigned
        if nurse_id:
            nurse_data = await db.fetchrow("""
                SELECT mobile_number 
                FROM nurses 
                WHERE id = $1
            """, nurse_id)
            if nurse_data:
                nurse_phone_number = nurse_data['mobile_number']
                formatted_date = normalize_date(date)
                formatted_date = convert_to_md(formatted_date)
                nurse_message = (
                    f"The shift you confirmed scheduled on {formatted_date} at {name} has been cancelled "
                    "by the coordinator. We are sorry for any inconvenience caused."
                )
                asyncio.create_task(send_message(nurse_phone_number, nurse_message)) 
        return True
    except Exception as error:
        print('Error deleting shift:', error)
        return False

async def search_shift_by_id(shift_id: int):
    # Get shift details
    shift = await db.fetchrow("""
        SELECT nurse_id, nurse_type, shift, facility_id, date
        FROM shift_tracker
        WHERE id = $1
    """, shift_id)

    if not shift:
        return None

    # Get facility details
    facility = await db.fetchrow("""
        SELECT city_state_zip, name
        FROM facilities
        WHERE id = $1
    """, shift['facility_id'])

    return {
        "nurse_id": shift['nurse_id'],
        "nurse_type": shift['nurse_type'],
        "shift_value": shift['shift'],
        "location": facility['city_state_zip'] if facility else '',
        "date": shift['date'],
        "facility_name": facility['name'] if facility else ''
    }

async def shift_cancellation_nurse(nurse_type, shift, date, phone_number):
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        nurse = await db.fetchrow("""
            SELECT * FROM nurses
            WHERE mobile_number = $1
        """, phone_number)

        if not nurse:
            return

        nurse_id = nurse['id']

        rows = await db.fetch("""
            SELECT * FROM shift_tracker
            WHERE nurse_type ILIKE $1
              AND shift ILIKE $2
              AND date = $3
              AND nurse_id = $4
        """, nurse_type, shift, date_obj, nurse_id)

        if not rows:
            formatted_date = normalize_date(date_obj)
            formatted_date = convert_to_md(formatted_date)
            message = f"The cancellation request you raised for the {nurse_type} nurse for {shift} shift scheduled on {formatted_date} does not exist or has been deleted already."
            asyncio.create_task(send_message(phone_number, message)) 
            return

        shift_data = rows[0]
        shift_id = shift_data['id']
        facility_id = shift_data['facility_id']
        coordinator_id = shift_data['coordinator_id']

        # Update shift to open
        await db.execute("""
            UPDATE shift_tracker 
            SET status = 'open',
                nurse_id = NULL
            WHERE id = $1
        """, shift_id)

        facility = await db.fetchrow("""
            SELECT city_state_zip, name
            FROM facilities
            WHERE id = $1
        """, facility_id)

        location = facility['city_state_zip'] if facility else ''
        name = facility['name'] if facility else ''
        formatted_date = normalize_date(date_obj)
        formatted_date = convert_to_md(formatted_date)
        # Message to nurse
        message_to_nurse = f"The shift you confirmed at {name} on {formatted_date} for {nurse_type} has been cancelled."
        asyncio.create_task(send_message(phone_number, message_to_nurse)) 

        # Get other nurses
        nurses = await search_nurses(nurse_type, shift, shift_id)
        nurses = [n for n in nurses if n['mobile_number'] != phone_number]
        
        await send_nurses_message(nurses, nurse_type, shift, shift_id, date, "")

        # Notify coordinator
        coordinator = await db.fetchrow("""
            SELECT coordinator_phone, coordinator_email
            FROM coordinator
            WHERE id = $1
        """, coordinator_id)

        if coordinator:
            message_to_creator = (
                f"Hello! Your shift request on {formatted_date} for a {nurse_type} nurse has been cancelled by the nurse. "
                f"We are looking for another to help cover it. Sorry for any inconvenience caused."
            )
            asyncio.create_task(send_message(coordinator['coordinator_phone'], message_to_creator))

    except Exception as error:
        print("Error cancelling nurse confirmed shift:", error)

async def check_shift_validity(shift_id: int, nurse_phone_number: str) -> bool:
    shift_data = await db.fetchrow("""
        SELECT shift, facility_id, nurse_type, date
        FROM shift_tracker
        WHERE id = $1
    """, shift_id)

    if not shift_data:
        asyncio.create_task(send_message(nurse_phone_number, "The shift does not exist."))
        return False

    shift = shift_data['shift']
    facility_id = shift_data['facility_id']
    nurse_type = shift_data['nurse_type']
    date = shift_data['date']

    formatted_date = normalize_date(date)
    formatted_date = datetime.strptime(formatted_date, "%Y-%m-%d").strftime("%m-%d-%Y")
    facility = await db.fetchrow("""
        SELECT lat, lng, name
        FROM facilities
        WHERE id = $1
    """, facility_id)

    if not facility:
        return False

    facility_lat = facility['lat']
    facility_lng = facility['lng']
    facility_name = facility['name']

    nurse = await db.fetchrow("""
        SELECT id, shift, location, nurse_type, lat, lng
        FROM nurses
        WHERE mobile_number = $1
    """, nurse_phone_number)

    if not nurse:
        return False

    nurse_id = nurse['id']
    nurse_shift = nurse['shift']
    nurse_type_from_db = nurse['nurse_type']
    nurse_lat = nurse['lat']
    nurse_lng = nurse['lng']

    def haversine_distance(lat1, lon1, lat2, lon2):
        R = 3959  # miles
        d_lat = radians(lat2 - lat1)
        d_lon = radians(lon2 - lon1)
        a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c

    distance = haversine_distance(facility_lat, facility_lng, nurse_lat, nurse_lng)
    location_match = distance <= 50

    if (
        shift.lower() != nurse_shift.lower()
        or not location_match
        or nurse_type.lower() != nurse_type_from_db.lower()
    ):
        asyncio.create_task(send_message(
            nurse_phone_number,
            f"The shift requested at {facility_name} on {formatted_date} does not match your profile."
        )) 
        return False

    is_available = await check_nurse_availability(nurse_id, shift_id)

    if not is_available:
        asyncio.create_task(send_message(
            nurse_phone_number,
            f"The shift you asked to cover at {facility_name} on {formatted_date} conflicts with your other shift and thus cannot be covered by you."
        ))
        return False

    return True

async def get_shift_id_by_name(facility_name: str, nurse_type: str, shift: str, sender: str):
    facility = await db.fetchrow("""
        SELECT id
        FROM facilities
        WHERE name ILIKE $1
    """, facility_name)

    if not facility:
        message = "The facility name you provided does not exist. Make sure the name is correct."
        asyncio.create_task(send_message(sender, message))
        raise Exception("Facility not found")

    facility_id = facility['id']

    shift_rows = await db.fetch("""
        SELECT id
        FROM shift_tracker
        WHERE nurse_type ILIKE $1
          AND shift ILIKE $2
          AND facility_id = $3
          AND status = 'open'
          AND nurse_id IS NULL
          AND date >= CURRENT_DATE
    """, nurse_type, shift, facility_id)

    if len(shift_rows) == 1:
        return shift_rows[0]['id']  # Return single shift ID
    elif len(shift_rows) > 1:
        return [row['id'] for row in shift_rows]  # Return list of shift IDs
    else:
        message = "There are no shifts matching your profile for the facility you provided. Please make sure you have provided the correct information."
        asyncio.create_task(send_message(sender, message)) 
        return None

async def search_by_date(date: str, facility_name: str, nurse_type: str, shift: str):
    date = datetime.strptime(date, "%Y-%m-%d").date()
    facility = await db.fetchrow("""
        SELECT id FROM facilities
        WHERE name ILIKE $1
    """, facility_name)

    if not facility:
        return None  # Facility not found
    
    facility_id = facility['id']

    shift_row = await db.fetchrow("""
        SELECT id FROM shift_tracker
        WHERE date = $1
          AND facility_id = $2
          AND nurse_type ILIKE $3
          AND shift ILIKE $4
    """, date, facility_id, nurse_type, shift)

    if not shift_row:
        return None  # No matching shift found

    return shift_row['id']

async def admin_get_shifts(request: Request, response: Response):
    try:
        params = request.query_params
        nurse_type = params.get("nurseType")
        facility_name = params.get("facility")
        shift = params.get("shift")
        status = params.get("status")

        filters = []
        values = []

        if nurse_type:
            values.append(nurse_type)
            filters.append(f"nurse_type = ${len(values)}")

        if shift:
            values.append(shift)
            filters.append(f"shift = ${len(values)}")

        if status:
            values.append(status)
            filters.append(f"status = ${len(values)}")
                    
        if facility_name:
            facility = await db.fetchrow(
                "SELECT id FROM facilities WHERE name = $1", facility_name
            )
            if facility:
                values.append(facility["id"])
                filters.append(f"facility_id = ${len(values)}")
            else:
                # If facility doesn't exist, return empty list (no results will match)
                return JSONResponse(content={"events": [], "status": 200}, status_code=200)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"SELECT * FROM shift_tracker {where_clause} ORDER BY date, shift"

        result = await db.fetch(query, *values)
        events = []

        for row in result:
            facility_id = row["facility_id"]
            shift_val = row["shift"]
            date = row["date"]

            # Nurse name
            if row["nurse_id"] is None:
                nurse_name = "Not assigned"
            else:
                nurse = await db.fetchrow(
                    "SELECT first_name, last_name FROM nurses WHERE id = $1",
                    row["nurse_id"]
                )
                nurse_name = f"{nurse['first_name']} {nurse['last_name']}"

            # Shift timings
            shift_row = await db.fetchrow(
                "SELECT * FROM shifts WHERE facility_id = $1 AND role ILIKE $2",
                facility_id, row["nurse_type"]
            )
            if not shift_row:
                continue

            shift_times = {
                "AM": (shift_row["am_time_start"], shift_row["am_time_end"]),
                "PM": (shift_row["pm_time_start"], shift_row["pm_time_end"]),
                "NOC": (shift_row["noc_time_start"], shift_row["noc_time_end"])
            }

            start_time, end_time = shift_times.get(shift_val, (None, None))
            if not start_time or not end_time:
                continue

            formatted_date = date.strftime("%Y-%m-%d")
            start = f"{formatted_date}T{start_time}"
            end = f"{formatted_date}T{end_time}"

            facility = await db.fetchrow("SELECT name FROM facilities WHERE id = $1", facility_id)
            facility_name = facility["name"] if facility else "Unknown"

            events.append({
                "id": row["id"],
                "title": f"{row['nurse_type']} at {facility_name}",
                "start": start,
                "end": end,
                "extendedProps": {
                    "nurse_type": row["nurse_type"],
                    "facility": facility_name,
                    "status": row["status"],
                    "date": row["date"].isoformat(),
                    "shift": row["shift"],
                    "nurse": nurse_name,
                },
            })

        return JSONResponse(content={"events": events, "status": 200}, status_code=200)

    except Exception as err:
        print("Error fetching shifts:", err)
        return JSONResponse(content={"error": "Failed to fetch shifts"}, status_code=500)

from fastapi import Request
from fastapi.responses import JSONResponse
from typing import Optional
import asyncio

async def admin_get_all_shifts(request: Request, response: Response):
    try:
        params = request.query_params
        search = params.get("search")
        page = int(params.get("page", 1))
        limit = int(params.get("limit", 10))
        offset = (page - 1) * limit

        if search:
            search_term = f"%{search.lower()}%"
            query = """
                SELECT 
                  s.*, 
                  CONCAT(n.first_name, ' ', n.last_name) AS nurse_name,
                  f.name AS facility_name,
                  CONCAT(c.coordinator_first_name, ' ', c.coordinator_last_name) AS coordinator_name
                FROM shift_tracker s
                LEFT JOIN nurses n ON s.nurse_id = n.id
                LEFT JOIN facilities f ON s.facility_id = f.id
                LEFT JOIN coordinator c ON s.coordinator_id = c.id
                WHERE 
                  LOWER(CONCAT(n.first_name, ' ', n.last_name)) ILIKE $1
                  OR LOWER(f.name) ILIKE $1
                  OR LOWER(CONCAT(c.coordinator_first_name, ' ', c.coordinator_last_name)) ILIKE $1
                  OR LOWER(s.nurse_type) ILIKE $1
                  OR LOWER(s.shift) ILIKE $1
                  OR LOWER(s.status) ILIKE $1
                ORDER BY s.id DESC
                LIMIT $2 OFFSET $3
            """
            count_query = """
                SELECT COUNT(*) AS total
                FROM shift_tracker s
                LEFT JOIN nurses n ON s.nurse_id = n.id
                LEFT JOIN facilities f ON s.facility_id = f.id
                LEFT JOIN coordinator c ON s.coordinator_id = c.id
                WHERE 
                  LOWER(CONCAT(n.first_name, ' ', n.last_name)) ILIKE $1
                  OR LOWER(f.name) ILIKE $1
                  OR LOWER(CONCAT(c.coordinator_first_name, ' ', c.coordinator_last_name)) ILIKE $1
                  OR LOWER(s.nurse_type) ILIKE $1
                  OR LOWER(s.shift) ILIKE $1
                  OR LOWER(s.status) ILIKE $1
            """
            values = [search_term, limit, offset]
            count_values = [search_term]
        else:
            query = """
                SELECT 
                  s.*, 
                  CONCAT(n.first_name, ' ', n.last_name) AS nurse_name,
                  f.name AS facility_name,
                  CONCAT(c.coordinator_first_name, ' ', c.coordinator_last_name) AS coordinator_name
                FROM shift_tracker s
                LEFT JOIN nurses n ON s.nurse_id = n.id
                LEFT JOIN facilities f ON s.facility_id = f.id
                LEFT JOIN coordinator c ON s.coordinator_id = c.id
                ORDER BY s.id DESC
                LIMIT $1 OFFSET $2
            """
            count_query = "SELECT COUNT(*) AS total FROM shift_tracker"
            values = [limit, offset]
            count_values = None

        # Execute both queries concurrently
        result, count_result = await asyncio.gather(
            db.fetch(query, *values),
            db.fetch(count_query, *count_values) if count_values else db.fetch(count_query)
        )

        total = int(count_result[0]["total"]) if count_result else 0

        return JSONResponse(
            content={
                "page": page,
                "limit": limit,
                "total": total,
                "totalPages": (total + limit - 1) // limit,
                "shifts": [
                    {
                        **serialize_row(shift),
                        "nurse_name": shift["nurse_name"] or "Not assigned",
                        "coordinator_name": shift["coordinator_name"] or "Not assigned"
                    } for shift in result
                ]
            },
            status_code=200
        )

    except Exception as e:
        print("Get All Shifts Error:", e)
        return JSONResponse(
            content={"message": "An Error has occurred", "status": 500},
            status_code=500
        )

async def admin_delete_shift(request: Request, response: Response, shift_id: int):
    try:
        # 1. Fetch shift details
        shift_details = await db.fetchrow("""
            SELECT coordinator_id, nurse_id, date, shift, nurse_type, status, facility_id
            FROM shift_tracker WHERE id = $1
        """, shift_id)

        if not shift_details:
            raise HTTPException(status_code=404, detail="Shift not found")

        coordinator_id = shift_details["coordinator_id"]
        nurse_id = shift_details["nurse_id"]
        shift_date = shift_details["date"]
        shift_type = shift_details["shift"]
        nurse_type = shift_details["nurse_type"]
        shift_status = shift_details["status"]
        facility_id = shift_details["facility_id"]

        # 2. Get coordinator contact
        coordinator_contact = await db.fetchrow("""
            SELECT coordinator_phone, coordinator_email
            FROM coordinator WHERE id = $1
        """, coordinator_id)

        phone = coordinator_contact["coordinator_phone"] if coordinator_contact else None
        email = coordinator_contact["coordinator_email"] if coordinator_contact else None

        # 3. Get facility name
        facility = await db.fetchrow("""
            SELECT name FROM facilities WHERE id = $1
        """, facility_id)

        facility_name = facility["name"] if facility else "Unknown Facility"

        # 4. Format date
        formatted_date = normalize_date(shift_date)
        formatted_date = datetime.strptime(formatted_date, "%Y-%m-%d").strftime("%m-%d-%Y")
        formatted_date = convert_to_md(formatted_date)
        message = (
            f"Hello, the shift for {nurse_type} on {formatted_date} for {shift_type} "
            f"shift has been deleted by the admin."
        )

        if phone:
            asyncio.create_task(send_message(phone, message))

        # 5. Notify nurse if needed
        if nurse_id and shift_status == "filled":
            nurse_contact = await db.fetchrow("""
                SELECT mobile_number, email FROM nurses WHERE id = $1
            """, nurse_id)

            nurse_phone = nurse_contact["mobile_number"] if nurse_contact else None
            if nurse_phone:
               asyncio.create_task(send_message(nurse_phone, message))

        # 6. Delete the shift
        await db.execute("""
            DELETE FROM shift_tracker WHERE id = $1
        """, shift_id)

        return JSONResponse(content={"message": "Shift deleted successfully", "status": 200})

    except Exception as e:
        print("Delete Shift Error:", str(e))
        raise HTTPException(status_code=500, detail="An error has occurred")

async def admin_add_shift(request: Request, response: Response):
    try:
        data = await request.json()
        facility = data.get("facility")
        facility = int(facility) if facility else None
        coordinator = data.get("coordinator")
        coordinator = int(coordinator) if coordinator else None
        position = data.get("position")
        date_obj = data.get("scheduleDate")
        schedule_date = datetime.strptime(date_obj, "%Y-%m-%d").date()
        nurse = data.get("nurse")
        nurse = int(nurse) if nurse else None
        additional_notes = data.get("additionalNotes")
        shift = data.get("shift")

        # Insert the shift
        await db.execute("""
            INSERT INTO shift_tracker
            (facility_id, coordinator_id, nurse_id, nurse_type, date, shift, status, booked_by, additional_instructions)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """, facility, coordinator, nurse, position, schedule_date, shift, 'filled', 'admin', additional_notes)

        # Fetch facility details
        facility_details = await db.fetchrow("""
            SELECT * FROM facilities WHERE id = $1
        """, facility)

        facility_name = facility_details["name"] if facility_details else ""
        facility_location = facility_details["city_state_zip"] if facility_details else ""

        # Fetch nurse details
        nurse_details = await db.fetchrow("""
            SELECT * FROM nurses WHERE id = $1
        """, nurse)

        nurse_first_name = nurse_details["first_name"] if nurse_details else ""
        nurse_last_name = nurse_details["last_name"] if nurse_details else ""
        nurse_email = nurse_details["email"] if nurse_details else ""
        nurse_phone = nurse_details["mobile_number"] if nurse_details else ""

        # Fetch coordinator details
        coordinator_details = await db.fetchrow("""
            SELECT * FROM coordinator WHERE id = $1
        """, coordinator)

        coordinator_phone = coordinator_details["coordinator_phone"] if coordinator_details else ""

        # Format date
        formatted_date = normalize_date(schedule_date)
        formatted_date = datetime.strptime(formatted_date, "%Y-%m-%d").strftime("%m-%d-%Y")
        formatted_date = convert_to_md(formatted_date)
        message_nurse = (
            f"A new shift at {facility_name} on {formatted_date} for {shift} shift. "
            f"Notes: {additional_notes} has been assigned to you by the admin."
        )

        message_coordinator = (
            f"{nurse_first_name} {nurse_last_name} new nurse on {formatted_date} for {shift} shift "
            f"has been booked for you by the admin."
        )

        # Background message sending
        if nurse_phone:
            asyncio.create_task(send_message(nurse_phone, message_nurse))
        if coordinator_phone:
            asyncio.create_task(send_message(coordinator_phone, message_coordinator))

        return JSONResponse(content={"message": "Shift added successfully", "status": 200})

    except Exception as e:
        print("Add Shift Error:", str(e))
        raise HTTPException(status_code=500, detail="An error has occurred")


async def admin_get_shift_by_id(request: Request, response: Response, id: int):
    try:
        row = await db.fetchrow("SELECT * FROM shift_tracker WHERE id = $1", id)
        return JSONResponse(content={"shift": serialize_row(dict(row)) if row else None, "status": 200})
    except Exception as e:
        print("Error fetching shift details:", str(e))
        raise HTTPException(status_code=500, detail="An error has occurred")
    
async def admin_edit_shift(request: Request, response: Response, id: int):
    try:
        body = await request.json()
        facility = body.get("facility")
        facility = int(facility) if facility else None
        coordinator = body.get("coordinator")
        coordinator = int(coordinator) if coordinator else None
        position = body.get("position")
        schedule_date = body.get("scheduleDate")
        schedule_date = datetime.strptime(schedule_date, "%Y-%m-%d").date() if isinstance(schedule_date, str) else schedule_date
        nurse = body.get("nurse")
        nurse = int(nurse) if nurse else None
        shift = body.get("shift")
        additional_notes = body.get("additionalNotes")

        existing_shift = await db.fetchrow("SELECT * FROM shift_tracker WHERE id = $1", id)
        if not existing_shift:
            raise HTTPException(status_code=404, detail="Shift not found")

        old_nurse_id = existing_shift["nurse_id"]
        old_coordinator_id = existing_shift["coordinator_id"]
        old_date = existing_shift["date"]
        old_shift = existing_shift["shift"]
        old_position = existing_shift["nurse_type"]
        old_facility_id = existing_shift["facility_id"]

        facility_row = await db.fetchrow("SELECT name FROM facilities WHERE id = $1", facility)
        facility_name = facility_row["name"] if facility_row else "Unknown Facility"

        # 🧑‍⚕️ Nurse Notification Logic
        if nurse != old_nurse_id:
            if old_nurse_id:
                old_nurse = await db.fetchrow("SELECT first_name, mobile_number FROM nurses WHERE id = $1", old_nurse_id)
                if old_nurse:
                    formatted_date = datetime.strptime(str(old_date), "%Y-%m-%d").strftime("%m-%d-%Y")
                    formatted_date = convert_to_md(formatted_date)
                    message = f"Hi {old_nurse['first_name']}, your previously assigned shift for {old_position} on {formatted_date} ({old_shift} shift) at {facility_name} has been reassigned to another nurse. Thank you for your support."
                    asyncio.create_task(send_message(old_nurse["mobile_number"], message))

            if nurse:
                new_nurse = await db.fetchrow("SELECT first_name, mobile_number FROM nurses WHERE id = $1", nurse)
                if new_nurse:
                    formatted_date = schedule_date
                    formatted_date = convert_to_md(formatted_date)
                    message = f"Hi {new_nurse['first_name']}, you've been scheduled for a new {position} shift on {formatted_date} ({shift} shift) at {facility_name}. Notes: {additional_notes}"
                    asyncio.create_task(send_message(new_nurse["mobile_number"], message))

        elif nurse:
            nurse_details = await db.fetchrow("SELECT first_name, mobile_number FROM nurses WHERE id = $1", nurse)
            if nurse_details:
                formatted_date = schedule_date
                formatted_date = convert_to_md(formatted_date)
                message = f"Hi {nurse_details['first_name']}, there have been updates to your shift: {position} on {formatted_date} ({shift} shift) at {facility_name}. Notes: {additional_notes}. Please take note of the changes."
                asyncio.create_task(send_message(nurse_details["mobile_number"], message))

        # 🧑‍💼 Coordinator Notification Logic
        nurse_name = None
        if nurse:
            nurse_row = await db.fetchrow("SELECT first_name FROM nurses WHERE id = $1", nurse)
            nurse_name = nurse_row["first_name"] if nurse_row else "a nurse"

        if coordinator != old_coordinator_id:
            if old_coordinator_id:
                old_coord = await db.fetchrow("SELECT coordinator_first_name, coordinator_phone FROM coordinator WHERE id = $1", old_coordinator_id)
                if old_coord:
                    formatted_date = datetime.strptime(str(old_date), "%Y-%m-%d").strftime("%m-%d-%Y")
                    formatted_date = convert_to_md(formatted_date)
                    message = f"Dear {old_coord['coordinator_first_name']}, the coordination responsibility for the {old_position} shift on {formatted_date} ({old_shift} shift)has been assigned to another coordinator. Thank you for your efforts."
                    asyncio.create_task(send_message(old_coord["coordinator_phone"], message))

            if coordinator:
                new_coord = await db.fetchrow("SELECT coordinator_first_name, coordinator_phone FROM coordinator WHERE id = $1", coordinator)
                if new_coord:
                    formatted_date = schedule_date
                    formatted_date = convert_to_md(formatted_date)
                    message = f"Dear {new_coord['coordinator_first_name']}, you are now responsible for overseeing the {position} shift on {formatted_date} ({shift} shift), assigned to nurse {nurse_name}. Please ensure smooth coordination."
                    asyncio.create_task(send_message(new_coord["coordinator_phone"], message))

        elif coordinator:
            coord = await db.fetchrow("SELECT coordinator_first_name, coordinator_phone FROM coordinator WHERE id = $1", coordinator)
            if coord:
                formatted_date = schedule_date
                formatted_date = convert_to_md(formatted_date)
                message = f"Dear {coord['coordinator_first_name']}, the shift details under your coordination have been updated. New details: {position} on {formatted_date} ({shift} shift), assigned to nurse {nurse_name}. Additional Notes: {additional_notes}. Please review."
                asyncio.create_task(send_message(coord["coordinator_phone"], message))

        # Update shift in DB
        await db.execute("""
            UPDATE shift_tracker
            SET facility_id = $1, coordinator_id = $2, nurse_id = $3, nurse_type = $4, date = $5, shift = $6, status = $7, additional_instructions = $8
            WHERE id = $9
        """, facility, coordinator, nurse, position, schedule_date, shift, 'filled', additional_notes, id)

        return JSONResponse(content={"message": "Shift updated successfully", "status": 200})

    except Exception as e:
        print("Error editing shift:", str(e))
        raise HTTPException(status_code=500, detail="Server error")
