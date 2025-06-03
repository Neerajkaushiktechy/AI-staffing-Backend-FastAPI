from fastapi import APIRouter, Request, Response, Depends
from app.controller.adminController import admin_login, admin_logout
router = APIRouter(prefix="/api/admin", tags=["Admin"])

@router.post("/login")
async def login(request: Request, response: Response):
    body = await request.json()
    email = body.get("email")
    password = body.get("password")
    return await admin_login(request, response, email, password)

@router.post("/logout")
async def logout(request: Request, response: Response):
    return await admin_logout(request, response)

