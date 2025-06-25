from app.database import db
from app.utils.send_message import send_message
from dotenv import load_dotenv
load_dotenv()
from app.helper.promptHelper import generate_follow_up_message_for_nurse
from app.controller.nurseController import update_nurse_chat_history
from app.utils.normalizeDate import normalize_date
import json
import asyncio
from fastapi import Request, Response, HTTPException
from app.utils.serialize_row import serialize_row
from fastapi.responses import JSONResponse
from app.utils.convert_mm_dd_yyyy_to_mm_dd import convert_to_md
from datetime import datetime
from app.utils.convert_date import extract_date_from_text

async def update_coordinator(shift_id: int, nurse_phone_number: str):
    try:
        nurse = await get_nurse_info(nurse_phone_number)

        if not nurse:
            print("Nurse not found.")
            return

        await update_shift_status(shift_id, nurse.get("id"))
        print('shift status updated')
        recipient = await get_coordinator_number(shift_id)
        shift_info = await get_shift_information(shift_id)
        print("recipient:", recipient)
        print("shift_info:", shift_info)
        if nurse and shift_info:
            print("Nurse and shift information found. Preparing to send message.")
            formatted_date = normalize_date(shift_info["date"])
            print("Formatted date:", formatted_date)
            date_obj = formatted_date if isinstance(formatted_date, str) else str(formatted_date)
            date_obj = date_obj.split("T")[0]  # assumes ISO format
            print("Date object:", date_obj)
            y, m, d = date_obj.split("-")
            final_date = f"{m.zfill(2)}-{d.zfill(2)}-{y}"
            final_date = convert_to_md(final_date)
            print("Final date:", final_date)
            message = (
                f"Hello! Your shift requested on {final_date} "
                f"for {nurse['nurse_type']} {shift_info['shift']} shift has been filled. "
                f"This shift will be covered by {nurse['first_name']}. "
                f"You can reach out via {nurse['mobile_number']}."
            )
            print("Message to be sent:", message)
            asyncio.create_task(send_message(recipient["coordinator_phone"], message))

        else:
            print("Missing nurse or shift information. Cannot send message.")
    except Exception as e:
        print("Error in update_coordinator:", e)

async def get_nurse_info(nurse_phone_number: str) -> dict | None:
    try:
        query = """
            SELECT *
            FROM nurses
            WHERE mobile_number = $1
            LIMIT 1
        """
        nurse = await db.fetchrow(query, nurse_phone_number)
        return dict(nurse) if nurse else None
    except Exception as e:
        print("Error fetching nurse information:", e)
        return None
    

async def update_shift_status(shift_id: int, nurse_id: int) -> None:
    try:
        query = """
            UPDATE shift_tracker
            SET status = 'filled',
                nurse_id = $2
            WHERE id = $1
        """
        await db.execute(query, shift_id, nurse_id)
    except Exception as e:
        print('Error updating shift status:', e)

async def get_coordinator_number(shift_id: int):
    try:
        shift_query = """
            SELECT coordinator_id 
            FROM shift_tracker
            WHERE id = $1
        """
        shift_row = await db.fetchrow(shift_query, shift_id)
        if not shift_row:
            return None

        coordinator_id = shift_row["coordinator_id"]

        coordinator_query = """
            SELECT coordinator_phone, coordinator_email
            FROM coordinator
            WHERE id = $1
        """
        coordinator_row = await db.fetchrow(coordinator_query, coordinator_id)

        if coordinator_row and coordinator_row["coordinator_phone"] and coordinator_row["coordinator_email"]:
            return {
                "coordinator_phone": coordinator_row["coordinator_phone"],
                "coordinator_email": coordinator_row["coordinator_email"]
            }
        return None
    except Exception as e:
        print("Error fetching coordinator number:", e)
        return None

async def get_shift_information(shift_id: int):
    try:
        # Get facility info using subquery
        facility_query = """
            SELECT city_state_zip, name
            FROM facilities
            WHERE id = (SELECT facility_id FROM shift_tracker WHERE id = $1)
        """
        facility = await db.fetchrow(facility_query, shift_id)
        location = facility["city_state_zip"] if facility and "city_state_zip" in facility else ""
        name = facility["name"] if facility and "name" in facility else ""

        # Get shift info
        shift_query = """
            SELECT date, shift
            FROM shift_tracker
            WHERE id = $1
        """
        shift = await db.fetchrow(shift_query, shift_id)
        if not shift:
            return None

        shift_info = {
            "date": shift["date"],
            "shift": shift["shift"],
            "location": location,
            "name": name
        }

        return shift_info
    except Exception as e:
        print("Error fetching shift information:", e)
        return None

