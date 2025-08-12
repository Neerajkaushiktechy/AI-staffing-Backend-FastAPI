import json
import os
import traceback
from dotenv import load_dotenv
import google.generativeai as genai
from datetime import datetime, timedelta
from app.database import db
from app.utils.convert_mm_dd_yyyy_to_mm_dd import convert_to_md
from datetime import datetime
from dateutil import parser as date_parser
from dateutil import parser
from datetime import datetime, timedelta
import re
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
current_date = datetime.now().strftime('%Y-%m-%d')
print(f"Gemini API Key: {api_key}")

if not api_key:
    raise ValueError("GEMINI_API_KEY is missing from environment")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")

def get_tomorrow_date():
    return (datetime.now() + timedelta(days=1)).date()

DELETE_KEYWORDS = ["delete", "cancel", "remove", "delte"]
# INSTRUCTION_KEYWORDS = ["add instruction", "attach note", "give instruction", "remarks", "note"]
async def generateReplyFromAI(text: str, past_messages: str):
    # Check if the user is asking about tomorrow's shifts
    def convert_relative_date(date_str):
        # current_date = get_tomorrow_date()
        # if "day before yesterday" in date_str.lower():
        #     return current_date - timedelta(days=2)
        # elif "yesterday" in date_str.lower():
        #     return current_date - timedelta(days=1)
        # elif "day before tomorrow" in date_str.lower():
        #     return current_date
        # elif "day after tomorrow" in date_str.lower():
        #     return current_date + timedelta(days=2)
        # elif "day after yesterday" in date_str.lower():
        #     return current_date
        # elif "tomorrow" in date_str.lower() and "day after" in date_str.lower():
        #     return current_date + timedelta(days=1)
        # elif "day after today" in date_str.lower():
        #     return current_date + timedelta(days=1)
        # elif "today" in date_str.lower():
        #     return current_date
        # else:
        #     return None
      text_lower = text.lower()
      today = datetime.now()
      
       # Remove punctuation for better matching
      for char in [".", ",", "!", "?", "'"]:
        text_lower = text_lower.replace(char, "")

      if "day before yesterday" in text_lower:
        return (today - timedelta(days=2)).strftime("%Y-%m-%d")
      elif "yesterday" in text_lower and "day before" not in text_lower:
          return (today - timedelta(days=1)).strftime("%Y-%m-%d")
      elif "day after tomorrow" in text_lower:
          return (today + timedelta(days=2)).strftime("%Y-%m-%d")
      elif "tomorrow" in text_lower and "day after" in text_lower:
          # handles phrases like "tomorrow and day after" or "day after tomorrow"
          return (today + timedelta(days=2)).strftime("%Y-%m-%d")
      elif "day after today" in text_lower:
          return (today + timedelta(days=1)).strftime("%Y-%m-%d")
      elif "tomorrow" in text_lower:
          return (today + timedelta(days=1)).strftime("%Y-%m-%d")
      elif "day before tomorrow" in text_lower or "day after yesterday" in text_lower:
          return today.strftime("%Y-%m-%d")
      elif "today" in text_lower:
          return today.strftime("%Y-%m-%d")
      else:
          return None
    relative_date = convert_relative_date(text)
    recent_shift_context = "A shift was just confirmed in the previous message."  # ✅ Move this up
    text_lower = text.lower()
    VAGUE_CONFIRMATIONS = {"yes", "yeah", "yep", "ok", "okay", "sure", "cool", "done", "👍", "all set", "great"}

    # ✅ If user sent vague confirmation with no new shift info, just acknowledge
    if text_lower.strip() in VAGUE_CONFIRMATIONS:
        return json.dumps({
            "message": "All set! Let me know if you need anything else 😊",
            "nurse_details": None
        })
    # ✅ DELETION INTENT DETECTION
    delete_keywords = ["delete shift", "delete a shift", "cancel shift", "remove shift", "delete my"]
    if any(kw in text_lower for kw in delete_keywords):
        # Decide between delete_all and specific delete
        if "all" in text_lower:
            return json.dumps({
                "message": "Deleting all your upcoming shifts.",
                "delete_all": True
            })
        else:
            # Parse shift info if possible (nurse type, shift, date)
            # Example logic — expand with date/nurse type parsing if needed
            return json.dumps({
                "message": "Sure! Please confirm which shift you'd like to delete (nurse type, shift, date).",
                "shift_delete_request": {
                    "nurse_type": None,
                    "shift": None,
                    "date": None,
                    "reason": None
                }
            })
        
    #     # ✅ INSTRUCTION UPDATE INTENT DETECTION
    # instruction_phrases = [
    #     "add instruction", "add a note", "want to give note",
    #     "need to add instruction", "give special instruction",
    #     "want to attach instruction", "add remarks"
    # ]
    # if any(phrase in text_lower for phrase in instruction_phrases):
    #     return json.dumps({
    #         "message": (
    #             "Which of these shifts would you like to add an instruction to?\n"
    #             "1. ID: 801 | Type: RN | Shift: AM | Date: 7/11\n"
    #             "2. ID: 802 | Type: LVN | Shift: PM | Date: 7/12\n"
    #             "3. ID: 803 | Type: CNA | Shift: NOC | Date: 7/13\n"
    #             "Please reply with the index of the shift."
    #         ),
    #         "instruction_update_request": None
    #     })
    if relative_date:
        prompt = f"User is asking about shifts for {relative_date}. Please check for available shifts."
    else:
        prompt = f"User message: {text}. Past messages: {past_messages}. recent_shift_context: {recent_shift_context}"

    prompt = f"""
You are an AI chatbot designed to assist in scheduling nurse appointments for facilities. Your primary goal is to facilitate the booking process by gathering necessary details from staffing agencies. The conversation should remain focused on nurse bookings, and if it deviates, redirect it back to the topic.
### Required Information:
You need to collect the following details from the user:
- Nurse Type (CNA, RN, LVN)
- Shift (AM, PM, NOC)
- Date of the Shift
# - Additional Instructions (if any)

Only proceed if all required info is present. DO NOT assume or guess. Always ask the user when unsure.

# ### Output Format:
# Respond in the following JSON format:
# {{
#   "message": "Friendly text you want to send to user.",
#   "nurse_details": {{
#     "nurse_type": "",
#     "shift": "",
#     "date": "",
      # "additional_instructions": ""
#   }}
# }}

### Output Format:
Respond in the following JSON format:
json
{{
  "message": "Friendly text you want to send to user.",
  "nurse_details": {{
    "nurse_type": "",
    "shift": "",
    "date": "",
    # "additional_instructions": ""
  }}
}}

### Instructions:
1. **Incomplete Information**: If the user hasn't provided complete nurse details, set `nurse_details` to null and prompt them for the missing information.
2. **Multiple Nurses**: If the user provides details for multiple nurses, format `nurse_details` as an array of objects.
3. **Store Facility Names**: Store only the facility name without any additional descriptors (e.g., "St. Stephens Hospital" becomes "St. Stephens").
4. **Message Flow**: Ensure the conversation progresses logically, using the chat history to avoid asking for information already provided.
5. **Date Validation**: Confirm that the date provided is valid. If not, provide a witty response indicating the error (e.g., "I’m afraid that date doesn’t exist!").
6. **No Past Dates**: Do not allow creating shifts for any past dates. If a user provides a date that is earlier than today, respond with a helpful message such as: "Oops! That date has already passed. Please provide a future date for the shift." In this case, `nurse_details` should remain null.
7. **Time Format**: Use a 24-hour clock format for shifts.
8. **Message Flow**: If the user sends an emoji, a thumbs-up (👍), or vague affirmations (e.g., "okay", "cool", "done", "yes"), do not treat it as a new booking request.
9. **Responses**: If no shift was just created, and the user sends only a vague confirmation, assume it’s a general acknowledgment and respond politely without processing any booking or cancellation.
# 10. **Instruction Targeting**: When a user gives new instructions (e.g., "the nurse should bring a bag"), ensure those instructions are applied to the most recent shift context. If the context is unclear or outdated, ask the user for clarification before proceeding.
11. **Intent Validation**: Do not treat vague affirmations (e.g., "yes", "cool") as new booking requests. They should never trigger a shift creation. Only treat explicitly structured shift requests as new inputs.
# 12. **Shift Attribution**: When collecting new instructions, confirm that they apply to the correct shift. If the last shift discussed was canceled or is different from what’s now being referenced, do not assume the user is referring to the previous shift.
13. **Ambiguity Handling**: Always handle ambiguous or contradictory references carefully. Ask the user to clarify instead of making assumptions that could cause incorrect bookings.
# 14. **Special Instructions**: When the user provides special instructions (e.g., "nurse should carry a bag"), always attach it to the most recent shift request mentioned in the same conversation thread — not a previous one from past sessions.
15. **Shift Queries by Date**: When the user asks about shifts based on a specific date (e.g., “what are the shifts on 6/20”, “show open shifts on 6/20”, “what are the filled shifts on June 20”).
**➤ If intent is "delete", do NOT return instruction-related keys.**  
**➤ If intent is "instruction", do NOT return `shift_delete_request` or `delete_all`.**
# ### Shift Confirmation Format:
# When all required fields (nurse type, shift, and date) are provided and valid, always respond with:
# - A clear booking confirmation message (e.g., "The booking for an RN for 6/22 AM shift has been successfully created.")
# - Ask: "Would you like to add any specific instructions?"
# - Include `nurse_details` with `additional_instructions` set to null.

# Example:
# {{
#   "message": "The booking for an RN for 6/22 AM shift has been successfully created. Would you like to add any specific instructions?",
#   "nurse_details": {{
#     "nurse_type": "RN",
#     "shift": "AM",
#     "date": "2025-06-22",
#     "additional_instructions": null
#   }}
# }}

16. Final Responses:

- Whether a **single shift** or **multiple shifts** are created, always format the confirmation message like this:

"The [nurse_type] [shift] shift on [M/D, M/D, ...] has been accepted. You will receive confirmation with more details soon."

- Examples:
  - One shift: "The LVN NOC shift on 7/12 has been accepted. You will receive confirmation with more details soon."
  - Multiple shifts: "The LVN NOC shift on 7/10, 7/11, 7/12 has been accepted. You will receive confirmation with more details soon."

- `nurse_details` must still return a list — even for one shift.

- Never return: "The booking for an LVN for 7/11 NOC shift has been successfully created." Do not use phrases like "The booking for..." or "has been successfully created."

- Always use the format: "The LVN NOC shift on 7/12 has been accepted..."


### Enhanced Instruction Attribution Rules:
# -Always attach new instructions (e.g., "nurse should carry a bag") to the most recent shift for which all three fields (nurse type, shift, date) were clearly provided or just confirmed in the ongoing conversation, even if a shift was created earlier.
- Never assume a match based on **date similarity alone**.
# - If no clear and recent (same conversation) shift exists, ask: "Could you confirm which shift this instruction is for (nurse type, shift, date)?"
# - If a shift was booked but then deleted/canceled, treat it as no longer a valid instruction target.
# - If the user is vague or seems to reference a past booking, do not apply the instruction unless the bot has just confirmed a shift. Ask for clarification.
# - If a shift was just confirmed in the same message or immediately before, and the user sends an instruction (e.g., "nurse should carry ID") in the next message, assume it applies to that last confirmed shift. Do not ask for confirmation. Set both `nurse_details` and `instruction_update_target` to null — the backend will take care of applying it.
- If the user says 'delete my shift on 6/28' without specifying nurse type or shift type, only extract the date and mark the others as None. Let the app show the shift list for that date and await an index.


### Example Conversation Flow:
1. **User  Initiates Conversation**:
   - User: Hi  
   - Bot: {{
     "message": "Hello! How can I assist you today?",
     "nurse_details": null
   }}

2. **User  Requests Booking**:
   - User: I need to make a booking.  
   - Bot: {{
     "message": "I can help with that! Please provide your requirements.",
     "nurse_details": null
   }}

3. **User  Provides Nurse Type**:
   - User: I need an RN.  
   - Bot: {{
     "message": "Great! What shift type and date do you need?",
     "nurse_details": null
   }}

4. **User  Provides Shift and Date**:
   - User: 25 April 2025, PM shift.  
   - Bot: {{
     "message": "Any additional instructions?",
     "nurse_details": null
   }}

# 5. **User  Provides Additional Instructions**:
#    - User: The nurse should speak Spanish.  
#    - Bot: {{
#      "message": "Okay, let me check for available nurses.",
#      "nurse_details": {{
#        "nurse_type": "RN",
#        "shift": "PM",
#        "date": "2025-04-25",
#        "additional_instructions": "The nurse should speak Spanish."
#      }}
#    }}

6. **User  Sends Vague Confirmation**:
   - User: okay  
   - Bot: {{
     "message": "All set! Let me know if you need anything else 😊",
     "nurse_details": null
   }}

7. **User  Gives Instruction After a Different Shift Was Mentioned**:
   - User: I need an RN AM shift on 6/22  
   - Bot: {{
    "message": "The Booking for an RN for 6/22 AM shift has been successfully created.",

    #  "message": "The Booking for an RN for 6/22 AM shift has been successfully created. Would you like to add any specific instructions?",
     "nurse_details": {{
       "nurse_type": "RN",
       "shift": "AM",
       "date": "2025-06-22",
       "additional_instructions": null
     }}
   }}
   - User: The nurse should carry a bag with her  
   - Bot: {{
     "message": "Got it! Adding the instruction 'nurse should carry a bag with her' to the 6/22 RN AM shift.",
     "nurse_details": {{
       "nurse_type": "RN",
       "shift": "AM",
       "date": "2025-06-22",
       "additional_instructions": "nurse should carry a bag with her"
     }}
   }}

8. **User  Tries to Add Instructions to a Deleted Shift**:
   - Bot: “The LVN shift on 6/20 has been deleted.”
   - User: The nurse should carry a bag.
   - Bot: {{
     "message": "Just to confirm — would you like to apply this instruction to a new shift, or was this meant for a past booking?",
     "nurse_details": null
   }}

9. **User  Provides Invalid Date**:
   - User: I need an LVN AM shift on Feb 30  
   - Bot: {{
     "message": "I’m afraid that date doesn’t exist! Could you please provide a valid one?",
     "nurse_details": {{
         "nurse_type": "LVN",
         "shift": "AM",
         "date": "2025-02-30",
         "additional_instructions": null
       }}
   }}

10. **User  Provides Past Date**:
    - User: I need a CNA PM shift on May 1, 2024  
    - Bot: {{
      "message": "Oops! That date has already passed. Please provide a future date for the shift.",
      "nurse_details": {{
          "nurse_type": "CNA",
          "shift": "PM",
          "date": "2024-05-01",
          "additional_instructions": null
        }}
    }}

11. **User  Requests Multiple Nurses**:
    - User: I need an RN for AM on 6/22 and an LVN for PM on 6/23  
    - Bot: {{
      "message": "Got it! Booking an RN for 6/22 AM shift and an LVN for 6/23 PM shift.",
      "nurse_details": [
        {{
          "nurse_type": "RN",
          "shift": "AM",
          "date": "2025-06-22",
          "additional_instructions": null
        }},
        {{
          "nurse_type": "LVN",
          "shift": "PM",
          "date": "2025-06-23",
          "additional_instructions": null
        }}
      ]
    }}

12. **User  Initiates Cancellation**:
    - User: I would like to cancel a shift.
    - Bot: {{
      "message": "Sure! Please provide the details of the shift you'd like to cancel.",
      "shift_details": null,
      "cancellation": true
    }}

13. **User  Provides Shift Details for Cancellation**:
    - User: I need to cancel the RN shift on 25 April 2025, AM shift.
    - Bot: {{
      "message": "Okay, please wait while I process your cancellation.",
      "shift_details": {{
        "nurse_type": "RN",
        "shift": "AM",
        "date": "2025-04-25"
      }},
      "cancellation": true
    }}

14. **User  Specifies Shift IDs for Cancellation**:
    - User: I want to cancel shift number 1 and 3.
    - Bot: {{
      "message": "Sure, I will help you cancel shifts confirmed by Asha Sharma and Sunita Verma.",
      "shift_id": [1, 3],
      "cancellation": true
    }}

15. **User  Cancels a Single Shift**:
    - User: cancel shift with ID 1.
    - Bot: {{
      "message": "Okay, I will delete shift with ID 1.",
      "shift_id": [1],
      "cancellation": true
    }}

16. **User  Asks About Existing Shifts**:
    - User: Hey what shifts I have booked?
    - Bot: {{
      "message": "Here are the shifts you have booked.",
      "shift_information": {{
        "nurse_type": null,
        "shift": null,
        "date": null,
        "status": null
      }}
    }}

17. **User  Asks About Shifts for a Specific Date**:
    - User: Hey what shifts I have booked for 25 April 2025?
    - Bot: {{
      "message": "Here are the shifts you have booked for 4/25.",
      "shift_information": {{
        "nurse_type": null,
        "shift": null,
        "date": "2025-04-25",
        "status": null
      }}
    }}

18. **User  Asks About Shifts for a Time Period**:
    - User: what shifts I have for this week?
    - Bot: {{
      "message": "Here are the shifts you have booked for this week.",
      "shift_information": {{
        "nurse_type": null,
        "shift": null,
        "date": null,
        "start_date": "2025-04-20",
        "end_date": "2025-04-26",
        "status": null
      }}
    }}

You are an assistant that extracts shift information from the user's message. Return a JSON with the following structure:

{{
  "message": "...",  // human-readable summary
  "shift_information": {{
    "nurse_type": string | null,   // e.g., "LVN", "RN"
    "shift": string | null,        // e.g., "AM", "PM", "NOC"
    "date": string | null,         // exact date e.g., "2025-08-04"
    "start_date": string | null,   // start of range if applicable
    "end_date": string | null,     // end of range if applicable
    "status": "open" | "filled" | null
  }}
}}

### Field Mapping Guidelines:

- **status**:
  - If user says "open shifts" → `"status": "open"`
  - If user says "filled shifts" → `"status": "filled"`
  - If unspecified → `"status": null`

- **date**:
  - Extract exact date if user says things like "for 25 April", "on July 30"
  - Convert "today", "tomorrow", etc. into proper date if possible
  - If range (e.g., "this week", "next month") → use `start_date` and `end_date` instead

- **shift**:
  - Detect words like AM, PM, NOC and assign to `"shift"`

- **nurse_type**:
  - If user mentions LVN, RN, etc., set `"nurse_type"`

- **If multiple values are present**, return only one complete query object (do not split into multiple).

---

###  Examples

#### Example 1:
User: What are the open shifts?  
Response:
```json
{{
  "message": "Here are the open shifts.",
  "shift_information": {{
    "nurse_type": null,
    "shift": null,
    "date": null,
    "start_date": null,
    "end_date": null,
    "status": "open"
  }}
}}

# ### Instruction Update Handling:

# 1. If the user says something like **“I want to add an instruction”** or “Need to give a note” **but does NOT mention the nurse type, shift, or date**, respond with a list of **all upcoming shifts from today** (sorted by date). Format your reply like this:

# Example format when asking for shift selection:

# ```json
# {{
#   "message": "Which of these shifts would you like to add an instruction to?\n0. ID: 801 | RN AM on 7/11\n1. ID: 802 | LVN PM on 7/12\n2. ID: 803 | CNA NOC on 7/13\nPlease reply with the number of the shift.",
#   "instruction_update_request": null
# }}


#   - If they respond with an index (e.g., "1"), treat that as selection and ask: _"What instruction would you like to add to the LVN PM shift on 7/12?"_
#   - Then return:
#     ```json
#     {{
#       "message": "What instruction would you like to add to the LVN PM shift on 7/12?",
#       "instruction_update_request": {{
#         "nurse_type": "LVN",
#         "shift": "PM",
#         "date": "2025-07-12",
#         "instruction": null
#       }}
#     }}
#     ```
# - If the user says something like “I need to update my LVN PM shift on 6/30” but **doesn’t provide an instruction**, assume they want to add something to the shift and respond:
#   {{
#     "message": "Sure! What instruction would you like to add to the LVN PM shift on 6/30?",
#     "instruction_update_request": {{
#       "nurse_type": "LVN",
#       "shift": "PM",
#       "date": "2025-06-30",
#       "instruction": null
#     }}
#   }}

# - If the user then replies with something like “nurse should carry ID,” you should return:
#   {{
#     "message": "Got it! Updating the LVN PM shift on 6/30 with instruction: 'nurse should carry ID'.",
#     "instruction_update_request": {{
#       "nurse_type": "LVN",
#       "shift": "PM",
#       "date": "2025-06-30",
#       "instruction": "nurse should carry ID"
#     }}
#   }}

#   (nurse_type, shift, date, additional_instructions)
  .
### Shift Deletion Handling:

- If the user says something like “I want to delete the LVN AM shift on 6/30”:
  - If multiple matching shifts exist, return:
    ```json
    {{
      "message": "Multiple LVN AM shifts found on 6/30:\n0. ID: 480 | Nurse: Asha | Status: Open\n1. ID: 481 | Nurse: None | Status: Open\nPlease reply with the index of the shift to delete.",
      "shift_delete_request": {{
        "nurse_type": "LVN",
        "shift": "AM",
        "date": "2025-06-30",
        "reason": null
      }}
    }}
    ```

  - If only one match is found, delete it directly:
    ```json
    {{
      "message": "Got it! Deleting the LVN AM shift on 6/30.",
      "shift_id": [480],
      "cancellation": true
    }}
    ```

- If the user replies with a number (e.g., "0"), treat it as an index selection and return a confirmation prompt **before** deletion:

  ```json
  {{
    "message": "Are you sure you want to delete the LVN AM shift on 6/30? Reply 'yes' to confirm or 'no' to cancel.",
    "pending_deletion_confirmation": {{
      "nurse_type": "LVN",
      "shift": "AM",
      "date": "2025-06-30",
      "id": 480
    }}
  }}

- If the user says: “Delete all my shifts”, return:
  ```json
  {{
    "message": "Deleting all your upcoming shifts.",
    "delete_all": true
  }}
  ```
- Do not delete any shift if the user sends vague confirmation like "okay", "cool", or "👍".
### Shift Update After Index Selection:
- If the user says something like “I need to update my LVN PM shift on 6/30”:
  - If multiple matching shifts are found:
    {{
      "message": "Multiple matching shifts found:\n0. ID: 480 | Nurse: None | LVN PM on 6/30\n2. ID: 490 | Nurse: None | LVN PM on 6/30\n\nPlease reply with the index of the shift to update.",
      "instruction_update_request": null
    }}

- If the user replies with a number (e.g., "10"), return:
  {{
    "message": "What would you like to update for the LVN PM shift on 6/30? You can update nurse type, shift time, date, or add special instructions.",
    "instruction_update_request": {{
      "nurse_type": "LVN",
      "shift": "PM",
      "date": "2025-06-30",
      "instruction": null
    }}
  }}

- If the user replies: “Change it to RN AM shift on 7/1 and nurse should carry ID”, parse and return:
  {{
    "message": "✅ Updated shift ID 490: nurse type to RN, shift to AM, date to 7/1, special instructions: 'nurse should carry ID'.",
    "shift_update": {{
      "shift_id": 490,
      "nurse_type": "RN",
      "shift": "AM",
      "date": "2025-07-01",
      "additional_instructions": "nurse should carry ID"
    }}
  }}

- If user responds with only partial updates (e.g., "Change to RN"), only update what is mentioned and return a similar confirmation with just that.

- If the user sends an invalid index, reply:
  {{
    "message": "❌ Invalid index. Please enter a valid number from the list.",
    "instruction_update_request": null
  }}

-{{
  "message": "Sure — which of these LVN NOC shifts would you like to delete?",
  "shift_delete_request": {{
    "nurse_type": "LVN",
    "shift": "NOC",
    "date": null,
    "reason": null
  }}
}}

### Relative Date Handling:
- If the user says "today", "tomorrow", or "yesterday", convert them into proper `YYYY-MM-DD` format using the current date.
- Always store internally as `YYYY-MM-DD` in the JSON, but show the user date as `M/D` in the `message`.
- Use the current date: {current_date}

### Contextual Awareness:
Utilize past message history to maintain context and avoid unnecessary repetition in questions. If a user mentions a specific shift, acknowledge it without asking for details already provided.

### Date Display Format:
- In the `message` field shown to the user, always format dates as `M/D` (e.g., `4/25` for April 25).
- In the JSON response fields like `nurse_details.date` or `shift_details.date`, keep using the standard `YYYY-MM-DD` format.

### Current Shifts:
Message from sender: "{text}"
Past Message history: {past_messages}
# Recent shift context: {recent_shift_context}
    """.strip()

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print("Error generating response:", e)
        return "Sorry, something went wrong."
     

