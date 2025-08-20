import asyncio
import json
from app.controller.shiftController import search_shifts_in_db
from app.utils.convert_mm_dd_yyyy_to_mm_dd import convert_to_md
from app.database import db
from app.utils.normalizeDate import normalize_date
from app.utils.send_message import send_message
from datetime import datetime, timedelta
import re


VAGUE = {"hi", "hello", "hey", "ok", "okay", "yes", "no"}
DELETE_KEYWORDS = {"delete", "delte", "remove", "cancel", "i want to delete"}

async def can_delete_shift(shift, sender, db):
    """Returns (True, None) if shift can be deleted, or (False, reason_message) if blocked."""
    today = datetime.now().date()
    now = datetime.now()

    shift_date = normalize_date(shift["date"])
    shift_type = shift.get("shift", "Unknown shift")
    status = shift.get("status", "").lower()
    nurse_type = shift.get("nurse_type")
    shift_date_obj = datetime.strptime(shift_date, "%Y-%m-%d").date()

    # Past filled shifts
    if shift_date_obj < today and status == "filled":
        return False, (
            f"❌ Unable to delete {shift_type} shift on {convert_to_md(shift_date)} "
            f"because it is already filled and the time has passed."
        )

    # Ongoing shifts (today)
    if shift_date_obj == today:
        shift_time_fields = {
            "AM": ("am_time_start", "am_time_end"),
            "PM": ("pm_time_start", "pm_time_end"),
            "NOC": ("noc_time_start", "noc_time_end")
        }
        time_fields = shift_time_fields.get(shift_type.upper())
        if time_fields:
            shift_start_field, shift_end_field = time_fields
            coordinator = await db.fetchrow(
                "SELECT facility_id FROM coordinator WHERE coordinator_phone = $1 OR coordinator_email = $1",
                sender
            )
            if coordinator:
                facility_id = coordinator["facility_id"]
                time_row = await db.fetchrow(
                    f"SELECT {shift_start_field}, {shift_end_field} FROM shifts WHERE facility_id = $1 AND role = $2",
                    facility_id, nurse_type
                )
                if time_row and time_row[shift_start_field] and time_row[shift_end_field]:
                    shift_start_time = time_row[shift_start_field]
                    shift_end_time = time_row[shift_end_field]

                    # Combine with today's date
                    shift_start_dt = datetime.combine(today, shift_start_time)
                    shift_end_dt = datetime.combine(today, shift_end_time)
                    if shift_end_dt <= shift_start_dt:  # Overnight handling
                        shift_end_dt += timedelta(days=1)

                    if shift_start_dt <= now <= shift_end_dt:
                        return False, (
                            f"❌ Unable to delete {shift_type} shift on {convert_to_md(shift_date)} "
                            f"because it is currently ongoing ({shift_start_time.strftime('%I:%M %p')} - {shift_end_time.strftime('%I:%M %p')})."
                        )

    return True, None


# Delete shift by ID
async def delete_shift(shift_id, created_by, nurse_id=None, nurse_type=None, shift_value=None, location=None, date=None, name=None):
    try:
        # Fetch shift details before deletion
        shift = await db.fetchrow("""
            SELECT s.id, s.nurse_id, s.date, s.status, s.shift, s.nurse_type, n.mobile_number
            FROM shift_tracker s
            LEFT JOIN nurses n ON s.nurse_id = n.id
            WHERE s.id = $1
        """, shift_id)

        if not shift:
            return False

        # Mark as deleted
        result = await db.execute("UPDATE shift_tracker SET is_deleted = TRUE WHERE id = $1", shift_id)
        if result == "UPDATE 0":
            return False

        # Determine if this is a future filled shift
        shift_date = shift["date"]
        nurse_type = shift["nurse_type"]
        shift_type = shift["shift"]

        is_future_shift = shift_date >= datetime.now().date()

        is_filled = shift["status"] == "filled"

        if is_future_shift and is_filled and shift["mobile_number"]:
            formatted_date = convert_to_md(normalize_date(shift_date))
            nurse_message = (
                f"Hello, the shift for {nurse_type} on {formatted_date} for {shift_type} "
                f"shift has been deleted by the Facility Coordinator."
            )

            asyncio.create_task(send_message(shift["mobile_number"], nurse_message))

        # Existing logic if nurse_id is passed explicitly
        if nurse_id and not (is_future_shift and is_filled):
            nurse_data = await db.fetchrow("SELECT mobile_number FROM nurses WHERE id = $1", nurse_id)
            if nurse_data:
                nurse_phone = nurse_data["mobile_number"]
                formatted_date = convert_to_md(normalize_date(date))
                nurse_message = (
                    f"The shift you confirmed on {formatted_date} at {name} has been cancelled by the coordinator. "
                    "We are sorry for any inconvenience caused."
                )
                asyncio.create_task(send_message(nurse_phone, nurse_message))

        return True
    except Exception as e:
        print("❌ Error deleting shift:", e)
        return False

