from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    id : Optional[str] = None

class ValidateUser(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
