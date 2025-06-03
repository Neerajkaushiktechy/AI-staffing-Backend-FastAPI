from fastapi import APIRouter, Request, Response, Depends
from app.controller.coordinatorController import admin_get_coordinators_by_facility, admin_get_coordinator_by_id, admin_delete_coordinator, coordinator_chat_bot
from app.middleware.auth import get_current_user
from pydantic import BaseModel

router = APIRouter()

class ChatRequest(BaseModel):
    sender: str
    text: str

@router.post("/api/chat")
async def chat_endpoint(payload: ChatRequest):
    sender = payload.sender
    text = payload.text
    return await coordinator_chat_bot(sender, text)

@router.get("/api/admin/get-coordinators-by-facility/{id}")
async def get_coordinators_by_facility(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_get_coordinators_by_facility(request, response, id=id)

@router.get("/api/admin/get-coordinator-by-id/{id}")
async def get_coordinator_by_id(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_get_coordinator_by_id(request, response, id=id)

@router.delete("/api/admin/delete-coordinator/{id}")
async def delete_coordinator(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_delete_coordinator(request, response, id=id)