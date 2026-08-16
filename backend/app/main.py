from fastapi import FastAPI
from fastapi.responses import JSONResponse
from .core.database import connect_to_mongo, close_mongo_connection, ping
from . routers import notes,auth,users

app = FastAPI()

app.include_router(notes.router)
app.include_router(auth.router)
app.include_router(users.router)

@app.on_event("startup")
async def startup_event():
    await connect_to_mongo()

@app.on_event("shutdown")
async def shutdown_event():
    await close_mongo_connection()

@app.get("/")
async def root():
    return {"message": "FastAPI + AsyncMongoClient is running. Try GET /ping-db"}

@app.get("/ping-db")
async def ping_db():
    try:
        await ping()
        return {"ok": True, "message": "MongoDB is reachable"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})