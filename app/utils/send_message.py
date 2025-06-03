# send_message.py
import os
import asyncio
import httpx
from fastapi import HTTPException

async def sleep(ms: int):
    await asyncio.sleep(ms / 1000)  # convert ms to seconds

async def send_message(recipient: str, message: str):
    await sleep(5000)

    host_mac = os.getenv("HOST_MAC")
    if not host_mac:
        raise EnvironmentError("HOST_MAC environment variable is not set")

    url = f"{host_mac}/send_message/"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={"recipient": recipient, "message": message})
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        print(f"Failed to send message to {recipient}: {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        print(f"Error sending message to {recipient}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
