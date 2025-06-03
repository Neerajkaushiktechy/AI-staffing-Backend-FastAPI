from fastapi import APIRouter, Request, Response, Depends
from app.middleware.auth import get_current_user
from app.controller.facilityController import admin_add_facility, admin_edit_facility, admin_get_facilities, admin_get_facility_by_id, admin_delete_facility

router = APIRouter(prefix="/api/admin", tags=["Admin"])

@router.post("/add-facility")
async def add_facility(request: Request, response: Response,user=Depends(get_current_user)):
    return await admin_add_facility(request, response)


@router.put("/edit-facility/{facility_id}")
async def edit_facility(request: Request, response: Response, facility_id: int, user=Depends(get_current_user)):
    return await admin_edit_facility(request, response, facility_id=facility_id)

@router.get("/get-facility")
async def get_facilities(request: Request, response: Response, user=Depends(get_current_user)):
    return await admin_get_facilities(request, response)

@router.get("/get-facility-by-id/{id}")
async def get_facility_by_id(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_get_facility_by_id(request, response, id=id)

@router.delete("/delete-facility/{id}")
async def delete_facility(request: Request, response: Response, id: int, user=Depends(get_current_user)):
    return await admin_delete_facility(request, response, id=id)
