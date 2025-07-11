from fastapi import FastAPI
from pydantic import BaseModel
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = "mongodb://localhost:27017"
client = AsyncIOMotorClient(MONGO_URI)

db = client["songFinder"]
collection = db["songs"]

# Define the data model
class Song(BaseModel):
    song: str

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.post("/api/songs")
async def add_song(song: Song):
    song_dict = song.dict()
    result = await collection.insert_one(song_dict)
    return {
        "message": f"Song '{song.song}' added successfully!",
        "id": str(result.inserted_id)
    }

@app.delete("/api/songs/{song_name}")
async def delete_song_by_name(song_name: str):
    result = await collection.delete_one({"song": song_name})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Song not found")
    return {"message": f"Song '{song_name}' deleted successfully"}

