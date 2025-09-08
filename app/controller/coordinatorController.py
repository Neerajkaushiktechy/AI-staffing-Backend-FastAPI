import re
from app.utils.cache import cache
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
from app.utils.convert_date import extract_date_from_text,normalize_to_date
from datetime import datetime, timedelta

async def update_coordinator(shift_id: int, nurse_phone_number: str):
    try:
        nurse = await get_nurse_info(nurse_phone_number)

        if not nurse:
            print("Nurse not found.")
            return

        await update_shift_status(shift_id, nurse.get("id"))
        recipient = await get_coordinator_number(shift_id)
        shift_info = await get_shift_information(shift_id)
        if nurse and shift_info:
            formatted_date = normalize_date(shift_info["date"])
            date_obj = formatted_date if isinstance(formatted_date, str) else str(formatted_date)
            date_obj = date_obj.split("T")[0]  # assumes ISO format
            y, m, d = date_obj.split("-")
            final_date = f"{m.zfill(2)}-{d.zfill(2)}-{y}"
            final_date = convert_to_md(final_date)
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
            WHERE id = $1 AND is_deleted = false
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
            WHERE id = (
                SELECT facility_id 
                FROM shift_tracker 
                WHERE id = $1 AND is_deleted = FALSE
            )
            AND is_deleted = FALSE
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
            WHERE (coordinator_phone = $1 OR coordinator_email = $1)
              AND is_deleted = false
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
            WHERE id = $1 AND is_deleted = false
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
            WHERE (coordinator_phone = $1 OR coordinator_email = $1)
              AND is_deleted = false
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
            WHERE (coordinator_phone = $1 OR coordinator_email = $1)
            AND is_deleted = false
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
                print("follow up message", reply_message)
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
            SELECT * FROM coordinator WHERE facility_id = $1 AND is_deleted = FALSE
        """, id)
        return JSONResponse(content={"coordinators": [serialize_row(row) for row in rows], "status": 200})
    except Exception as e:
        print("Error fetching coordinators by facility:", str(e))
        raise HTTPException(status_code=500, detail="An error has occurred")
    
async def admin_get_coordinator_by_id(request: Request, response: Response, id: int):
    try:
        row = await db.fetchrow("""
            SELECT * FROM coordinator WHERE id = $1 AND is_deleted = FALSE
        """, id)
        return JSONResponse(content={"coordinatorData": [serialize_row(row)], "status": 200})
    except Exception as e:
        print("Error fetching coordinator by ID:", str(e))
        raise HTTPException(status_code=500, detail="An error has occurred")

async def admin_delete_coordinator(request: Request, response: Response, id: int):
    try:
        await db.execute("""
            UPDATE coordinator
            SET is_deleted = TRUE
            WHERE id = $1
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
            SELECT id FROM coordinator WHERE (coordinator_phone = $1 OR coordinator_email = $1) AND is_deleted = false
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


def is_greeting(text):
    greetings = ["hi", "hello", "hey", "hii", "heyy", "yo", "sup", "good morning", "good evening", "how are you", "gm", "ge"]
    cleaned = text.strip().lower()
    return any(cleaned.startswith(greet) for greet in greetings)

