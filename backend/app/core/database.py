import os

from dotenv import load_dotenv

from pymongo import AsyncMongoClient

load_dotenv()

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