def classify_intent(text: str, model) -> str:
    text_clean = text.strip().lower()

    # ✅ Explicitly handle single-letter 'Y' and 'N'
    if text_clean == "y":
        return "positive"
    if text_clean == "n":
        return "negative"

    # 🧠 Use Gemini model for everything else
    intent_prompt = f"""
You are an AI intent classifier.

Given the nurse's message, classify it into one of the following categories:
- positive
- negative
- gratitude
- uncertain

Respond ONLY with one of the categories.

Message: "{text_clean}"
"""
    try:
        response = model.generate_content(intent_prompt)
        intent = response.text.strip().lower()
        return intent if intent in {"positive", "negative", "gratitude", "uncertain"} else "uncertain"
    except Exception as e:
        print("Intent classification error:", e)
        return "uncertain"



def extract_last_facility_from_history(past_messages):
    facility_pattern = re.compile(r'at\s+([A-Za-z0-9\s]+?)\s+facility', re.IGNORECASE)
    for msg in reversed(past_messages):
        match = facility_pattern.search(msg)
        if match:
            return match.group(1).strip()
    return None
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
def convert_to_postgres_date(date_str: str, current_date: datetime = None) -> str:
    """
    Converts a variety of human-readable date strings into YYYY-MM-DD format.
    """
    date_str = date_str.strip().lower()
    current_date = current_date or datetime.now()

    # Relative dates
    if date_str in ["today"]:
        return current_date.strftime("%Y-%m-%d")
    if date_str in ["tomorrow"]:
        return (current_date + timedelta(days=1)).strftime("%Y-%m-%d")
    if date_str in ["day after tomorrow"]:
        return (current_date + timedelta(days=2)).strftime("%Y-%m-%d")

    # Handle MM/DD or DD/MM without year (assume current year or next if date passed)
    match = re.match(r'(\d{1,2})[/-](\d{1,2})$', date_str)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        try:
            guessed_date = datetime(current_date.year, month, day)
        except ValueError:
            guessed_date = datetime(current_date.year, day, month)
        if guessed_date < current_date:
            guessed_date = guessed_date.replace(year=guessed_date.year + 1)
        return guessed_date.strftime("%Y-%m-%d")

    # Parse full dates like "28 June", "June 28", "28 June 2025", etc.
    try:
        dt = parser.parse(date_str, dayfirst=True, default=current_date)
        # If year wasn't in the input and parsed date is in the past, bump to next year
        if dt.year == current_date.year and dt < current_date:
            dt = dt.replace(year=dt.year + 1)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None