async def handle_index_reply_for_shift_deletion(sender, text, db, cache):
    awaiting_raw = await cache.get(sender + "_awaiting_shift_delete")
    if not awaiting_raw:
        return None

    cleaned = text.strip().lower()

    try:
        payload = json.loads(awaiting_raw)
        shifts = payload.get("shifts", [])
        is_single = payload.get("single", False)

        # ✅ Handle yes/no for single shift deletion
        if is_single:
            if cleaned == "yes":
                shift = shifts[0]
                deleted = await delete_shift(shift["id"], sender)
                # await cache.delete(sender + "_awaiting_shift_delete")
                if deleted:
                    return {"message": f"✅ Shift {shift['nurse_type']} {shift['shift']} on {convert_to_md(shift['date'])} deleted."}
                return {"message": "❌ Could not delete the shift."}

            elif cleaned == "no":
                await cache.delete(sender + "_awaiting_shift_delete")
                return {"message": "❎ Deletion cancelled."}

        # ✅ Handle vague or nonsense input (only if not single)
        if not any(ch.isdigit() for ch in cleaned):  # no numbers at all
            vague_responses = ["yes", "no", "ok", "okay", "done", "cancel", "thank you", "thanks", "sure"]

            if cleaned in vague_responses:
                await cache.delete(sender + "_awaiting_shift_delete")
                return {"message": "All set! Let me know if you need anything else 😊"}

            await cache.delete(sender + "_awaiting_shift_delete")
            return {"message": "⚠️ I couldn’t match your response to a shift number. Let’s start fresh if you’d like to try again."}

        # ✅ Extract all index numbers from the message
        index_strs = re.findall(r'\b\d+\b', cleaned)
        indexes = list(set(int(i) for i in index_strs if i.isdigit()))
        if not indexes:
            await cache.delete(sender + "_awaiting_shift_delete")
            return {
                "message": "✅ Got it. If you need anything else, just let me know!"
            }
        # ❌ If DELETE_KEYWORDS present but no valid indexes → cancel
        if any(kw in cleaned for kw in DELETE_KEYWORDS) and not indexes:
            await cache.delete(sender + "_awaiting_shift_delete")
            return {"message": "❎ Deletion cancelled because no valid shift indexes were provided."}

       # Convert to zero-based indexes
        indexes = [int(i) - 1 for i in index_strs if i.isdigit()]  

        # ❌ No valid indexes at all
        if not indexes:
            return {"message": "❌ Please provide valid shift number(s) to delete."}

        # ✅ Validate indexes
        if any(i < 0 or i >= len(shifts) for i in indexes):
            return {"message": "❌ Invalid index(es). Please enter valid shift numbers from the list."}

        # ✅ Store for confirmation
        selected_shifts = [shifts[i] for i in indexes]
        await cache.set(sender + "_pending_deletion_confirmation", json.dumps({"shifts": selected_shifts}))

        confirm_lines = ["Hey, just to confirm — you want me to remove these shifts, right?"]
        for idx, shift in enumerate(selected_shifts, start=1):
            status_symbol = "●" if shift['status'].lower() == "filled" else "○"
            confirm_lines.append(
                f"{idx}. {convert_to_md(shift['date'])} - {shift['shift']} - {shift['nurse_type']} - {status_symbol} {shift['status'].capitalize()}"
            )
        confirm_lines.append("\nType 'yes' to delete or 'no' to keep them.")

        return {"message": "\n".join(confirm_lines)}

    except Exception as e:
        print("❌ Error parsing index input:", e)
        return {"message": "❌ Invalid input. Please reply with shift number(s) like '1' or '1,2'."}

