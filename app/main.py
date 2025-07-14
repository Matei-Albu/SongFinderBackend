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
    username: str

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.post("/api/songs")
async def add_song(song: Song):
    # Check if the song already exists for this user
    existing_song = await collection.find_one({"song": song.song, "username": song.username})
    if existing_song:
        raise HTTPException(status_code=400, detail="Song already exists for this user")
    
    song_dict = song.dict()
    result = await collection.insert_one(song_dict)
    return {
        "message": f"Song '{song.song}' added successfully!",
        "id": str(result.inserted_id)
    }

@app.get("/api/songs/{username}")
async def get_user_songs(username: str):
    songs = []
    async for song in collection.find({"username": username}):
        songs.append(song["song"])
    return {"songs": songs}

@app.delete("/api/songs/{username}/{song_name}")
async def delete_song_by_name(username: str, song_name: str):
    result = await collection.delete_one({"song": song_name, "username": username})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Song not found")
    return {"message": f"Song '{song_name}' deleted successfully"}

@app.delete("/api/songs/{username}")
async def clear_all_user_songs(username: str):
    result = await collection.delete_many({"username": username})
    return {"message": f"All songs cleared for user '{username}'", "deleted_count": result.deleted_count}