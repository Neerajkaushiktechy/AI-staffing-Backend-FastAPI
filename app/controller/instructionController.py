import json
from datetime import datetime
import re
from app.utils.convert_mm_dd_yyyy_to_mm_dd import convert_to_md


# async def handle_instruction_update_request(sender, request_data, db, cache):
#     nurse_type = request_data["nurse_type"]
#     shift = request_data["shift"]
#     date_str = request_data["date"]
#     date = datetime.strptime(date_str, "%Y-%m-%d").date()
#     instruction = request_data["instruction"]

#     results = await db.fetch(
#         """
#         SELECT s.id, s.nurse_type, s.shift, s.date, n.first_name AS nurse_name
#         FROM shift_tracker s
#         LEFT JOIN nurses n ON s.nurse_id = n.id
#         WHERE s.nurse_type = $1 AND s.shift = $2 AND s.date = $3
#         ORDER BY s.id ASC
#         """,
#         nurse_type, shift, date
#     )

#     if not nurse_type or not shift or not date:
#         return {"message": "Please specify the nurse type, shift time, and date to update a shift."}

#     # if len(results) == 1:
#     #     shift_id = results[0]["id"]
#     #     await cache.set(sender + "_awaiting_shift_update", json.dumps({
#     #         "shift_id": shift_id
#     #     }))
#     #     await cache.delete(sender + "_pending_instruction")  # just in case
#     #     formatted_date = convert_to_md(date)
#     #     return {
#     #         "message": f"What would you like to update for the {nurse_type} {shift} shift on {formatted_date}? You can update nurse type, shift time, date, or add special instructions."
#     #     }
#     if len(results) == 1:
#         shift = results[0]
#         shift_id = shift["id"]
    
#         await cache.set(sender + "_awaiting_instruction_target", json.dumps({
#             "id": shift_id,
#             "nurse_type": shift["nurse_type"],
#             "shift": shift["shift"],
#             "date": str(shift["date"]),
#         }))
#         await cache.delete(sender + "_pending_instruction")  # cleanup

#         return {
#             "message": f"📝 What instructions would you like to add for the {shift['nurse_type']} {shift['shift']} shift on {convert_to_md(shift['date'])}?"
#         }


#     # Multiple matches: show index list
#     indexed = []
#     msg_lines = ["Multiple matching shifts found:\n"]
#     for i, row in enumerate(results):
#         nurse = row["nurse_name"] or "None"
#         msg_lines.append(f"{i}. ID: {row['id']} | Nurse: {nurse} | {row['nurse_type']} {row['shift']} on {row['date']}")
#         indexed.append({
#             "index": i,
#             "id": row["id"],
#             "nurse_type": row["nurse_type"],
#             "shift": row["shift"],
#             "date": str(row["date"]),
#             "nurse_name": nurse
#         })

#     msg_lines.append("\nPlease reply with the index of the shift to update.")
#     await cache.set(sender + "_pending_instruction", json.dumps({
#         "instruction": instruction,
#         "matches": indexed
#     }))

#     return {"message": "\n".join(msg_lines)}