async def handle_deletion_confirmation(sender, text, db, cache):
    cleaned = text.strip().lower()

    if await cache.get(sender + "_pending_delete_all_confirmation"):
        if cleaned == "no":
            await cache.delete(sender + "_pending_delete_all_confirmation")
            return {"message": "❎ Cancelled deletion of all shifts."}
        elif cleaned == "yes":
            await cache.delete(sender + "_pending_delete_all_confirmation")
            return await handle_delete_all_shifts(sender, db)
        else:
            return {"message": "Please reply with 'yes' or 'no' to confirm deletion of all shifts."}

    raw = await cache.get(sender + "_pending_deletion_confirmation")
    if not raw:
        return None

    if cleaned == "no":
        await cache.delete(sender + "_pending_deletion_confirmation")
        await cache.delete(sender + "_awaiting_shift_delete")
        await cache.delete(sender + "_pending_delete_all_confirmation")
        return {"message": "❎ Deletion cancelled. All set! Let me know if you need anything else."}

    if cleaned == "yes":
        data = json.loads(raw)
        shifts = data.get("shifts", [])
        success = 0
        failed = 0
        blocked = 0
        blocked_msgs = []

            # Try deleting
        for shift in shifts:
            allowed, reason = await can_delete_shift(shift, sender, db)
            print(allowed, reason, "Shift deletion permission check")
            if not allowed:
                blocked += 1
                blocked_msgs.append(reason)
                continue

            deleted = await delete_shift(shift["id"], sender)
            if deleted:
                success += 1
            else:
                failed += 1

        # Clear existing confirmation and deletion context
        await cache.delete(sender + "_pending_deletion_confirmation")
        await cache.delete(sender + "_awaiting_shift_delete")

        # ✅ Fetch updated shift list and re-initiate loop
        remaining_shifts = await search_shifts_in_db(sender_phone=sender)
        if remaining_shifts:
            await cache.set(sender + "_awaiting_shift_delete", json.dumps({"shifts": remaining_shifts}))

        # Build result message
        parts = []
        if success:
            parts.append(f"✅ Deleted {success} shift(s) successfully.")
        if failed:
            parts.append(f"⚠️ {failed} shift(s) could not be deleted.")
        if blocked:
            parts.append("\n".join(blocked_msgs))  # keep normal join here

        final_message = "\n\n".join(parts)  # this controls section spacing
        
        msg = "\n".join(parts) if parts else "❌ No shifts were deleted."

        # ✅ Ask if they want to delete more (if shifts remain)
        if remaining_shifts:
            lines = [
                msg,
                "",
                "Would you like to delete another shift? Just reply with the shift number (e.g. '1') 👇",
                ""
            ]
            for i, s in enumerate(remaining_shifts, start=1):
                date = convert_to_md(s.get("date")) if s.get("date") else "Unknown date"
                shift = s.get("shift", "Unknown shift")
                nurse_type = s.get("nurse_type", "Unknown nurse type")
                status = s.get("status", "Unknown status").lower()
                # Use symbols for status
                if status == "filled":
                    status_display = "● Filled"
                elif status == "open":
                    status_display = "○ Open"
                else:
                    status_display = status.capitalize()
                lines.append(f"{i}. {date} - {shift} - {nurse_type} - {status_display}")
            return {"message": "\n".join(lines)}
        else:
            return {"message": msg}

    return {"message": "Please reply with 'yes' or 'no' to confirm shift deletion."}



# AI-triggered delete
async def handle_shift_delete_request(reply_message, sender, db, cache):
    delete_req = reply_message["shift_delete_request"]

    if not delete_req.get("date") and not delete_req.get("nurse_type") and not delete_req.get("shift"):
        matching_shifts = await search_shifts_in_db(sender_phone=sender)
    else:
        matching_shifts = await search_shifts_in_db(
            date=delete_req.get("date"),
            nurse_type=delete_req.get("nurse_type"),
            shift=delete_req.get("shift"),
            sender_phone=sender
        )

    if not matching_shifts:
        return {"message": f"No upcoming {delete_req['nurse_type']} {delete_req['shift']} shifts found."}

    if delete_req.get("date") and len(matching_shifts) == 1:
        shift = matching_shifts[0]
        # await cache.set(sender + "_awaiting_shift_delete", json.dumps({
        #     "shifts": matching_shifts,
        #     "single": True
        # }))
        await cache.set(sender + "_pending_deletion_confirmation", json.dumps({"shifts": [shift]}))

        return {
            "message": f"⚠️ Are you sure you want to delete shift ID {shift['id']}: {shift['nurse_type']} {shift['shift']} on {convert_to_md(shift['date'])}? Reply 'yes' to confirm or 'no' to cancel."
        }

    await cache.set(sender + "_awaiting_shift_delete", json.dumps({"shifts": matching_shifts}))
    lines = ["Here are the shifts that match your criteria:"]
    for i, s in enumerate(matching_shifts):
        shift_date = s.get("date")
        display_date = convert_to_md(shift_date) if shift_date else "Unknown"
        lines.append(f"{i}. Date: {display_date}, Shift: {s['shift']}, Nurse Type: {s['nurse_type']}, Status: {s['status']}")
        lines.append("\nPlease reply with the index of the shift you'd like to delete.")
    return {"message": "\n".join(lines)}

# Delete all shifts for coordinator
async def fetch_all_shifts_for_coordinator(sender, db):
    coordinator = await db.fetchrow(
        "SELECT facility_id FROM coordinator WHERE coordinator_phone = $1 OR coordinator_email = $1", sender
    )
    if not coordinator:
        return []
    return await db.fetch("SELECT id FROM shift_tracker WHERE facility_id = $1 AND is_deleted = FALSE", coordinator["facility_id"])

async def handle_delete_all_shifts(sender, db):
    shifts = await fetch_all_shifts_for_coordinator(sender, db)
    if not shifts:
        return {"message": "You don't have any upcoming shifts to delete."}

    deleted_ids = []
    blocked_msgs = []
    for shift in shifts:
        # We need the full shift details, not just ID
        full_shift = await db.fetchrow("SELECT * FROM shift_tracker WHERE id = $1", shift["id"])
        allowed, reason = await can_delete_shift(full_shift, sender, db)
        if not allowed:
            blocked_msgs.append(reason)
            continue

        if await delete_shift(full_shift["id"], created_by=sender):
            deleted_ids.append(full_shift["id"])

      # Build message safely
    msg_parts = []

    if deleted_ids:
        msg_parts.append(f"✅ Deleted {len(deleted_ids)} shift(s) successfully.")

    if blocked_msgs:
        msg_parts.extend(blocked_msgs)

    if not msg_parts:
        msg_parts.append("No shifts could be deleted.")

    return {"message": "\n".join(msg_parts), "deleted_shift_ids": deleted_ids}
