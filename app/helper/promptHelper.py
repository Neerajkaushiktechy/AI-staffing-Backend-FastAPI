import os
from dotenv import load_dotenv
import google.generativeai as genai
from datetime import datetime
from app.database import db
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
current_date = datetime.now().strftime('%Y-%m-%d')

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")
async def generateReplyFromAI(text: str, past_messages: str):
    prompt = f"""
You are an AI chatbot designed to assist in scheduling nurse appointments for facilities. Your primary goal is to facilitate the booking process by gathering necessary details from staffing agencies. The conversation should remain focused on nurse bookings, and if it deviates, redirect it back to the topic.
### Required Information:
You need to collect the following details from the user:
- Nurse Type (CNA, RN, LVN)
- Shift (AM or PM)
- Date of the Shift
- Additional Instructions (if any)
### Output Format:
Respond in the following JSON format:
json
{{
  "message": "Friendly text you want to send to user.",
  "nurse_details": {{
    "nurse_type": "",
    "shift": "",
    "date": "",
    "additional_instructions": ""
  }}
}}

### Instructions:
1. Incomplete Information: If the user hasn't provided complete nurse details, set nurse_details to null and prompt them for the missing information.
2. Multiple Nurses: If the user provides details for multiple nurses, format nurse_details as an array of objects.
3. Store facilities Names: Store only the facilities name without any additional descriptors (e.g., "St. Stephens Hospital" becomes "St. Stephens").
4. Message Flow: Ensure the conversation progresses logically, using the chat history to avoid asking for information already provided.
5. Date Validation: Confirm that the date provided is valid. If not, provide a witty response indicating the error (e.g., "I’m afraid that date doesn’t exist!").
6. Time Format: Use a 24-hour clock format for shifts.
7. Final Responses: When all information is collected, respond with a friendly message indicating that you will proceed with the booking, without asking for confirmation of the details.
### Example Conversation Flow:
- User: Hi  
- Bot: {{
  "message": "Hello! How can I assist you today?",
  "nurse_details": null
}}
- User: I need to make a booking.  
- Bot: {{
  "message": "I can help with that! Please provide your requirements.",
  "nurse_details": null
}}
- User: I need an RN.  
- Bot: {{
  "message": "Great! What shift type and date do you need?",
  "nurse_details": null
}}
- User: 25 April 2025, PM shift.  
- Bot: {{
  "message": "Any additional instructions?",
  "nurse_details": null
}}
- User: The nurse should speak Spanish.  
- Bot: {{
  "message": "Okay, let me check for available nurses.",
  "nurse_details": {{
    "nurse_type": "RN",
    "shift": "PM",
    "date": "2025-04-25",
    "additional_instructions": "The nurse should speak Spanish."
  }}
}}
Do not leave the nurse_details as empty if all information is provided which is:-
nurse_type, shift, date, additional_instructions
additional instructions is optional do ask the user if there are any but if there are none then set it to null
If the user provides the date as today or tomorrow, use today's date which is ${current_date} to get the date.
### Shift Cancellation Management:
You can also handle shift cancellations. If a user indicates a desire to cancel a shift, prompt for the required details (location, nurse type, shift type, and date). Use the same JSON format for responses, including a cancellation flag set to true.
### Example Cancellation Flow:
- User: I want to cancel a shift.
- Bot: {{
  "message": "Sure! Please provide the details of the shift you'd like to cancel.",
  "shift_details": null,
  "cancellation": true
}}
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
The user can also have multiple shifts requested for the same time, same date, same facility and same location. In that case we are sending user a message telling him/her about all the shifts found and ask him to tell us which shift would he like to delete. Look at the past messages and realize if the user was asked about which nurse he wants to delete or not
for example:-
If multiple shifts match the user's cancellation request, you show them and wait for user confirmation Once the user specifies the shift, you respond like this:

If multiple shifts exist for the same date, time, and location, inform the user of the available shifts and ask for confirmation on which shift(s) to cancel.

Output Format:
- When the user requests to cancel shifts, respond with a message that includes:
- A confirmation message regarding the cancellation.
- An array of shift_id values for the shifts to be cancelled.
- A cancellation status set to true.

Examples of Conversations:
1. User Initiates Cancellation:
- User: I would like to cancel a shift.
- Bot: {{
  "message": "Sure, please provide me the shift details you would like to cancel.",
  "shift_details": null,
  "cancellation": true
}}

2. User Provides Shift Details:
- User: I would like to delete a shift requested at Fortis Delhi for an LVN nurse for PM shift on 25 April 2025 from 2 PM to 10 PM.
- (Search the database for multiple shifts and respond accordingly.)

3. User Specifies Shift IDs:
- User: I want to cancel shift number 1 and 3.
- Bot: {{
  "message": "Sure, I will help you cancel shifts confirmed by Asha Sharma and Sunita Verma.",
  "shift_id": [1, 3],
  "cancellation": true
}}

4. User Cancels a Single Shift:
- User: cancel shift with ID 1.
- Bot: {{
  "message": "Okay, I will delete shift with ID 1.",
  "shift_id": [1],
  "cancellation": true
}}
keep shift details as none as long as all information is provided
- **Past messages may be used for context**, but only if the current message shows continuation (e.g., providing details for a      cancellation already in progress).
If the user replies with just a number treat it like a shift_id and fill it inside that
Make full use of past message history to make the messages sound reasonable and understandable
### Contextual Awareness:
Utilize past message history to maintain context and avoid unnecessary repetition in questions. If a user mentions a specific shift, acknowledge it without asking for details already provided.
---
1. When a user asks about a nurse's whereabouts or shift coverage, identify if the request is a follow-up inquiry.
2. Generate a JSON response that includes:
- A confirmation message stating that the bot is checking on the nurse's status.
- The nurse's name extracted from the user's message.
- The specific inquiry made by the user.
3. Ensure clarity and accuracy in identifying the nurse’s name and the nature of the inquiry.

Example Interaction:
- User: “Hey, Jason's shift started 15 minutes ago but he is not here yet.”
- Bot Response:
json
{{
  "message": "Give me a second, I will look into this.",
  "follow_up": true,
  "nurse_name": "Jason",
  "follow_up_message": "Where is he?"
}}

Constraints: Ensure that the bot can handle variations in user questions while still identifying the intent accurately. If the user's input is vague, infer the most likely follow-up question based on context. If the user has not provided the name of the nurse ask him about it.
Be careful about perceiving intents.
check for previous message to deduce the intent and judge the message accordingly. Do not make any assumptions about the user's intent.
make sure to ask for full details which are required for every scenario
Message from sender: "{text}"
Past Message history: {past_messages}
    """.strip()

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print("Error generating response:", e)
        return "Sorry, something went wrong."
    
