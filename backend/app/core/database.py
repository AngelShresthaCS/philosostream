import os

from dotenv import load_dotenv

from pymongo import AsyncMongoClient
import redis.asyncio as redis


load_dotenv()


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)



MONGODB_URI = os.environ["MONGODB_URL"]

client: AsyncMongoClient | None = None


async def connect_to_mongo():
    global client
    client = AsyncMongoClient(MONGODB_URI)


async def close_mongo_connection():
    if client is not None:
        await client.close()


async def ping():
    await client.admin.command("ping")