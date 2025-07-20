from fastapi import FastAPI
from pydantic import BaseModel
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import httpx
import os
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = "mongodb://localhost:27017"
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
LASTFM_BASE_URL = "http://ws.audioscrobbler.com/2.0/"

client = AsyncIOMotorClient(MONGO_URI)
db = client["songFinder"]
collection = db["songs"]

# Define the data models
class Song(BaseModel):
    song: str
    username: str
    artist: Optional[str] = None
    title: Optional[str] = None
    image: Optional[str] = None

class SearchQuery(BaseModel):
    query: str

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.post("/api/search")
async def search_songs(search: SearchQuery):
    """Search for songs using Last.fm API"""
    try:
        async with httpx.AsyncClient() as client:
            params = {
                "method": "track.search",
                "track": search.query,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": 20 # Limit results to 20 songs
            }
            response = await client.get(LASTFM_BASE_URL, params=params)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Last.fm API error")
            
            data = response.json()
            
            # Extract track information
            tracks = []
            if "results" in data and "trackmatches" in data["results"] and "track" in data["results"]["trackmatches"]:
                track_list = data["results"]["trackmatches"]["track"]
                
                # Handle case where only one result is returned (not in a list)
                if isinstance(track_list, dict):
                    track_list = [track_list]
                
                for track in track_list:
                    # Extract image information
                    image_url = None
                    if "image" in track and isinstance(track["image"], list):
                        # Last.fm provides images in different sizes: small, medium, large, extralarge
                        # Let's get the largest available image
                        for img in reversed(track["image"]):  # Start from the end (usually largest)
                            if img.get("#text"):  # Check if image URL exists
                                image_url = img["#text"]
                                break
                    
                    # Format track data
                    track_data = {
                        "name": f"{track.get('artist', 'Unknown Artist')} - {track.get('name', 'Unknown Track')}",
                        "artist": track.get('artist', 'Unknown Artist'),
                        "title": track.get('name', 'Unknown Track'),
                        "image": image_url,
                        "listeners": track.get('listeners'),
                        "url": track.get('url')
                    }
                    tracks.append(track_data)
            
            return {"songs": tracks}
            
    except httpx.RequestError:
        raise HTTPException(status_code=500, detail="Failed to connect to Last.fm API")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")

@app.post("/api/songs")
async def add_song(song: Song):
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