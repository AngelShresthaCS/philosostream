from fastapi import   HTTPException, status, Depends, APIRouter
from .. schemas import user_schema
from ..utils import hashing
router = APIRouter(
    prefix="/users",
    tags = ['users']
)

@router.post("", status_code=status.HTTP_201_CREATED, response_model=user_schema.UserOut, response_model_by_alias=False)
async def create_user(user: user_schema.User):
    from ..core.database import client
    if client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection not established",
            )
    db = client.philosostream
    collection = db.users
    try:
        hashed_password = hashing.hash(user.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Password hashing failed: {str(e)}"
        )
    print(user.password)
    user_data = user.model_dump()
    user_data["password"] = hashed_password
    try:
        new_user = await collection.insert_one(user_data)
    # Fetch the newly created document directly from the database using its new ID
        created_user = await collection.find_one({"_id": new_user.inserted_id})
    except Exception as e:
        raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"User Couldn't be created in Database: {str(e)}"
                )
        
    # Convert the ObjectId to a string before returning it
    created_user["_id"] = str(created_user["_id"])
    return created_user


