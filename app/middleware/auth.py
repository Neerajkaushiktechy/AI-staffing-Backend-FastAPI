# dependencies/auth.py
from fastapi import Request, HTTPException
from jose import jwt, JWTError
import os

JWT_SECRET = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"

def get_current_user(request: Request):
    token = request.cookies.get("auth_token")
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        request.state.user = payload
        return payload
    except JWTError:
        raise HTTPException(status_code=403, detail="Invalid token")