async def update_coordinator_chat_history(sender: str, text: str, msg_type: str):
    try:
        await db.execute("""
            INSERT INTO coordinator_chat_data (sender, message, message_type)
            VALUES ($1, $2, $3)
        """, sender, text, msg_type)
    except Exception as err:
        print("Error updating coordinator chat history:", err)

async def get_coordinator_chat_data(sender: str):
    try:
        query = """
            SELECT message
            FROM coordinator_chat_data
            WHERE sender = $1
            LIMIT 50
        """
        result = await db.fetch(query, sender)
        past_messages = [row["message"] for row in result]
        return past_messages
    except Exception as error:
        print("Error getting coordinator chat data:", error)
        return []

async def validate_shift_before_cancellation(shift_id: int, phone_number: str) -> bool:
    try:
        # Fetch coordinator's facility_id
        coordinator_query = """
            SELECT facility_id
            FROM coordinator
            WHERE coordinator_phone = $1 OR coordinator_email = $1
        """
        coordinator = await db.fetchrow(coordinator_query, phone_number)
        if not coordinator:
            asyncio.create_task(send_message(phone_number, "Coordinator not found."))
            return False

        facility_id_coordinator = coordinator["facility_id"]

        # Check if shift exists and get its facility_id
        shift_query = """
            SELECT facility_id
            FROM shift_tracker
            WHERE id = $1
        """
        shift = await db.fetchrow(shift_query, shift_id)

        if not shift:
            message = f"The shift with ID {shift_id} does not exist. Please check and try again."
            asyncio.create_task(send_message(phone_number, message))
            return False

        if shift["facility_id"] != facility_id_coordinator:
            message = f"The shift with ID {shift_id} does not belong to your account. Please check and try again."
            asyncio.create_task(send_message(phone_number, message))
            return False

        return True

    except Exception as e:
        print("Error in validate_shift_before_cancellation:", e)
        return False

async def check_nurse_type(sender: str, nurse_type: str) -> bool:
    try:
        # Check if nurse_type exists
        type_query = """
            SELECT * 
            FROM nurse_type 
            WHERE nurse_type = $1
        """
        type_exists = await db.fetch(type_query, nurse_type)
        if not type_exists:
            return False

        # Get coordinator's facility_id
        facility_query = """
            SELECT facility_id
            FROM coordinator 
            WHERE coordinator_phone = $1 OR coordinator_email = $1
        """
        facility = await db.fetchrow(facility_query, sender)
        if not facility:
            return False

        facility_id = facility["facility_id"]

        # Check if shifts exist for that nurse_type in the facility
        shifts_query = """
            SELECT * 
            FROM shifts 
            WHERE role = $1 
              AND facility_id = $2
        """
        shifts = await db.fetch(shifts_query, nurse_type, facility_id)
        return len(shifts) > 0

    except Exception as e:
        print("Error in check_nurse_type:", e)
        return False
    
