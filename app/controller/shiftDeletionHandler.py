import asyncio
import json
from app.controller.shiftController import search_shifts_in_db
from app.utils.convert_mm_dd_yyyy_to_mm_dd import convert_to_md
from app.database import db
from app.utils.normalizeDate import normalize_date
from app.utils.send_message import send_message
import re


VAGUE = {"hi", "hello", "hey", "ok", "okay", "yes", "no"}
DELETE_KEYWORDS = {"delete", "delte", "remove", "cancel", "i want to delete"}

# Delete shift by ID
async def delete_shift(shift_id, created_by, nurse_id=None, nurse_type=None, shift_value=None, location=None, date=None, name=None):
    try:
        result = await db.execute("UPDATE shift_tracker SET is_deleted = TRUE WHERE id = $1", shift_id)
        if result == "UPDATE 0":
            return False

        if nurse_id:
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

    # Case: vague input
    if cleaned in VAGUE:
        await cache.delete(sender + "_awaiting_shift_delete")
        return {
            "message": "❎ Deletion cancelled."
        }

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

        # ❌ No valid indexes at all
        if not indexes:
            return {"message": "❌ Please provide valid shift number(s) to delete."}

        # ✅ Validate indexes
        if any(i < 0 or i >= len(shifts) for i in indexes):
            return {"message": "❌ Invalid index(es). Please enter valid shift numbers from the list."}

        # ✅ Store for confirmation
        selected_shifts = [shifts[i] for i in indexes]
        await cache.set(sender + "_pending_deletion_confirmation", json.dumps({"shifts": selected_shifts}))

        confirm_lines = ["⚠️ Are you sure you want to delete the following shifts:"]
        for shift in selected_shifts:
            confirm_lines.append(
                f"- Date: {convert_to_md(shift['date'])}, Shift: {shift['shift']}, Nurse Type: {shift['nurse_type']}, Status: {shift['status']}"
            )
        confirm_lines.append("Reply 'yes' to confirm or 'no' to cancel.")

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
        return {"message": "❎ Deletion cancelled."}

    if cleaned == "yes":
        data = json.loads(raw)
        shifts = data.get("shifts", [])
        success = 0
        failed = 0

        for shift in shifts:
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

        # Build response
        if success and not failed:
            msg = f"✅ Deleted {success} shift(s) successfully."
        elif success and failed:
            msg = f"⚠️ Deleted {success} shift(s), but {failed} could not be deleted."
        else:
            msg = "❌ Failed to delete the selected shifts."

        # ✅ Ask if they want to delete more (if shifts remain)
        if remaining_shifts:
            lines = [msg, "\nWould you like to delete another shift? Reply with the shift number (e.g. '1')."]
            for i, s in enumerate(remaining_shifts):
                lines.append(f"{i}. Date: {convert_to_md(s['date'])}, Shift: {s['shift']}, Nurse Type: {s['nurse_type']}, Status: {s['status']}")
            return {"message": "\n".join(lines)}
        else:
            return {"message": msg}

    return {"message": "Please reply with 'yes' or 'no' to confirm shift deletion."}



# AI-triggered delete
async def handle_shift_delete_request(reply_message, sender, db, cache):
    delete_req = reply_message["shift_delete_request"]

    matching_shifts = await search_shifts_in_db(
        date=delete_req.get("date"),
        nurse_type=delete_req["nurse_type"],
        shift=delete_req["shift"],
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
        lines.append(f"{i}. Date: {convert_to_md(s['date'])}, Shift: {s['shift']}, Nurse Type: {s['nurse_type']}, Status: {s['status']}")
    lines.append("\nPlease reply with the index of the shift you'd like to delete.")
    return {"message": "\n".join(lines)}

# Delete all shifts for coordinator
async def fetch_all_shifts_for_coordinator(sender, db):
    coordinator = await db.fetchrow(
        "SELECT facility_id FROM coordinator WHERE coordinator_phone = $1 OR coordinator_email = $1", sender
    )
    if not coordinator:
        return []
    return await db.fetch("SELECT id FROM shift_tracker WHERE facility_id = $1", coordinator["facility_id"])

async def handle_delete_all_shifts(sender, db):
    shifts = await fetch_all_shifts_for_coordinator(sender, db)
    if not shifts:
        return {"message": "You don't have any upcoming shifts to delete."}

    deleted_ids = []
    for shift in shifts:
        if await delete_shift(shift["id"], created_by=sender):
            deleted_ids.append(shift["id"])

    return {
        "message": f"✅ Deleted {len(deleted_ids)} shift(s) successfully.",
        "deleted_shift_ids": deleted_ids
    }
