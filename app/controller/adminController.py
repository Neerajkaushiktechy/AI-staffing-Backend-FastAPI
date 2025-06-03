from fastapi import Request, Response
from jose import jwt
from app.database import db
import os
from dotenv import load_dotenv
import logging
load_dotenv()
logger = logging.getLogger(__name__)
SECRET_KEY = os.getenv("JWT_SECRET")

async def admin_login(request: Request, response: Response, email: str, password: str):
    query = "SELECT * FROM admin WHERE email = $1"
    admin = await db.fetchrow(query, email)

    if not admin or password != admin["password"]:
        return {"message": "Invalid email or password", "status": 404}

    token = jwt.encode(
        {"id": admin["id"], "email": admin["email"]},
        SECRET_KEY,
        algorithm="HS256"
    )

    # Set HTTP-only cookie
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=24 * 60 * 60,
    )

    return {
        "message": "Login successful",
        "user": {"id": admin["id"], "email": admin["email"]},
        "token": token,
        "status": 200
    }

async def admin_logout(request: Request, response: Response):
    response.delete_cookie("auth_token")
    return {"message": "Logout successful", "status": 200}


