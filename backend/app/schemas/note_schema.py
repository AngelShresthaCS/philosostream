from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

# 1. Schema for receiving data when a user creates a new note
class NoteCreate(BaseModel):
    content: str
    # Automatically defaults to the current UTC time if not provided
    time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# 2. Schema for returning data from the database to the client
class NoteResponse(BaseModel):
    # Maps MongoDB's internal "_id" to a clean "id" for your frontend
    id: Optional[str] = Field(alias="_id", default=None)
    username: Optional[str] = None
    content: str
    time: datetime
    
    class Config:
        # Allows Pydantic to populate the model using either "id" or "_id"
        populate_by_name = True