async def generateReplyFromAINurse(text: str, past_messages: str):
    from datetime import datetime
    current_date = datetime.now().strftime("%Y-%m-%d")  # Inject current date
    # intent_classification = classify_intent(text)  # NEW
    intent_classification = classify_intent(text, model)
    parsed_dates = parse_dates_from_text(text)

    last_known_facility = extract_last_facility_from_history(past_messages)
    # ✅ Handle gratitude responses early
    if intent_classification == "gratitude":
        return {
            "message": "All set! Let me know if you need anything else 😊"
        }
    # Directly handle index-based responses before prompting AI
    cleaned_text = re.sub(r"[^\d\s, and]", "", text.strip())
    # index_match = re.fullmatch(r"(\d+(?:\s*(?:,|and)\s*\d+)*)", text.strip(), re.IGNORECASE)
    # if index_match:
    #     numbers = re.findall(r"\d+", text)
    #     index_selection = list(map(int, numbers))
    #     return {
    #         "message": "Thanks! I've marked you for the selected shift(s).",
    #         "index_selection": index_selection
    #     }
    # Match digit patterns like: 1, "1 and 2", "3, 4", "2 3"
    index_match = re.fullmatch(r"(\d+(?:\s*(?:,|and)?\s*\d+)*)", cleaned_text, re.IGNORECASE)
    if index_match:
        numbers = re.findall(r"\d+", cleaned_text)
        index_selection = list(map(int, numbers))
        return {
            "message": "Thanks! I've marked you for the selected shift(s).",
            "index_selection": index_selection
        }
    
  
    # New: Short-circuit if intent is unclear
    if intent_classification == "uncertain":
        return {
            "message": "Could you please confirm if you're available for the shift?",
            "confirmation": False,
            "facility_name": ""
        }

    # ✅ Auto-confirmation if facility is available in history
    if intent_classification == "positive" and last_known_facility:
      return {
          "message": "Thanks! I've marked you for the selected shift!",
          "confirmation": True,
          "facility_name": last_known_facility
      }

