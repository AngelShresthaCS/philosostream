from typing import List

from fastapi import HTTPException, status, APIRouter,Depends, Query
from fastapi.encoders import jsonable_encoder

from bson import ObjectId
from ..core import oauth2

from ..schemas.note_schema import NoteResponse, NoteCreate
from ..schemas import oauth2_schema 
import json

from .. core.database import REDIS_URL,redis_client
from .. utils import searialize

import logging

# Set up a basic logger to format your output cleanly
logger = logging.getLogger("uvicorn.error")

router = APIRouter(
    prefix="/notes",
    tags=['Posts']
)

CACHE_TTL_SECONDS = 60  # Cache duration (1 minute)

@router.get("/", response_model=List[NoteResponse], response_model_by_alias=False)
async def get_notes(
    limit: int = Query(10, ge=1, le=100), # Default 10, min 1, max 100
    skip: int = Query(0, ge=0)            # Default 0, min 0
):
    cache_key = f"notes:limit_{limit}:skip_{skip}"

    # 1. Try to fetch from Redis (with graceful fallback if Redis encounters an issue)
   
        
    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            # CACHE HIT
            logger.info("✅ CACHE HIT! Returning data directly from ElastiCache.")
            
            # Optional: Print the first 100 characters of the JSON to prove it's the right data
            logger.info(f"📦 Cached Data Preview: {cached_data[:100]}...") 
            
            return json.loads(cached_data)
    except Exception as e:
        logger.error(f"⚠️ Redis read error: {e}")
        print(f"Redis read error: {e}")

    # CACHE MISS
    logger.warning("❌ CACHE MISS! Data not in ElastiCache. Reaching out to MongoDB Atlas...")
    # 2. Cache Miss: Connect to MongoDB
    from ..core.database import client

    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection not established",
        )

    db = client.philosostream
    collection = db.notes

    # 3. Query MongoDB with pagination
    notes_cursor = collection.find({}).skip(skip).limit(limit)
    notes = await notes_cursor.to_list(length=limit)

    for note in notes:
        note["_id"] = str(note["_id"])

    # 4. Store the result in Redis with a TTL
    try:
        # jsonable_encoder handles datetime objects and other BSON types safely
        serialized_notes = jsonable_encoder(notes)
        await redis_client.setex(
            cache_key,
            CACHE_TTL_SECONDS,
            json.dumps(serialized_notes)
        )
    except Exception as e:
        # If cache write fails, the client still gets the database response
        print(f"Redis write error: {e}")

    return notes

@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(note: NoteCreate, token_data: oauth2_schema.TokenData = Depends(oauth2.get_current_user)):
    

    from ..core.database import client
    
    if client is None:
        raise HTTPException(status_code=500, detail="Database connection not established")
        
    db = client.philosostream
    collection = db.notes
    users = db.users

    user = await users.find_one({"_id":ObjectId(token_data.id)})
    
    # .model_dump() converts the Pydantic schema into a standard Python dictionary so Mongo can read it
    note_dict = note.model_dump()

    note_dict["username"] = user["username"]
    
    # Insert the new note into the database
    new_note = await collection.insert_one(note_dict)
    
    # Fetch the newly created document directly from the database using its new ID
    created_note = await collection.find_one({"_id": new_note.inserted_id})
    
    # Convert the ObjectId to a string before returning it
    created_note["_id"] = str(created_note["_id"])
    print("done")
    print(created_note)
    return created_note