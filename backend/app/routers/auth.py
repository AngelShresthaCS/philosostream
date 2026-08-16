from fastapi import   HTTPException, status, Depends, APIRouter, Response
import uuid
from ..core import oauth2
from .. schemas import auth_schema
from ..utils import hashing
router = APIRouter(
    prefix='/login',
    tags=['Authentication']
)
@router.post("", status_code=status.HTTP_200_OK)
async def login(user_credentials: auth_schema.ValidateUser, 
    response: Response):
    from ..core.database import client
    new_session_id = str(uuid.uuid4())
    if client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection not established",
            )
    db = client.philosostream
    collection = db.users
    user = await collection.find_one({"email": user_credentials.email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Invalid Credentials"
        )
    await collection.update_one(
        {"_id": user["_id"]}, 
        {"$set": {"session_id": new_session_id}}
    )
    # If the email exists, verify the plaintext password against the saved database hash
    if not hashing.verify(user_credentials.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Invalid Credentials"
        )
    access_token = oauth2.create_access_token(data={"user_id":str(user["_id"]),
            "session_id": new_session_id})

    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,  # CRITICAL: Prevents JavaScript from stealing the token
        max_age=1800,   # Expires in 1800 seconds (30 minutes)
        samesite="lax", # Protects against Cross-Site Request Forgery (CSRF)
        secure=False,   # Set to True ONLY when you deploy to HTTPS (AWS/production)
    )
    # 4. If they survive both checks, they are in
    return {"access_token":access_token, "token_type":"bearer","message": "Login successful", "user_id": str(user["_id"])}