async def handle_instruction_update_request(sender, request_data, db, cache):
    instruction = request_data.get("instruction")
    nurse_type = request_data.get("nurse_type")
    shift = request_data.get("shift")
    date_str = request_data.get("date")

    # ✅ CASE: instruction is present but no shift info → show index list of upcoming shifts
    if instruction and (not nurse_type or not shift or not date_str):
        results = await db.fetch(
            """
            SELECT s.id, s.nurse_type, s.shift, s.date, n.first_name AS nurse_name
            FROM shift_tracker s
            LEFT JOIN nurses n ON s.nurse_id = n.id
            WHERE s.date >= CURRENT_DATE
            ORDER BY s.date ASC
            """
        )
        if not results:
            return {
                "message": "⚠️ No active or upcoming shifts found. Please mention the shift you'd like to add instructions to."
            }
        await cache.delete(sender + "_pending_instruction")
        indexed = []
        msg_lines = ["Which of these shifts would you like to add an instruction to?\n"]
        
        for i, row in enumerate(results, start=1):
            msg_lines.append(f"{i}. ID: {row['id']} | Type: {row['nurse_type']}, Shift: {row['shift']}, Date: {convert_to_md(row['date'])}")

            # msg_lines.append(f"{i}. ID: {row['id']} | {row['nurse_type']} {row['shift']} on {convert_to_md(row['date'])}")
            indexed.append({
                "index": i - 1,  # ✅ map back to 0-based index for selection
                "id": row["id"],
                "nurse_type": row["nurse_type"],
                "shift": row["shift"],
                "date": str(row["date"]),
                "nurse_name": row["nurse_name"] or "None"
            })
 
        msg_lines.append("Please reply with the index of the shift.")
        await cache.delete(sender + "_pending_instruction")  # 💥 Clear old cache before setting new one
        await cache.set(sender + "_pending_instruction", json.dumps({
            "instruction": instruction,
            "matches": indexed
        }))

        return {"message": "\n".join(msg_lines)}

    # ✅ If all required shift data is present
    if not nurse_type or not shift or not date_str:
        return {"message": "Please specify the nurse type, shift time, and date to update a shift."}

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return {"message": "Invalid date format. Use YYYY-MM-DD."}

    results = await db.fetch(
        """
        SELECT s.id, s.nurse_type, s.shift, s.date, n.first_name AS nurse_name
        FROM shift_tracker s
        LEFT JOIN nurses n ON s.nurse_id = n.id
        WHERE s.nurse_type = $1 AND s.shift = $2 AND s.date = $3
        ORDER BY s.id ASC
        """,
        nurse_type, shift, date
    )
    if len(results) == 1:
        shift = results[0]
        shift_id = shift["id"]

        await cache.set(sender + "_awaiting_instruction_target", json.dumps({
            "id": shift_id,
            "nurse_type": shift["nurse_type"],
            "shift": shift["shift"],
            "date": str(shift["date"]),
        }))
        await cache.delete(sender + "_pending_instruction")

        return {
            "message": f"📝 What instructions would you like to add for the {shift['nurse_type']} {shift['shift']} shift on {convert_to_md(shift['date'])}?"
        }
    

    if len(results) > 1:
        indexed = []
        msg_lines = ["Multiple matching shifts found:\n"]
        for i, row in enumerate(results):
            nurse = row["nurse_name"] or "None"
            msg_lines.append(f"{i+1}. ID: {row['id']} | Type: {row['nurse_type']}, Shift: {row['shift']}, Date: {convert_to_md(row['date'])}")

            indexed.append({
                "index": i-1,
                "id": row["id"],
                "nurse_type": row["nurse_type"],
                "shift": row["shift"],
                "date": str(row["date"]),
                "nurse_name": nurse
            })

        msg_lines.append("Please reply with the index of the shift to update.")
        await cache.delete(sender + "_pending_instruction")  # 💥 Clear old cache before setting new one
        await cache.set(sender + "_pending_instruction", json.dumps({
            "instruction": instruction,
            "matches": indexed
        }))

        return {"message": "\n".join(msg_lines)}

    return {"message": "No matching shifts found for the specified nurse type, shift, and date."}


def is_probably_index(text):
    return text.strip().isdigit()

async def handle_index_reply_for_instruction(sender, index_text, db, cache):
    pending_raw = await cache.get(sender + "_pending_instruction")
    # ✅ If no pending list is found but user typed an index like '3'
    if not pending_raw:
        if is_probably_index(index_text):  # they entered something like '3'
            return {
                "message": "⚠️ Please say 'I want to add an instruction' again to continue."
            }
        return None  # Let generateReplyFromAI handle it

    # ✅ If the message is *not* an index number, assume it’s a new instruction or unrelated message
    if not is_probably_index(index_text):
        await cache.delete(sender + "_pending_instruction")  # Exit index flow
        return None  # Let normal flow (e.g. generateReplyFromAI) handle it

    try:
        pending = json.loads(pending_raw)
        index = int(index_text.strip())
        matches = pending["matches"]
        if index < 1 or index > len(matches):
            return {
                "message": f"❌ Invalid index. Please enter a number between 1 and {len(matches)} for the matching shift."
            }

        # selected = pending["matches"][index]
        selected = pending["matches"][index - 1]

        shift_id = selected["id"]

        # await cache.set(sender + "_awaiting_shift_update", json.dumps({
        #     "shift_id": shift_id
        # }))
        await cache.set(sender + "_awaiting_instruction_target", json.dumps({
        "id": selected["id"],
        "nurse_type": selected["nurse_type"],
        "shift": selected["shift"],
        "date": selected["date"]
        }))

        # await cache.delete(sender + "_pending_instruction")

        return {
            "message": f"📝 What instructions would you like to add for the {selected['nurse_type']} {selected['shift']} shift on {convert_to_md(selected['date'])}?"
        }

    
    except (ValueError, IndexError):
        return {"message": "❌ Invalid index. Please enter a valid number from the list."}



async def handle_instruction_text_reply(sender, text, db, cache):
    pending_raw = await cache.get(sender + "_awaiting_instruction_target")
    if not pending_raw:
        return None  # No pending instruction target

    try:
        shift_data = json.loads(pending_raw)
        shift_id = shift_data["id"]

        # Apply the instruction
        await db.execute(
            "UPDATE shift_tracker SET additional_instructions = $1 WHERE id = $2",
            text.strip(),
            shift_id
        )

        await cache.delete(sender + "_awaiting_instruction_target")

        return {
        "message": f"✅ Instruction added for the {shift_data['nurse_type']} {shift_data['shift']} shift on {convert_to_md(shift_data['date'])}."
        }


    
    except Exception as e:
        return {
            "message": f"❌ Something went wrong while saving the instruction: {str(e)}"
        }
    
