# Securing FastAPI JWTs: Implementing Single-Session Limits

You have just discovered the fundamental double-edged sword of using JWTs (JSON Web Tokens). 

By design, JWTs are **stateless**. This means your FastAPI backend does not keep a list of active tokens in its memory. When you log in, the server signs a token and hands it to you. Because it has a mathematically valid signature and an expiration time in the future, the server will trust it blindly. If you spam the login button 50 times, you will successfully create 50 mathematically valid tokens that all live for 30 minutes.

Here is how you solve this.

## The Good News: The Browser is Already Helping You

Because you are now using `HttpOnly` cookies instead of standard JSON responses, the browser handles part of this problem for you automatically. 

When you spam login, the server sends back a `Set-Cookie` header every single time. The browser sees this and immediately overwrites the old cookie with the new one. So, from the user's perspective, they aren't stuck with the old token's remaining time. They get a fresh 30-minute token every time they log in, and their browser throws the old one in the trash.

## The Security Problem

Even though the *browser* threw the old token away, the *server* still thinks it is valid. If a hacker managed to copy that old token before you logged in again, they could still use it until its 30 minutes ran out.

## The Enterprise Solution: Token Versioning (Session IDs)

To force the server to only accept the **newest** token and instantly invalidate all older ones, you need to introduce a tiny bit of state into your database. We do this by attaching a unique "Session ID" to both the user's database document and the JWT payload.

Here is how you implement this in your code:

### Step 1: Update the Login Route (`auth.py`)

Every time a user logs in, generate a random string, save it to their MongoDB document, and put it inside their JWT.

```python
import uuid # Add this to your imports
from fastapi import APIRouter, HTTPException, status, Response

@router.post("", status_code=status.HTTP_200_OK)
async def login(user_credentials: auth_schema.ValidateUser, response: Response):
    # ... your existing DB connection and password verification ...

    # 1. Generate a brand new, random Session ID for this specific login
    new_session_id = str(uuid.uuid4())

    # 2. Save this Session ID to the user's document in MongoDB
    await collection.update_one(
        {"_id": user["_id"]}, 
        {"$set": {"session_id": new_session_id}}
    )

    # 3. Inject BOTH the user_id and the session_id into the JWT
    access_token = oauth2.create_access_token(
        data={
            "user_id": str(user["_id"]),
            "session_id": new_session_id # The token now carries the session ID
        }
    )

    # ... your existing response.set_cookie and return logic ...