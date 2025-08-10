from fastapi import FastAPI
from pydantic import BaseModel
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import httpx
import os
from dotenv import load_dotenv
import asyncio
from datetime import datetime

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
MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2/"
COVERART_BASE_URL = "https://coverartarchive.org"

client = AsyncIOMotorClient(MONGO_URI)
db = client["songFinder"]
collection = db["songs"]
reviews_collection = db["reviews"]

class Song(BaseModel):
    song: str
    username: str
    artist: Optional[str] = None
    title: Optional[str] = None
    image: Optional[str] = None
    listeners: Optional[str] = None
    url: Optional[str] = None

class SearchQuery(BaseModel):
    query: str

class Review(BaseModel):
    song_name: str
    artist: str
    title: str
    username: str
    score: float  # 0-10 scale
    review_text: str
    image: Optional[str] = None

class ReviewUpdate(BaseModel):
    score: float
    review_text: str

@app.get("/")
async def root():
    return {"message": "Hello World"}

async def get_musicbrainz_image(artist: str, track: str) -> Optional[str]:
    """Get cover art from MusicBrainz/Cover Art Archive as fallback"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {
                "User-Agent": "SongFinder/1.0 (your-email@example.com)"
            }
            
            query = f'recording:"{track}" AND artist:"{artist}"'
            params = {
                "query": query,
                "fmt": "json",
                "limit": 1
            }
            
            url = f"{MUSICBRAINZ_BASE_URL}recording"
            response = await client.get(url, params=params, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if "recordings" in data and data["recordings"]:
                    recording = data["recordings"][0]
                    
                    if "releases" in recording and recording["releases"]:
                        first_release = recording["releases"][0]
                        if "release-group" in first_release:
                            release_group_id = first_release["release-group"]["id"]
                            
                            cover_url = f"{COVERART_BASE_URL}/release-group/{release_group_id}/front"
                            cover_response = await client.head(cover_url, follow_redirects=True)
                            if cover_response.status_code == 200:
                                return str(cover_response.url)
    except Exception as e:
        print(f"MusicBrainz lookup failed: {e}")
    
    return None

@app.post("/api/search")
async def search_songs(search: SearchQuery):
    """Search for songs using Last.fm API with MusicBrainz fallback for images"""
    try:
        async with httpx.AsyncClient() as lastfm_client:
            params = {
                "method": "track.search",
                "track": search.query,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": 8
            }
            response = await lastfm_client.get(LASTFM_BASE_URL, params=params)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Last.fm API error")
            
            data = response.json()
            
            tracks = []
            if "results" in data and "trackmatches" in data["results"] and "track" in data["results"]["trackmatches"]:
                track_list = data["results"]["trackmatches"]["track"]
                
                # Handle case where only one result is returned (not in a list)
                if isinstance(track_list, dict):
                    track_list = [track_list]
                
                for track in track_list:
                    artist_name = track.get('artist', 'Unknown Artist')
                    track_title = track.get('name', 'Unknown Track')
                    
                    # Always get image from MusicBrainz
                    image_url = await get_musicbrainz_image(artist_name, track_title)
                    await asyncio.sleep(0.1)
                    
                    track_data = {
                        "name": f"{artist_name} - {track_title}",
                        "artist": artist_name,
                        "title": track_title,
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
    async for song_doc in collection.find({"username": username}):
        song_doc.pop('_id', None)
        
        # Check if user has reviewed this song
        review = await reviews_collection.find_one({
            "username": username,
            "song_name": song_doc.get("song", ""),
            "artist": song_doc.get("artist", ""),
            "title": song_doc.get("title", "")
        })
        
        if review:
            song_doc["user_score"] = review["score"]
            song_doc["user_review"] = review["review_text"]
            song_doc["has_review"] = True
        else:
            song_doc["has_review"] = False
            
        songs.append(song_doc)
    return {"songs": songs}

@app.delete("/api/songs/{username}/{song_name}")
async def delete_song_by_name(username: str, song_name: str):
    result = await collection.delete_one({"song": song_name, "username": username})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Song not found")
    
    #  delete  associated review
    await reviews_collection.delete_one({"song_name": song_name, "username": username})
    
    return {"message": f"Song '{song_name}' deleted successfully"}

@app.delete("/api/songs/{username}")
async def clear_all_user_songs(username: str):
    result = await collection.delete_many({"username": username})
    #  delete all reviews by this user
    await reviews_collection.delete_many({"username": username})
    return {"message": f"All songs cleared for user '{username}'", "deleted_count": result.deleted_count}

@app.post("/api/reviews")
async def add_review(review: Review):
    """Add or update a review for a song"""
    song_exists = await collection.find_one({
        "song": review.song_name,
        "username": review.username
    })
    
    if not song_exists:
        raise HTTPException(status_code=404, detail="Song not found in user's list")
    
    existing_review = await reviews_collection.find_one({
        "song_name": review.song_name,
        "username": review.username
    })
    
    review_dict = review.dict()
    review_dict["created_at"] = datetime.now()
    review_dict["updated_at"] = datetime.now()
    
    if existing_review:
        review_dict["updated_at"] = datetime.now()
        await reviews_collection.replace_one(
            {"_id": existing_review["_id"]}, 
            review_dict
        )
        return {"message": "Review updated successfully"}
    else:
        await reviews_collection.insert_one(review_dict)
        return {"message": "Review added successfully"}

@app.put("/api/reviews/{username}/{song_name}")
async def update_review(username: str, song_name: str, review_update: ReviewUpdate):
    """Update an existing review"""
    result = await reviews_collection.update_one(
        {"song_name": song_name, "username": username},
        {
            "$set": {
                "score": review_update.score,
                "review_text": review_update.review_text,
                "updated_at": datetime.now()
            }
        }
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Review not found")
    
    return {"message": "Review updated successfully"}

@app.get("/api/reviews")
async def get_all_reviews():
    """Get all reviews for the reviews page"""
    reviews = []
    async for review_doc in reviews_collection.find({}).sort("created_at", -1):
        review_doc.pop('_id', None)
        if 'created_at' in review_doc:
            review_doc['created_at'] = review_doc['created_at'].isoformat()
        if 'updated_at' in review_doc:
            review_doc['updated_at'] = review_doc['updated_at'].isoformat()
        reviews.append(review_doc)
    return {"reviews": reviews}

@app.get("/api/reviews/{song_name}")
async def get_song_reviews(song_name: str):
    """Get all reviews for a specific song"""
    reviews = []
    async for review_doc in reviews_collection.find({"song_name": song_name}).sort("created_at", -1):
        review_doc.pop('_id', None)
        if 'created_at' in review_doc:
            review_doc['created_at'] = review_doc['created_at'].isoformat()
        if 'updated_at' in review_doc:
            review_doc['updated_at'] = review_doc['updated_at'].isoformat()
        reviews.append(review_doc)
    return {"reviews": reviews}

@app.delete("/api/reviews/{username}/{song_name}")
async def delete_review(username: str, song_name: str):
    """Delete a review"""
    result = await reviews_collection.delete_one({
        "song_name": song_name,
        "username": username
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Review not found")
    
    return {"message": "Review deleted successfully"}