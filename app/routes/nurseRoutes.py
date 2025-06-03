from fastapi import APIRouter,Request, Response, Depends
from pydantic import BaseModel
from app.controller.nurseController import nurse_chat_bot
from app.middleware.auth import get_current_user
from app.controller.nurseController import admin_get_nurses,admin_get_nurse_by_id,admin_add_nurse,admin_edit_nurse,admin_delete_nurse,admin_get_available_nurses, admin_get_nurse_types, admin_get_nurse_type, admin_delete_nurse_type, admin_edit_nurse_type, admin_add_nurse_type, admin_delete_service
router = APIRouter()

class ChatNurseRequest(BaseModel):
    sender: str
    text: str

@router.post("/api/chat_nurse")
async def chat_nurse_endpoint(payload: ChatNurseRequest):
    sender = payload.sender
    text = payload.text
    return await nurse_chat_bot(sender, text)

@router.get("/api/admin/get-nurses")
async def get_nurse_types(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_get_nurses(request, response)

@router.get("/api/admin/get-nurse-by-id/{id}")
async def get_nurse_by_id(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_get_nurse_by_id(request, response, id=id)

@router.post("/api/admin/add-nurse")
async def add_nurse(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_add_nurse(request, response)

@router.put("/api/admin/edit-nurse/{id}")
async def edit_nurse(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_edit_nurse(request, response, id=id)

@router.delete("/api/admin/delete-nurse/{id}")
async def delete_nurse(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_delete_nurse(request, response, id=id)

@router.get("/api/admin/get-available-nurses")
async def get_available_nurses(request: Request, response: Response):
    return await admin_get_available_nurses(request, response)

@router.post("/api/admin/add-nurse-type")
async def add_nurse_type(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_add_nurse_type(request, response)

@router.get("/api/admin/get-nurse-type")
async def get_nurses(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_get_nurse_type(request, response)

@router.get("/api/admin/get-nurse-types")
async def get_nurse_types(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_get_nurse_types(request, response)

@router.delete("/api/admin/delete-nurse-type/{id}")
async def delete_nurse_type(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_delete_nurse_type(request, response, id=id)

@router.put("/api/admin/edit-nurse-type/{id}")
async def edit_nurse_type(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_edit_nurse_type(request, response, id=id)

@router.delete("/api/admin/delete-service/{id}/{role}")
async def delete_service(request: Request, response: Response, id: int, role: str, user=Depends(get_current_user)):
    return await admin_delete_service(request, response, id=id, role=role)