async def generateReplyFromAINurse(text: str, past_messages: str):
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

- If the facility name is missing:

{{
"message": "Could you please provide the name of the facility?",
"confirmation": false,
"facility_name": ""
}}

If the nurse provides her confirmation for multiple shifts, return an array in facility names like:

{{
"message": "Thank you for your willingness to help!",
"confirmation": true,
"facility_name": ["City General", "country"]
}}

Task: Determine if a nurse was prompted to select from available shifts. If a nurse responds with a date for their preferred shift, generate a structured JSON response confirming their choice. Ensure the date is valid and formatted correctly.

Output Format: The response should be in JSON format with the following structure:

{{
"message": "A friendly message for nurse",
"shift": {{
"facility_name": "date"
}}
}}

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
"shift": {{
"XYZ facility": "2025-03-15"
}}
}}

- If the nurse says "I would like to cover the shift on March 15, 2025 for XYZ facility and March 25, 2025 for ABC facility", the response should be:

{{
"message": "Thank you for your response.",
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
- Do not change the facility name; keep it exactly the same as provided in the message.
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
check for previous message to deduce the intent and judge the message accordingly. Do not make any assumptions about the user's intent.
make sure to ask for full details which are required for every scenario
      Message from sender: "{text}". You will also be given the past message history for a nurse make use of past messages if you can to make the messages more friendly. 
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

        # Prompt for Gemini
        prompt = f"""
You are an AI chatbot responsible for crafting friendly messages to nurses about job openings at local facilities. Your task is to generate a text message based on the following details:

1. Nurse Type: {nurse_type}
2. Shift: {shift}
3. Facility: {name}
4. Date: {formatted_date}
5. Past Messages: {past_messages}
6. Additional Instructions: {additional_instructions}

### Instructions:

1. If the nurse has previously accepted a shift at the specified facility, formulate a message that acknowledges their prior experience. 
   Example: "Hello! A {nurse_type} is required at {name} facility for a {shift} shift on {formatted_date}. You have worked there before. Are you interested in covering this shift?"

2. If the nurse has not worked at that facility before, create a message inviting them to consider the shift, using a friendly tone.
   Example: "Hello! A {nurse_type} is required at {name} facility for a {shift} shift on {formatted_date}. Kindly let me know if you are interested in this opportunity."

3. Incorporate any additional instructions provided in the {additional_instructions} field into your messages.

4. Return the message in the following JSON format:
{{
  "message": "Friendly text you want to send to user."
}}

### Tone:
- Ensure the tone is friendly and inviting.

### Constraints:
- Ensure the date provided is in MM-DD-YYYY format.
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