def is_intended_shift_message(text: str) -> bool:
    """
    Detects if the message is intended for shift booking
    by checking keywords or valid date formats.
    """
    text = text.lower().strip()

    # ✅ 1. Keyword-based detection
    if re.search(r"\b(shift|am|pm|noc|book|booking|schedule|nurse|cna|lvn|rn|date|delete|get|provide|what|available|open|filled|today|tomorrow)\b", text):
        return True

    # ✅ 2. Date-based detection
    date_formats = ["%m/%d", "%m-%d", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"]
    for fmt in date_formats:
        try:                                    
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue

    # ✅ 3. Regex date patterns (handles partials like 9/6)
    if re.match(r"^\d{1,2}[/\-]\d{1,2}([/\-]\d{2,4})?$", text):
        return True

    return False

def is_search_intent(text: str) -> bool:
    text = text.lower()
    return (
        ("shift" in text)
        and (
            re.search(r"\b(what|show|list|get)\b", text)
            or re.search(r"\b(open|available|filled)\b", text)
        )
    )

async def coordinator_chat_bot(sender,text):
    from app.helper.promptHelper import generateReplyFromAI
    from app.controller.nurseController import search_nurses, send_nurses_message
    from app.controller.shiftController import create_shift, search_shift, search_shift_by_id, delete_shift, search_shifts_in_db,update_conversation_state,get_conversation_state
    from app.controller.instructionController import handle_instruction_update_request, handle_index_reply_for_instruction, handle_instruction_text_reply, handle_shift_field_update_text  # ✅ imported new functions
    from app.controller.shiftDeletionHandler import (
    handle_index_reply_for_shift_deletion,
    handle_shift_delete_request,
    handle_delete_all_shifts,
    handle_deletion_confirmation,
    fetch_all_shifts_for_coordinator
    )
    await update_coordinator_chat_history(sender, text, "received")
    past_messages = await get_coordinator_chat_data(sender)

    # First: Handle final confirmation of deletion (yes/no)
    response_from_confirmation = await handle_deletion_confirmation(sender, text, db, cache)
    if response_from_confirmation:
        return response_from_confirmation

    # Second: Handle shift deletion by index
    response_from_index_delete = await handle_index_reply_for_shift_deletion(sender, text, db, cache)
    if response_from_index_delete:
        return response_from_index_delete

    # Third: Handle instruction update by index
    response_from_index = await handle_index_reply_for_instruction(sender, text, db, cache)
    if response_from_index:
        return response_from_index

    #  Fourth: Handle case where user is replying with update info (e.g., "Change to RN AM on 7/1")
    response_from_field_update = await handle_shift_field_update_text(sender, text, db, cache)
    if response_from_field_update:
        return response_from_field_update

    # Fifth: Handle case where user is replying with simple instruction text (fallback)
    response_from_instruction_text = await handle_instruction_text_reply(sender, text, db, cache)
    if response_from_instruction_text:
        return response_from_instruction_text
    
    # Eight: Handle shift deletion by index
    response_from_index_delete = await handle_index_reply_for_shift_deletion(sender, text, db, cache)
    if response_from_index_delete:
        return response_from_index_delete
    
    # Optional: Clear instruction context if delete intent detected
    if any(word in text.lower() for word in ["delete", "remove", "cancel", "delte"]):
        await cache.delete(sender + "_pending_instruction")

    try:

        # ❌ If not intended → skip AI and just reply politely
        if not is_intended_shift_message(text) and not is_greeting(text):
            await db.execute("""
        DELETE FROM incomplete_shift_info
        WHERE sender = $1
    """, sender)

            return {
                "message": "Hello! How can I assist you today?",
                "nurse_details": None
            }
        reply_message = await generateReplyFromAI(text, past_messages)
        print("AI Reply:", reply_message)
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
        
        # ✅ Handle AI sample prompt block for instruction update
        if reply_message.get("instruction_update_request") is None and "Which of these shifts" in reply_message.get("message", ""):
            return await handle_instruction_update_request(sender, {"instruction": text}, db, cache)
    
        # Handle delete_all request
        if reply_message.get("delete_all"):
            if not await cache.get(sender + "_pending_delete_all_confirmation"):
                shifts = await fetch_all_shifts_for_coordinator(sender, db)
                if not shifts:
                    return {"message": "You don't have any upcoming shifts to delete."}
                await cache.set(sender + "_pending_delete_all_confirmation", "true")
                return {
                    "message": f"⚠️ You have {len(shifts)} upcoming shift(s).\nAre you sure you want to delete *all*?\nReply 'yes' to confirm or 'no' to cancel."
                }

        #  Handle AI-detected shift delete request by nurse_type, shift, date
        if "shift_delete_request" in reply_message:
            req = reply_message["shift_delete_request"]

            if not req["nurse_type"] or not req["shift"]:  # Missing info
                # If only date is provided, show all shifts on that date
                matching_shifts = await search_shifts_in_db(
                    date=req["date"], sender_phone=sender
                )
                if not matching_shifts:
                    return {"message": f"No shifts found on {convert_to_md(req['date'])}."}

                if len(matching_shifts) == 1:
                    shift = matching_shifts[0]
                    await cache.set(sender + "_pending_deletion_confirmation", json.dumps({"shifts": [shift]}))

                    return {
                        "message": (
                            f"⚠️ Just to confirm — you want to delete this shift:\n"
                            f"1) {convert_to_md(shift['date'])} – {shift['shift']}, {shift['nurse_type']}, {shift['status'].capitalize()}\n\n"
                            "Type 'yes' to delete or 'no' to keep them."
                        )
                    }

                # Multiple shifts — show index list
                await cache.set(sender + "_awaiting_shift_delete", json.dumps({
                    "shifts": matching_shifts
                }))

                response_lines = [
                    "Here are the shifts I found for you 👇",
                ]
                for idx, s in enumerate(matching_shifts, start=1):
                    date = convert_to_md(s.get("date")) if s.get("date") else "Unknown date"
                    shift = s.get("shift", "Unknown shift")
                    nurse_type = s.get("nurse_type", "Unknown nurse type")
                    nurse_name = s.get("nurse_name")
                    nurse_phone = s.get("nurse_phone")
                    status = s.get("status", "Unknown status").lower()

                    # format nurse info only if status is filled and nurse details exist
                    if status == "filled" and nurse_name and nurse_phone:
                        status_icon = "● Filled"
                        response_lines.append(f"{idx}. {date} - {shift} - {nurse_type} - {status_icon}")
                    else:
                        status_icon = "○ Open" if status == "open" else f"● {status.capitalize()}"
                        response_lines.append(f"{idx}. {date} - {shift} - {nurse_type} - {status_icon}")
                response_lines.append("")
                response_lines.append("💡 Reply with the *number* of the shift you’d like me to delete.")
                return {"message": "\n".join(response_lines)}

            else:
                # Proceed with normal delete logic (nurse_type + shift known)
                return await handle_shift_delete_request(reply_message, sender, db, cache)
        response_text = reply_message.get("message", "")

        #  Handle instruction update request with possible multiple matches
        if reply_message.get("instruction_update_request"):
            return await handle_instruction_update_request(sender, reply_message["instruction_update_request"], db, cache)

        if is_greeting(text):
            return {
                "message": "Hello! How can I assist you today?",
                "nurse_details": None
            }
        
        # 🚨 Handle search first so create-flow does not hijack it
        if is_search_intent(text):
            reply_message["intent"] = "search_shifts"
            # return reply_message
        
        # Step A: Load partial state if exists
        # 
        # if not reply_message.get("nurse_details") and not reply_message.get("intent") == "create_shift":
        if (not reply_message.get("nurse_details")and reply_message.get("intent") not in ["create_shift", "search_shifts"]):
            incomplete = await get_conversation_state(sender, db)

            # 2️⃣ Parse user input (FIXED)
            user_input = text.upper()
            parts = [p.strip() for p in user_input.replace(",", " ").split() if p.strip()]

            found_nurse_type = next((p for p in parts if p in ["CNA", "LVN", "RN"]), None)
            found_shift = next((p for p in parts if p in ["AM", "PM", "NOC"]), None)
            # found_date = next(
            #     (extract_date_from_text(p) for p in parts if extract_date_from_text(p)), None
            # )

            found_date = None
            for p in parts:
                parsed = extract_date_from_text(p)
                if parsed:
                    found_date = parsed
                    break


            # Count how many fields are in this message
            # new_fields_count = len([x for x in [found_nurse_type, found_shift, found_date] if x])

            # ✅ If message contains at least 2 new fields → start a fresh shift request
            # if new_fields_count >= 2:
            #     await db.execute("DELETE FROM incomplete_shift_info WHERE sender = $1", sender)
            #     incomplete = {"nurse_type": None, "shift": None, "date": None}

            # Detect if user is in an incomplete flow
            has_partial_info = any([
                incomplete.get("nurse_type"),
                incomplete.get("shift"),
                incomplete.get("date")
            ])

            # ❌ If user sends something irrelevant during incomplete state → reset conversation
            if (
                has_partial_info
                and not found_nurse_type
                and not found_shift
                and not found_date
            ):
                await db.execute("DELETE FROM incomplete_shift_info WHERE sender = $1", sender)
                return {
                    "message": "Hello! How can I assist you today?"
                }

            # ✅ Update conversation state with any found values
            if found_nurse_type:
                incomplete["nurse_type"] = found_nurse_type
                await update_conversation_state(sender, db, {"nurse_type": found_nurse_type})

            if found_shift:
                incomplete["shift"] = found_shift
                await update_conversation_state(sender, db, {"shift": found_shift})

            # if found_date:
            #     iso_date_str = found_date
            #     incomplete["date"] = iso_date_str
            #     await update_conversation_state(sender, db, {"date": iso_date_str})

            if found_date:
                incomplete["date"] = found_date.isoformat()
                await update_conversation_state(sender, db, {"date": found_date})

            # ✅ Check if any fields are still missing
            missing_parts = []
            if not incomplete.get("nurse_type"):
                missing_parts.append("nurse type (CNA/LVN/RN)")
            if not incomplete.get("shift"):
                missing_parts.append("shift (AM/PM/NOC)")
            if not incomplete.get("date"):
                missing_parts.append("date")

            if missing_parts:
                return {
                    "message": "To create a shift, I still need: " + ", ".join(missing_parts)
                }
            # ✅ If all fields are available → proceed with shift creation
            reply_message["nurse_details"] = [{
                "nurse_type": incomplete["nurse_type"],
                "shift": incomplete["shift"],
                "date": incomplete["date"]
            }]
            reply_message["intent"] = "create_shift"

        VALID_NURSE_TYPES = ["CNA", "LVN", "RN"]

        if reply_message.get("nurse_details"):
            nurse_details_list = (
                reply_message["nurse_details"]
                if isinstance(reply_message["nurse_details"], list)
                else [reply_message["nurse_details"]]
            )

            created_shifts = []
            failed_shifts = []

            for nurse_detail in nurse_details_list:
                if nurse_detail is None:
                    continue

                nurse_type = nurse_detail["nurse_type"]
                shift = nurse_detail["shift"]
                date = nurse_detail["date"]
                additional_instructions = nurse_detail.get("additional_instructions", "")

                if not nurse_type:
                    failed_shifts.append(f"The nurse type '{nurse_type}' is not valid. Valid types: {', '.join(VALID_NURSE_TYPES)}.")
                    continue
                # Check for invalid nurse type spelling
                if nurse_type.upper() not in VALID_NURSE_TYPES:
                    failed_shifts.append(f"The nurse type '{nurse_type}' is not valid. Valid types: {', '.join(VALID_NURSE_TYPES)}.")
                    continue

                # Check if coordinator has access to the nurse type
                nurse_exists = await check_nurse_type(sender, nurse_type)
                if not nurse_exists:
                    failed_shifts.append(
                        f"You are not eligible to create shifts for the '{nurse_type}' nurse type. "
                        "Please select a nurse type you are eligible for."
                    )
                    continue
                if reply_message.get("intent") == "create_shift":
                    pass

                if not reply_message.get("instruction_update_target") and additional_instructions:
                    last = await db.fetchval(
                        "SELECT last_created_shift FROM coordinator WHERE (coordinator_phone = $1 OR coordinator_email = $1) AND is_deleted = false",
                        sender
                    )
                    if last:
                        last_shift = json.loads(last)
                        shift_id = last_shift.get("shift_id")
                        nurse_type = last_shift.get("nurse_type")
                        date = last_shift.get("date")
                        shift = last_shift.get("shift")
                        if shift_id:
                            await db.execute(
                                "UPDATE shift_tracker SET additional_instructions = $1 WHERE id = $2",
                                additional_instructions,
                                shift_id
                            )
                            msg = f"✅ Instruction added to shift{date, nurse_type, shift} thanks\""
                            await update_coordinator_chat_history(sender, msg, "sent")
                            return {"message": msg}

                if reply_message.get("instruction_update_target"):
                    target = reply_message["instruction_update_target"]
                    shift_id = target.get("id")
                    additional_instructions = target.get("additional_instructions")

                    if shift_id and additional_instructions:
                        await db.execute(
                            "UPDATE shift_tracker SET additional_instructions = $1 WHERE id = $2",
                            additional_instructions,
                            shift_id
                        )
                        msg = f"✅ Instruction added to shift ID {shift_id}: \"{additional_instructions}\""
                        await update_coordinator_chat_history(sender, msg, "sent")
                        return {"message": msg}

                shift_date = normalize_to_date(date)
                today = datetime.now().date()
                now = datetime.now().time()

                # Reject Past Dates
                if shift_date < today:
                    formatted_date = convert_to_md(normalize_date(date))
                    failed_shifts.append(f"⚠️ Oops! {formatted_date} has already passed. Please provide a future date.")
                    continue

                if not shift:
                    failed_shifts.append("Please specify a valid shift (AM, PM, or NOC) to proceed with booking.")
                    continue

                # Step 2: If Today, Check Shift Start Time
                if shift_date == today:
                    # shift_time_fields = {
                    #     "AM": "am_time_start",
                    #     "PM": "pm_time_start",
                    #     "NOC": "noc_time_start"
                    # }
                    # shift_start_field = shift_time_fields.get(shift.upper())

                    # if shift_start_field:
                    #     coordinator = await db.fetchrow(
                    #         "SELECT facility_id FROM coordinator WHERE coordinator_phone = $1 OR coordinator_email = $1",
                    #         sender
                    #     )
                    #     if coordinator:
                    #         facility_id = coordinator["facility_id"]
                    #         time_row = await db.fetchrow(
                    #             f"SELECT {shift_start_field} FROM shifts WHERE facility_id = $1 AND role = $2",
                    #             facility_id, nurse_type
                    #         )
                    #         if time_row and time_row[shift_start_field]:
                    #             shift_start_time = time_row[shift_start_field]

                    #             if now >= shift_start_time:
                    #                 msg = f"⚠️ Booking not allowed. The {shift.upper()} shift for {nurse_type} has already started at {shift_start_time.strftime('%I:%M %p')}."
                    #                 return {"message": msg}
                    now = datetime.now()
                    shift_time_fields = {
                        "AM": ("am_time_start", "am_time_end"),
                        "PM": ("pm_time_start", "pm_time_end"),
                        "NOC": ("noc_time_start", "noc_time_end")
                    }
                    time_fields = shift_time_fields.get(shift.upper())

                    if time_fields:
                        shift_start_field, shift_end_field = time_fields
                        coordinator = await db.fetchrow(
                            "SELECT facility_id FROM coordinator WHERE (coordinator_phone = $1 OR coordinator_email = $1) AND is_deleted = false",
                            sender
                        )
                        if coordinator:
                            facility_id = coordinator["facility_id"]
                            time_row = await db.fetchrow(
                                f"SELECT {shift_start_field}, {shift_end_field} FROM shifts WHERE facility_id = $1 AND role = $2",
                                facility_id, nurse_type
                            )
                            if time_row and time_row[shift_start_field] and time_row[shift_end_field]:
                                # Extract start and end time (these are `datetime.time` objects)
                                shift_start_time = time_row[shift_start_field]
                                shift_end_time = time_row[shift_end_field]

                                # Convert to datetime.datetime
                                shift_start_dt = datetime.combine(now.date(), shift_start_time)
                                shift_end_dt = datetime.combine(now.date(), shift_end_time)
                                # If end time is past midnight
                                if shift_end_dt <= shift_start_dt:
                                    shift_end_dt += timedelta(days=1)

                                cutoff_time = shift_start_dt + ((shift_end_dt - shift_start_dt) / 2)
                                if now >= cutoff_time:
                                    failed_shifts.append(
                                        f"⚠️ Booking not allowed. The {shift.upper()} shift for {nurse_type} started at "
                                        f"{shift_start_time.strftime('%I:%M %p')} and the booking cutoff was "
                                        f"{cutoff_time.strftime('%I:%M %p')}."
                                    )
                                    continue

                # Proceed with Shift Creation
                shift_result = await create_shift(sender, nurse_type, shift, date, additional_instructions)
                if isinstance(shift_result, dict) and "error" in shift_result:
                    failed_shifts.append(shift_result["error"])
                    continue

                await db.execute(
                    "UPDATE coordinator SET last_created_shift = $1 WHERE coordinator_phone = $2 OR coordinator_email = $2",
                    json.dumps({
                        "shift_id": shift_result,
                        "nurse_type": nurse_type,
                        "shift": shift,
                        "date": date
                    }),
                    sender
                )
                await db.execute("DELETE FROM incomplete_shift_info WHERE sender = $1", sender)

                shift_id = shift_result
                nurses = await search_nurses(nurse_type, shift, shift_id)
                await send_nurses_message(nurses, nurse_type, shift, shift_id, date, additional_instructions)

                created_shifts.append(f"{nurse_type} {shift} on {convert_to_md(date)}")

            # Final message
            if created_shifts:
                shift_word = "shift" if len(created_shifts) == 1 else "shifts"
                msg = f"The {', '.join(created_shifts)} {shift_word} have been accepted. You will receive confirmation soon."
                if failed_shifts:
                    msg += "\n\nSome of your requested shifts couldn’t be booked:\n" + "\n".join(failed_shifts)
            else:
                msg = "\n".join(failed_shifts)

            return {"message": msg}
        
        # if reply_message.get("shift_details") and reply_message.get("cancellation"):
        #     shift_details_list = (
        #         reply_message["shift_details"]
        #         if isinstance(reply_message["shift_details"], list)
        #         else [reply_message["shift_details"]]
        #     )
        #     for shift_detail in shift_details_list:
        #         await search_shift(
        #             shift_detail["nurse_type"],
        #             shift_detail["shift"],
        #             shift_detail["date"],
        #             sender
        #         )

        # if reply_message.get("shift_id") and reply_message.get("cancellation"):
        #     shift_ids = (
        #         reply_message["shift_id"]
        #         if isinstance(reply_message["shift_id"], list)
        #         else [reply_message["shift_id"]]
        #     )
        #     deleted_shift_ids = []

        #     for shift_id in shift_ids:
        #         is_valid = await validate_shift_before_cancellation(shift_id, sender)
        #         if not is_valid:
        #             continue
        #         shift_details = await search_shift_by_id(shift_id)
        #         if not shift_details:
        #             continue
        #         deleted = await delete_shift(
        #             shift_id,
        #             sender,
        #             shift_details["nurse_id"],
        #             shift_details["nurse_type"],
        #             shift_details["shift_value"],
        #             shift_details["location"],
        #             shift_details["date"],
        #             shift_details["facility_name"]
        #         )
        #         if deleted:
        #             deleted_shift_ids.append(str(shift_id))

        #     if deleted_shift_ids:
        #         if len(deleted_shift_ids) == 1:
        #             msg = f"The shift with ID {deleted_shift_ids[0]} has been deleted."
        #         else:
        #             msg = f"The shifts with IDs {', '.join(deleted_shift_ids)} have been deleted."
        #         asyncio.create_task(send_message(sender, msg))

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
            # today = datetime.today().date()
            #  # Inject today's date if no date provided
            # if not requested_date and not requested_start_date and not requested_end_date:
            #     requested_start_date = today.isoformat()
            #     print("No date provided, using today and future dates from:", requested_start_date)
            #     if "message" in reply_message:
            #         reply_message["message"] = "Here are the shifts you have booked for today and upcoming days."

            #  # Case 1: Specific date (e.g., 7/30)
            # if requested_date:
            #     date_obj = datetime.strptime(requested_date, "%Y-%m-%d").date()
            #     if date_obj < today:
            #         response_text = (
            #             f"The date you requested {date_obj.strftime('%-m/%-d')} has already passed. "
            #             "We can't book or display shifts for past dates."
            #         )
            #         return {"message": response_text}

            # # Case 2: Date range
            # if requested_start_date and requested_end_date:
            #     start_obj = datetime.strptime(requested_start_date, "%Y-%m-%d").date()
            #     end_obj = datetime.strptime(requested_end_date, "%Y-%m-%d").date()

            #     if end_obj < today:
            #         response_text = "That range has already passed. No shifts available for past date ranges."
            #         return {"message": response_text}

            #     if start_obj < today:
            #         requested_start_date = today.isoformat()
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
              status_icon = {"open": "○", "filled": "●"}
              for idx, s in enumerate(actual_shifts, start=1):
                    if requested_status and s['status'] != requested_status:
                        continue  # Skip non-matching shifts
                    formatted_date = datetime.strptime(s['date'], "%Y-%m-%d").strftime("%-m/%-d")
                    status_text = status_icon.get(s['status'], "⚪")
                    if s['status'] == "filled" and s.get('nurse_name') and s.get('nurse_phone'):
                        line = f"{idx}. {formatted_date} - {s['shift']} - {s['nurse_type']} - {s['nurse_name']} ({s['nurse_phone']}) {status_text} Filled"
                    else:
                        line = f"{idx}. {formatted_date} - {s['shift']} - {s['nurse_type']} - {status_text} Open"

                    shift_list_lines.append(line)  # <<-- This line must be inside the loop

              response_text = "Here are the shifts that match your request 👇\n\n" + "\n".join(shift_list_lines)
            else:
              response_text = "I couldn’t find any shifts matching your request."
              reply_message["nurse_details"] = None
              reply_message["shift_information"] = None

        else:
         # Fallback if no shift info (just use AI response message)
           response_text = reply_message.get("message", "")

        return {"message": response_text}

    except Exception as e:
        print("Error generating response:", e)
        raise HTTPException(status_code=500, detail="Sorry, something went wrong.")