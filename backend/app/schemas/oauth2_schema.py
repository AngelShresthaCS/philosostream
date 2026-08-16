from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str
class TokenData(BaseModel):
    id : Optional[str] = None

class Post(BaseModel):
    title: str
    content: str
    class Config:
        orm_mode = True