async def handle_shift_field_update_text(sender, text, db, cache):
    awaiting_raw = await cache.get(sender + "_awaiting_shift_update")
    if not awaiting_raw:
        return None

    data = json.loads(awaiting_raw)
    shift_id = data["shift_id"]
    cleaned_text = text.strip().lower() 

    updates = {}
    message_parts = []

    lowered = text.lower()

    # 🔄 Detect nurse type changes
    nurse_type_map = {"cna": "CNA", "rn": "RN", "lvn": "LVN"}
    nurse_type_matches = re.findall(r"(?:to|from)?\s*(cna|rn|lvn)", lowered)
    if nurse_type_matches:
        for nt in reversed(nurse_type_matches):  # last one wins
            if nt in nurse_type_map:
                updates["nurse_type"] = nurse_type_map[nt]
                message_parts.append(f"nurse type to {updates['nurse_type']}")
                break

    # 🔄 Detect shift time changes
    shift_map = {"am": "AM", "pm": "PM", "noc": "NOC"}
    shift_matches = re.findall(r"(?:to|from)?\s*(am|pm|noc)", lowered)
    if shift_matches:
        for sh in reversed(shift_matches):
            if sh in shift_map:
                updates["shift"] = shift_map[sh]
                message_parts.append(f"shift to {updates['shift']}")
                break

    # 📅 Detect date
    date_matches = re.findall(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", text)
    if date_matches:
       try:
        # pick the LAST date in the sentence — assuming user says "from X to Y"
        month, day, year = date_matches[-1]
        if not year:
            year = str(datetime.now().year)
        parsed_date = datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d").date()
        updates["date"] = parsed_date
        message_parts.append(f"date to {parsed_date.strftime('%-m/%-d')}")
       except Exception:
        pass

    # 📝 Detect and extract instructions if present
    instruction_phrases = ["instruction", "note", "comment", "nurse should", "special instruction"]
    if any(p in cleaned_text for p in instruction_phrases):
        match = re.search(r"(?:instruction|note|comment|nurse should.*?|special instruction)[:\-]?\s*(.+)", text, re.IGNORECASE)
        if match:
            instruction_text = match.group(1).strip()
            updates["additional_instructions"] = instruction_text
            message_parts.append(f"instructions: {instruction_text}")   

    # 📝 Fallback: treat text as special instructions if no field matched
    vague_replies = {"hi", "hello", "okay", "ok", "yes", "cool", "👍"}

    # Basic shift creation detection (user wants to do something new)
    shift_creation_keywords = {"create shift", "book shift", "need to create", "want to book", "schedule shift"}

    if not updates:
        if any(kw in cleaned_text for kw in shift_creation_keywords):
            await cache.delete(sender + "_awaiting_shift_update")
            return {
                "message": "Got it — let's handle that new shift separately. Please tell me the nurse type, shift time, and date.",
            }

        if cleaned_text in vague_replies:
        # 🧠 User said something casual — stop update flow and fall back to AI
           await cache.delete(sender + "_awaiting_shift_update")
           return None

        # Otherwise treat it as a valid instruction
        updates["additional_instructions"] = text.strip()
        message_parts.append(f'instructions: "{updates["additional_instructions"]}"')

    # 🔄 Update the DB
    if updates:
        set_clauses = [f"{field} = ${i+2}" for i, field in enumerate(updates)]

        if "nurse_type" in updates or "shift" in updates:
            row = await db.fetchrow("SELECT facility_id FROM shift_tracker WHERE id = $1", shift_id)
            if row:
                facility_id = row["facility_id"]
                # pull updated values or fallback to existing ones
                role_to_check = updates.get("nurse_type")
                shift_to_check = updates.get("shift")

                existing_shift = await db.fetchrow("SELECT nurse_type, shift FROM shift_tracker WHERE id = $1", shift_id)
                if existing_shift:
                    if not role_to_check:
                        role_to_check = existing_shift["nurse_type"]
                    if not shift_to_check:
                        shift_to_check = existing_shift["shift"]

                # validate against shifts table
                shift_field_map = {"AM": "am_time_start", "PM": "pm_time_start", "NOC": "noc_time_start"}
                time_field = shift_field_map.get(shift_to_check)

                if time_field:
                    shift_row = await db.fetchrow(
                        f"SELECT {time_field} FROM shifts WHERE facility_id = $1 AND role = $2",
                        facility_id, role_to_check  # ✅ DB uses `role`, not `nurse_type`
                    )
                    if not shift_row or not shift_row[time_field]:
                        return {
                            "message": f"⚠️ Sorry, {role_to_check} {shift_to_check} shift isn't set up at this facility. Please pick another combination."
                        }

        # ✅ Only runs if above validation passed
        sql = f"UPDATE shift_tracker SET {', '.join(set_clauses)} WHERE id = $1"
        values = [shift_id] + list(updates.values())
        await db.execute(sql, *values)

    await cache.delete(sender + "_awaiting_shift_update")

    summary = ", ".join(message_parts)
    return {"message": f"✅ Updated shift ID {shift_id}: {summary}"}