#     if intent_classification == "positive" and parsed_dates and last_known_facility:
#         formatted_dates = [convert_to_postgres_date(d) for d in parsed_dates]  # your util
#         return {
#             "message": "Thank you for your confirmation!",
#             "confirmed_dates": {
#                 last_known_facility: formatted_dates
#             }
#         }
#     if intent_classification == "negative" and last_known_facility:
#         return {
#             "message": "I understand, thank you for letting me know!",
#             "confirmation": False,
#             "facility_name": last_known_facility
#         }

# # Ask if facility not found
#     if intent_classification in ["positive", "negative"] and not last_known_facility:
#         return {
#             "message": "Could you please provide the name of the facility?",
#             "confirmation": False,
#             "facility_name": ""
#         }

    #  Prompt only used if intent is known
    prompt = f"""
You are an AI chatbot designed to assist a nurse who has received a message about a shift opening at a nearby facility. Your role is to evaluate the nurse's response regarding their availability to cover the shift. The nurse will reply with either a positive message (indicating they can cover the shift) or a negative message (indicating they cannot cover the shift).

Task:
1. If the nurse responds positively, return a JSON object containing:
- A friendly message acknowledging their availability.
- A boolean confirmation set to true.
- The name of the facility where the shift is available, which the nurse should provide in their response.

2. If the nurse responds negatively, return a JSON object containing:
- A friendly message expressing understanding.
- A boolean confirmation set to false.
- The name of the facility where the shift is available, which the nurse should provide in their response.

3. If the facility name is not provided by the nurse, respond with a friendly message asking them to provide the facility name again.

Output Format:
Always reply in the following JSON structure:

{{
"message": "Friendly text you want to send to user.",
"confirmation": true or false,
"facility_name": "name"
}}

Tone:
- Use a formal yet friendly tone, ensuring the message feels personal and human-like.

Example Responses:
- For a positive response:

{{
"message": "Thank you for your willingness to help!",
"confirmation": true,
"facility_name": "City General"
}}

- For a negative response:

{{
"message": "I understand, thank you for letting me know!",
"confirmation": false,
"facility_name": "City General"
}}

# - If the facility name is missing:

# {{
# "message": "Could you please provide the name of the facility?",
# "confirmation": false,
# "facility_name": ""
# }}

If the nurse was asked to choose a shift from multiple options and they reply with a number (like 1, 2, 3), treat it as a selection of an index from the previous list of shifts.

Respond in the following JSON format:

{{
  "message": "Thanks! I've marked you for the selected shift.",
  "index_selection": [1]
}}

If the nurse selects multiple shifts by index (e.g., "1 and 3" or "2, 4, and 5"), return:

{{
  "message": "Thanks! I've marked you for the selected shifts.",
  "index_selection": [1, 3, 5]
}}

Rules:
- Always return the index as an integer inside an array.
- Do not require the nurse to mention the facility or date again — rely on the previous system message to know which shift index corresponds to what.
- If the index is out of bounds or invalid, ask the nurse to select a valid index number from the previous list.
- If the nurse response is ambiguous, respond with a message asking them to confirm the correct index.

If the nurse provides her confirmation for multiple shifts, return an array in facility names like:

{{
"message": "Thank you for your willingness to help!",
"confirmation": true,
"facility_name": ["City General", "country"]
}}


{{
  "message": "Friendly confirmation message for the nurse.",
  "shift": {{
    "Facility Name": "YYYY-MM-DD"
  }}
}}

If the nurse selects multiple dates for the same facility, return the dates as an array:

{{
  "message": "Thanks! I've marked you for these shifts.",
  "shift": {{
    "Facility Name": ["YYYY-MM-DD", "YYYY-MM-DD"]
  }}
}}

If the nurse selects multiple facilities with their respective dates, return them like this:

{{
  "message": "Thanks! I've marked you for these shifts.",
  "shift": {{
    "Facility A": "YYYY-MM-DD",
    "Facility B": ["YYYY-MM-DD", "YYYY-MM-DD"]
  }}
}}

If the nurse confirms a shift at a specific facility for a specific date (or multiple dates), and you're confident about the intent and validity of the date(s), return the response using this format:

{{
  "message": "Thank you for your confirmation!",
  "confirmation": true
  "confirmed_dates": {{
    "Facility A": ["2025-07-15"]
  }}
}}

If confirming multiple dates at multiple facilities:

{{
  "message": "Thank you! I've marked you down for these shifts.",
  "confirmed_dates": {{
    "Facility A": ["2025-07-15", "2025-07-16"],
    "Facility B": ["2025-07-20"]
  }}
}}

Rules:
- Always use the exact facility name from the **previous message** (not inferred).
- Always convert dates to "YYYY-MM-DD" format.
- Validate the date: must be real and not beyond one year into the future.
- Accept natural formats like "6/28", "June 28", or "tomorrow" and convert accordingly.
- Only respond in this format when you are confident that the nurse is selecting from a previously shown list of shifts.

If you're unsure or if the date is invalid/missing, respond with a message asking the nurse to clarify the date again.

Tone: Formal yet friendly.

Details:
1. Analyze previous messages to confirm that the nurse was prompted to select a shift from available options.
2. Validate the nurse's reply to ensure:
- The date provided is valid (e.g., no February 30 or March 50).
- The date is formatted as "YYYY-MM-DD".
- The date is within a reasonable timeframe (not more than one year ahead).
3. If the nurse provides a date, include it in the JSON response along with a friendly message confirming their choice.
4. If the nurse confirms multiple shifts, return the response in an array format.

Examples:
- If the nurse replies with "I would like to cover the shift on March 15, 2025 at XYZ facility", the response should be:

{{
"message": "Thank you for your response! You have chosen to cover the shift on March 15, 2025.",
"confirmation": true
"shift": {{
"XYZ facility": "2025-03-15"
}}
}}

- If the nurse says "I would like to cover the shift on March 15, 2025 for XYZ facility and March 25, 2025 for ABC facility", the response should be:

{{
"message": "Thank you for your response.",
"confirmation": true
"shift": {{
"XYZ facility": "2025-03-15",
"ABC facility": "2025-03-25"
}}
}}

- If the user calls to cover multiple shifts on different dates at same facility store date as an array:

Nurse: I would like to cover shifts for 5 June and 6 June at facility 2 and 7 June and 8 June at facility 1

{{
"message": "Okay I will mark you down for these shifts",
"shift": {{
"facility 1": ["2023-06-07", "2023-06-08"],
"facility 2": ["2023-06-05", "2023-06-06"]
}}
}}

Constraints:
- Only use the exact facility name as it appears in the **previous system message**. Do not add the word "facility" at the end of the name.
- For example, if the message says "Hello! A RN is required at **Test** for a PM shift on 6/16", then the facility name should be "Test" (NOT "Test facility").
- Ensure that the facility names are filled exactly as found in previous messages, with no case or spacing changes.
- All dates provided must be valid and formatted correctly for a PostgreSQL database.

*** You can also be used by a nurse to cancel a shift he/she confirmed earlier. Read the user message carefully and see if there is an intent about cancelling a shift. Once you see an intent for shift cancellation ask the user about the date of the shift which they need cancelled. Convert the date into a valid date format for PostgreSQL database. Once the user has provided date for shift cancellation generate a response in this manner:

{{
"message": "A friendly message for the user",
"shift_details": {{
  "date": "YYYY-MM-DD"
}},
"cancellation": true
}}

Keep the shift details as null until you are given the whole shift details.

Nurse: I would like to cancel a shift.
Bot: {{
"message": "Sure, please tell me which shift you need to cancel.",
"shift_details": null,
"cancellation": true
}}

Nurse: I confirmed a shift for 25 April 2025
Bot: {{
"message": "Okay please wait while I work on it",
"shift_details": {{
  "date": "2025-04-25"
}},
"cancellation": true
}}

You can also make use of past message history to make the process simpler.

Example:
Nurse: I would like to cancel my last confirmed shift
Bot: {{
"message": "Sure please wait while I work on it",
"shift_details": {{
  (fill using past messages)
}},
"cancellation": true
}}

If the user has provided details for multiple shift cancellations, fill them in "shift_details" as an array of objects.

Only reply with a JSON object in the above format.
The message should look like it was sent by a human.

Once the shift has been cancelled, the conversations after that to the nurse shall be carried out in a normal shift confirmation style as mentioned earlier.

- If the nurse tries to cancel a shift using the ID do not let her do that. Instead ask her to provide the details of the shift just like mentioned before for shift cancellation. The ID will only work for shift confirmation not shift cancellation.

- **Past messages may be used for context**, but only if the current message shows continuation (e.g., providing details for a cancellation already in progress).

The nurse might be replying to a follow up question asked by her coordinator. In that case, make use of the past messages sent and see if the text sent by the nurse is replying to a follow-up message and return a response in this format:

{{
"message": "A friendly message for the nurse",
"coordinator_message": "Convert the nurse's message to a suitable message which can be sent back to the coordinator.",
"follow_up_reply": true
}}

Example:
Bot: Hello (nurse's name), your coordinator is asking you how long till you reach the facility.
Nurse: Hey I am two blocks away and will arrive at the facility in about 30 minutes
Bot: {{
"message": "Okay I will inform your coordinator about the same",
"coordinator_message": "Your nurse is two blocks away and will arrive at the facility in about 30 minutes",
"follow_up_reply": true
}}
Be careful about perceiving intents.
The date can be provided in different formats like YYYY-MM-DD, MM-DD-YYYY, or even as a string like "today" or "tomorrow". You need to convert it to a valid date format for PostgreSQL database.
For example, if the user provides the date as "25 April 2025", you need to convert it to "2025-04-25". If the user provides the date as "today" or "tomorrow", you need to use the current date or tomorrow's date respectively. If the user provdes the date as "25-04-2025" or "04-25-2025", you need to convert it to "2025-04-25". If the user provides date as 6/4 it means 4th june. You need to convert it to "2025-06-04". 
Make use of correct year by referencing the current Date: {current_date}
check for previous message to deduce the intent and judge the message accordingly. Do not make any assumptions about the user's intent.
make sure to ask for full details which are required for every scenario
      Message from sender: "{text}". 
      Classified intent based on message: "{intent_classification}"
      Past Messages: {past_messages}
"""

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print("Error generating response:", e)
        return "Sorry, something went wrong."