async def follow_up_message_send(sender: str, nurse_name_input: str, follow_up_message: str):
    try:
        # Get coordinator ID
        coordinator_query = """
            SELECT id
            FROM coordinator
            WHERE coordinator_phone = $1 OR coordinator_email = $1
        """
        coordinator = await db.fetchrow(coordinator_query, sender)
        if not coordinator:
            print("Coordinator not found.")
            return

        coordinator_id = coordinator["id"]

        # Get today's matching shifts
        matching_query = """
            SELECT 
                s.id AS shift_id,
                n.first_name,
                n.last_name,
                n.mobile_number,
                n.email,
                f.name,
                s.date
            FROM shift_tracker s
            JOIN nurses n ON s.nurse_id = n.id
            JOIN facilities f ON s.facility_id = f.id
            WHERE s.coordinator_id = $1
              AND s.date = CURRENT_DATE
              AND (
                LOWER(n.first_name) = LOWER($2) OR
                LOWER(n.first_name || ' ' || n.last_name) = LOWER($2)
              )
        """
        matching_shifts = await db.fetch(matching_query, coordinator_id, nurse_name_input)
        if not matching_shifts:
            asyncio.create_task(send_message(sender, f"No shift for {nurse_name_input} found for today."))
            print("No matching nurse shift found for today.")
            return

        sent_to = set()

        for shift in matching_shifts:
            first_name = shift["first_name"]
            last_name = shift["last_name"]
            full_name = f"{first_name} {last_name}"
            mobile_number = shift["mobile_number"]
            email = shift["email"]
            facility_name = shift["name"]

            recipient_key = f"{full_name}_{mobile_number}_{email}"
            if recipient_key in sent_to:
                continue

            try:
                reply_message = await generate_follow_up_message_for_nurse(full_name, follow_up_message, facility_name)
                print("follow uo message", reply_message)
                if isinstance(reply_message, str):
                    reply_message = reply_message.strip()
                    if reply_message.startswith("```json") or reply_message.startswith("```"):
                        reply_message = reply_message.replace("```json", "").replace("```", "").strip()
                    try:
                        reply_message = json.loads(reply_message)
                    except json.JSONDecodeError as parse_error:
                        print("Failed to parse AI reply:", parse_error)
                        return

                print("replyMessage:", reply_message)

                if mobile_number:
                    asyncio.create_task(send_message(mobile_number, reply_message["message"]))
                await update_nurse_chat_history(mobile_number, reply_message["message"], "sent")
                await update_nurse_chat_history(email, reply_message["message"], "sent")

                sent_to.add(recipient_key)
            except Exception as err:
                print(f"Failed to send message to {full_name}:", err)

    except Exception as e:
        print("Error in follow_up_message_send:", e)

async def admin_get_coordinators_by_facility(request: Request, response: Response, id: int):
    try:
        rows = await db.fetch("""
            SELECT * FROM coordinator WHERE facility_id = $1
        """, id)
        return JSONResponse(content={"coordinators": [serialize_row(row) for row in rows], "status": 200})
    except Exception as e:
        print("Error fetching coordinators by facility:", str(e))
        raise HTTPException(status_code=500, detail="An error has occurred")
    
async def admin_get_coordinator_by_id(request: Request, response: Response, id: int):
    try:
        row = await db.fetchrow("""
            SELECT * FROM coordinator WHERE id = $1
        """, id)
        return JSONResponse(content={"coordinatorData": [serialize_row(row)], "status": 200})
    except Exception as e:
        print("Error fetching coordinator by ID:", str(e))
        raise HTTPException(status_code=500, detail="An error has occurred")

async def admin_delete_coordinator(request: Request, response: Response, id: int):
    try:
        await db.execute("""
            DELETE FROM coordinator WHERE id = $1
        """, id)
        return JSONResponse(content={"message": "Coordinator deleted successfully", "status": 200})
    except Exception as e:
        print("Error deleting coordinator:", str(e))
        raise HTTPException(status_code=500, detail="An error has occurred")

from fastapi import HTTPException

async def send_shift_information_to_coordinator(sender: str, shift_info: dict):
    try:
        print("SHIFT INFO:", shift_info)
        base_query = "SELECT * FROM shift_tracker WHERE"
        conditions = []
        values = []

        # Get coordinator ID
        coordinator_row = await db.fetchrow("""
            SELECT id FROM coordinator WHERE coordinator_phone = $1 OR coordinator_email = $1
""", sender)

        if not coordinator_row:
            raise HTTPException(status_code=404, detail="Coordinator not found")

        coordinator_id = coordinator_row["id"]  # Extract the integer id

        conditions.append("coordinator_id = ${}".format(len(values) + 1))
        values.append(coordinator_id)

        # Dynamic filters
        if shift_info.get("date"):
            conditions.append("date = ${}".format(len(values) + 1))
            values.append(shift_info["date"])
        elif shift_info.get("start_date") and shift_info.get("end_date"):
            conditions.append("date BETWEEN ${} AND ${}".format(len(values) + 1, len(values) + 2))
            values.append(shift_info["start_date"])
            values.append(shift_info["end_date"])

        if shift_info.get("shift"):
            conditions.append("shift = ${}".format(len(values) + 1))
            values.append(shift_info["shift"])

        if shift_info.get("nurse_type"):
            conditions.append("nurse_type = ${}".format(len(values) + 1))
            values.append(shift_info["nurse_type"])

        if shift_info.get("status"):
            conditions.append("status = ${}".format(len(values) + 1))
            values.append(shift_info["status"])

        # Final query
        final_query = base_query + " " + " AND ".join(conditions)
        shift_records = await db.fetch(final_query, *values)
        print("Shift Records:", shift_records)
    # Format and send message
        if shift_records:
            shift_lines = []
            for shift in shift_records:
                date = normalize_date(shift['date'])
                date = convert_to_md(date)
                shift_lines.append(
                    f"- Date: {date}, Shift: {shift['shift']}, Nurse Type: {shift['nurse_type']}, Status: {shift['status']}"
                )
            shift_message = "Here are the shifts that match your criteria:\n" + "\n".join(shift_lines)
        else:
            shift_message = "No shifts found for the given criteria."

        asyncio.create_task(send_message(sender, shift_message))
        await update_coordinator_chat_history(sender, shift_message, "sent")
    except Exception as e:
        print("Error in send_shift_information_to_coordinator:", e)
        raise HTTPException(status_code=500, detail="An error has occurred while processing your request.")



