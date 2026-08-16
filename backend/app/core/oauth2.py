import os
from bson import ObjectId
from dotenv import load_dotenv
from jose import JWTError, jwt
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta
from .. schemas import oauth2_schema

load_dotenv()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='login')

# No default: a missing SECRET_KEY must crash at import, exactly like MONGODB_URL
# in database.py. Falling back to a hardcoded default would silently re-create
# the problem this change exists to fix.
SECRET_KEY = os.environ["SECRET_KEY"]

# These two are not secrets, so a sane default is fine if .env omits them.
ALGORITHM = os.getenv("ALGORITHM", "HS256")
# int() is required — os.getenv always returns a str, and timedelta(minutes="30")
# raises TypeError.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))




def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp":expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


async def verify_access_token(token: str, credentials_exception):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        id: str = payload.get("user_id")
        token_session_id: str = payload.get("session_id")
        if id is None or token_session_id is None:
            raise credentials_exception
        token_data = oauth2_schema.TokenData(id=str(id))
    except JWTError:
        raise credentials_exception

    # 2. Connect to the database to check the user's current valid session
    from .database import client
    db = client.philosostream
    user = await db.users.find_one({"_id": ObjectId(id)})

    if not user:
        raise credentials_exception

    # 3. THE KILL SWITCH: If the token's session ID does not match the database, 
    # it means they logged in again somewhere else. Reject the old token!
    if user.get("session_id") != token_session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. You logged in on another device."
        )
    
    return token_data


# 1. Create a tiny extractor function to rip the token out of the incoming cookie
def get_token_from_cookie(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Not authenticated"
        )
    
    # Strip the "Bearer " part off the string to get the raw JWT
    _, _, raw_token = token.partition(" ")
    return raw_token

async def get_current_user(token: str  = Depends(get_token_from_cookie)):
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate":"Bearer"})
    return await verify_access_token(token, credentials_exception)