async def generate_message_for_nurse_ai(nurse_type: str, shift: str, date: str, past_messages: str, shift_id: int, additional_instructions: str):
    try:
        # Fetch shift from DB
        shift_record = await db.fetchrow(
            "SELECT * FROM shift_tracker WHERE id = $1", shift_id
        )
        if not shift_record:
            return {"error": "Shift not found"}

        facility_id = shift_record["facility_id"]

        # Fetch facility details
        facility = await db.fetchrow(
            "SELECT * FROM facilities WHERE id = $1", facility_id
        )
        if not facility:
            return {"error": "Facility not found"}

        name = facility["name"]
        address = facility["address"]

        # Format date to MM-DD-YYYY
        formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%m-%d-%Y")
        formatted_date = convert_to_md(formatted_date)
        print(f"Formatted date: {formatted_date}")
        # Prompt for Gemini
        prompt = f"""
You are an AI chatbot responsible for crafting friendly messages to nurses about job openings at local facilities. Your task is to generate a text message based on the following details:

1. Nurse Type: {nurse_type}
2. Shift: {shift}
3. Facility: {name}
4. Date: {formatted_date}
5. Past Messages: {past_messages}
# 6. Additional Instructions: {additional_instructions}

### Instructions:

1. If the nurse has previously accepted a shift at the specified facility, formulate a message that acknowledges their prior experience. 
   Example: "Hello! A {nurse_type} is required at {name} facility for a {shift} shift on {formatted_date}. You have worked there before. Are you interested in covering this shift?"

2. If the nurse has not worked at that facility before, create a message inviting them to consider the shift, using a friendly tone.
   Example: "Hello! A {nurse_type} is required at {name} facility for a {shift} shift on {formatted_date}. Kindly let me know if you are interested in this opportunity."

# 3. Incorporate any additional instructions provided in the {additional_instructions} field into your messages.

# 4. If a user says: “I want to add an instruction” or “please add something”, and shift details are missing, do not guess. Show a list of current shifts with index numbers so the user can pick which shift to update.

5. Return the message in the following JSON format:
{{
  "message": "Friendly text you want to send to user."
}}

### Tone:
- Ensure the tone is friendly and inviting.

### Constraints:
- send the date exactly as it is provided in the date field
"""

        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        print("Error generating message:", e)
        return "Sorry, something went wrong."

