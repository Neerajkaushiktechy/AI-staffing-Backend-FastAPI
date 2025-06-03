from app.controller.shiftController import admin_get_shifts, admin_get_all_shifts, admin_delete_shift, admin_add_shift, admin_get_shift_by_id, admin_edit_shift
from fastapi import APIRouter, Request, Response, Depends
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/api/admin", tags=["Admin"])

@router.get("/get-shifts")
async def get_shifts(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_get_shifts(request, response)

@router.get("/get-all-shifts")
async def get_all_shifts(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_get_all_shifts(request, response)

@router.delete("/delete-shift/{shift_id}")
async def delete_shift(request: Request, response: Response, shift_id: int, user=Depends(get_current_user)):
    return await admin_delete_shift(request, response, shift_id=shift_id)

@router.post("/add-shift")
async def add_shift(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_add_shift(request, response)

@router.get("/get-shift-by-id/{id}")
async def get_shift_by_id(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_get_shift_by_id(request, response, id=id)

@router.put("/edit-shift/{id}")
async def edit_shift(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_edit_shift(request, response, id=id)