async def coordinator_chat_bot(sender,text):
    from app.helper.promptHelper import generateReplyFromAI
    from app.controller.nurseController import search_nurses, send_nurses_message
    from app.controller.shiftController import create_shift, search_shift, search_shift_by_id, delete_shift, search_shifts_in_db
    await update_coordinator_chat_history(sender, text, "received")
    past_messages = await get_coordinator_chat_data(sender)
    try:
        reply_message = await generateReplyFromAI(text, past_messages)
        if isinstance(reply_message, str):
            reply_message = reply_message.strip()
            if reply_message.startswith("```json"):
                reply_message = reply_message.replace("```json", "").replace("```", "").strip()
            elif reply_message.startswith("```"):
                reply_message = reply_message.replace("```", "").strip()

            try:
                reply_message = json.loads(reply_message)
            except json.JSONDecodeError:
                raise HTTPException(status_code=500, detail="Invalid AI response format.")
        print("Parsed AI Reply:", reply_message)
        response_text = reply_message.get("message", "")
        
        # ✅ Handle nurse_details (shift creation or instruction-only update)
        if reply_message.get("nurse_details"):
            nurse_details_list = (
                reply_message["nurse_details"]
                if isinstance(reply_message["nurse_details"], list)
                else [reply_message["nurse_details"]]
            )
            for nurse_detail in nurse_details_list:
                if nurse_detail is None:
                    continue

                nurse_type = nurse_detail["nurse_type"]
                shift = nurse_detail["shift"]
                date = nurse_detail["date"]
                additional_instructions = nurse_detail.get("additional_instructions", "")

                # ✅ Check if nurse type is linked
                nurse_exists = await check_nurse_type(sender, nurse_type)
                if not nurse_exists:
                    response_text = f"❌ The service type '{nurse_type}' is not available for your facility. Please choose a different service type."
                    await update_coordinator_chat_history(sender, response_text, "sent")
                    return {"message": response_text}

               # ✅ Only update existing shift if a specific shift ID or update instruction is given