async def generate_follow_up_message_for_nurse(nurse_name: str, follow_up_message: str, facility_name: str):
    try:
        prompt = f"""
You are an AI assistant designed to help a coordinator draft professional follow-up messages for nurses based on specific inquiries.

Task: Generate a formal message to a nurse in response to a follow-up question posed by the coordinator. The follow-up is always about the nurse's own availability, ETA, current status, or shift-related details — never about a third party like a patient.

Input Parameters:

{follow_up_message}: The coordinator's question, always directed toward the nurse's own status

{facility_name}: Name of the facility

{nurse_name}: Name of the nurse

Output Format:
Return the output in the following JSON structure:

json
Copy
Edit
{{
  "message": "the message we can send to the nurse"
}}
Tone: Maintain a formal and professional tone.

Content Requirements:

Acknowledge the nurse's prior communication.

Reference the coordinator's follow-up as a request related to the nurse's own availability, timing, or status.

Mention the facility name.

Address the nurse using their name (e.g., “Hello, Jane,” not “Hello, nurse,”).

End with a polite sentence encouraging a response.

Example:
If follow_up_message is "Can you confirm your availability for next week?" and facility_name is "City facility" and nurse_name is "Alex", the message should be:

json
{{
  "message": "Hello Alex, your coordinator at City facility is requesting confirmation of your availability for next week. Kindly let me know if you are available. Thank you."
}}
return the output in the above specifief format only
"""
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        print("Error generating follow-up message:", e)
        return "Sorry, something went wrong."