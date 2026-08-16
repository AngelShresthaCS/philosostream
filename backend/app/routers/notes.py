from typing import List

from fastapi import HTTPException, status, APIRouter,Depends, Query
from bson import ObjectId
from ..core import oauth2

from ..schemas.note_schema import NoteResponse, NoteCreate
from ..schemas import oauth2_schema 



router = APIRouter(
    prefix="/notes",
    tags=['Posts']
)

@router.get("/", response_model=List[NoteResponse], response_model_by_alias=False)
async def get_notes(
    limit: int = Query(10, ge=1, le=100), # Default 10, min 1, max 100
    skip: int = Query(0, ge=0)            # Default 0, min 0
):
    from ..core.database import client

    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection not established",
        )

    db = client.philosostream
    collection = db.notes

    # Convert the MongoDB '_id' to a string because ObjectId is not JSON serializable
    # Pagination enabled
    notes_cursor = collection.find({}).skip(skip).limit(limit)
    notes = await notes_cursor.to_list(length=100)
    for note in notes:
        note["_id"] = str(note["_id"])

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