# (You can later enhance this to rely on `instruction_update_target` from the AI)
                if reply_message.get("instruction_update_target"):
                    target = reply_message["instruction_update_target"]
                    shift_id = target.get("id")
                    additional_instructions = target.get("additional_instructions")
                    
                    if shift_id and additional_instructions:
                        await db.execute(
                            """
                            UPDATE shift SET additional_instructions = $1
                            WHERE id = $2
                            """,
                            additional_instructions,
                            shift_id
                        )
                        msg = f"✅ Instruction added to shift ID {shift_id}: \"{additional_instructions}\""
                        await update_coordinator_chat_history(sender, msg, "sent")
                        return {"message": msg}

                shift_date = datetime.strptime(date, "%Y-%m-%d").date()
                today = datetime.now().date()
                now = datetime.now().time()

                # Step 1: Reject Past Dates
                if shift_date < today:
                    formatted_date = normalize_date(date)
                    formatted_date = convert_to_md(formatted_date)
                    msg = f"⚠️ Oops! {formatted_date} has already passed. Please provide a future date for the shift."
                    return {"message": msg}

                # Step 2: If Today, Check Shift Start Time
                if shift_date == today:
                    shift_time_fields = {
                        "AM": "am_time_start",
                        "PM": "pm_time_start",
                        "NOC": "noc_time_start"
                    }
                    shift_start_field = shift_time_fields.get(shift.upper())

                    if shift_start_field:
                        coordinator = await db.fetchrow(
                            "SELECT facility_id FROM coordinator WHERE coordinator_phone = $1 OR coordinator_email = $1",
                            sender
                        )
                        if coordinator:
                            facility_id = coordinator["facility_id"]
                            time_row = await db.fetchrow(
                                f"SELECT {shift_start_field} FROM shifts WHERE facility_id = $1 AND role = $2",
                                facility_id, nurse_type
                            )
                            if time_row and time_row[shift_start_field]:
                                shift_start_time = time_row[shift_start_field]

                                if now >= shift_start_time:
                                    msg = f"⚠️ Booking not allowed. The {shift.upper()} shift for {nurse_type} has already started at {shift_start_time.strftime('%I:%M %p')}."
                                    return {"message": msg}

                # Step 3: Proceed with Shift Creation
                shift_result = await create_shift(sender, nurse_type, shift, date, additional_instructions)
                print(shift_result, "shift_result")
                if isinstance(shift_result, dict) and "error" in shift_result:
                    error_msg = shift_result["error"]
                    print("Shift creation failed:", error_msg)
                    return {"message": f"{error_msg}"}

                shift_id = shift_result
                nurses = await search_nurses(nurse_type, shift, shift_id)
                print("Nurses found:", nurses)
                await send_nurses_message(nurses, nurse_type, shift, shift_id, date, additional_instructions)
        if reply_message.get("shift_details") and reply_message.get("cancellation"):
            shift_details_list = (
                reply_message["shift_details"]
                if isinstance(reply_message["shift_details"], list)
                else [reply_message["shift_details"]]
            )
            for shift_detail in shift_details_list:
                await search_shift(
                    shift_detail["nurse_type"],
                    shift_detail["shift"],
                    shift_detail["date"],
                    sender
                )

        if reply_message.get("shift_id") and reply_message.get("cancellation"):
            shift_ids = (
                reply_message["shift_id"]
                if isinstance(reply_message["shift_id"], list)
                else [reply_message["shift_id"]]
            )
            deleted_shift_ids = []

            for shift_id in shift_ids:
                is_valid = await validate_shift_before_cancellation(shift_id, sender)
                if not is_valid:
                    continue
                shift_details = await search_shift_by_id(shift_id)
                if not shift_details:
                    continue
                deleted = await delete_shift(
                    shift_id,
                    sender,
                    shift_details["nurse_id"],
                    shift_details["nurse_type"],
                    shift_details["shift_value"],
                    shift_details["location"],
                    shift_details["date"],
                    shift_details["facility_name"]
                )
                if deleted:
                    deleted_shift_ids.append(str(shift_id))

            if deleted_shift_ids:
                if len(deleted_shift_ids) == 1:
                    msg = f"The shift with ID {deleted_shift_ids[0]} has been deleted."
                else:
                    msg = f"The shifts with IDs {', '.join(deleted_shift_ids)} have been deleted."
                asyncio.create_task(send_message(sender, msg))

        if reply_message.get("follow_up") and reply_message.get("nurse_name"):
            await follow_up_message_send(sender, reply_message["nurse_name"], reply_message["follow_up_message"])
        if reply_message.get("shift_information"):
            shift_info = reply_message["shift_information"]

            # Extract the criteria from the AI's response
            requested_date = shift_info.get("date")
            requested_nurse_type = shift_info.get("nurse_type")
            requested_shift = shift_info.get("shift")
            requested_status = shift_info.get("status")
            requested_start_date = shift_info.get("start_date")
            requested_end_date = shift_info.get("end_date")

            # Call your database function to get the actual shifts
            actual_shifts = await search_shifts_in_db(
                date=requested_date,
                nurse_type=requested_nurse_type,
                shift=requested_shift,
                status=requested_status,
                start_date=requested_start_date,
                end_date=requested_end_date,
                sender_phone=sender # Pass sender to filter by coordinator's facility
            )
            print("actual_shifts", actual_shifts)
            if actual_shifts:
              shift_list_lines = []
              for s in actual_shifts:
                    shift_list_lines.append(
                        f"- Date: {s['date']}, Shift: {s['shift']}, Nurse Type: {s['nurse_type']}, Status: {s['status']}"
                    )
              response_text = "Here are the shifts that match your criteria:\n" + "\n".join(shift_list_lines)
            else:
              response_text = "I couldn't find any shifts matching your criteria."
              reply_message["nurse_details"] = None
              reply_message["shift_information"] = None

        else:
         # Fallback if no shift info (just use AI response message)
           response_text = reply_message.get("message", "")

        

        return {"message": response_text}

    except Exception as e:
        print("Error generating response:", e)
        raise HTTPException(status_code=500, detail="Sorry, something went wrong.")
