from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import adminRoutes, nurseRoutes, facilityRoutes, coordinatorRoutes, shiftRoutes
from app.database import db
app = FastAPI()

@app.on_event("startup")
async def startup():
    await db.connect()

origins = [
    "http://localhost:5173", 
    "https://your-frontend-domain.com" 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,            
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(adminRoutes.router)
app.include_router(nurseRoutes.router)
app.include_router(facilityRoutes.router)
app.include_router(coordinatorRoutes.router)
app.include_router(shiftRoutes.router)
