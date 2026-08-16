from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class User(BaseModel):
    username: str
    name: Optional[str] = None
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    # class Config:
    #     orm_mode = True

class UserOut(BaseModel):
    id: Optional[str] = Field(alias="_id", default=None)
    username: str
    name: str
    email: EmailStr
    password: str
