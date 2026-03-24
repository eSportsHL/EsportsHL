from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import utils
import json
import os

app = FastAPI()

# Allow your frontend to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/standings")
async def get_standings():
    sh = utils.get_sheet()
    try:
        ws = sh.worksheet("Standings")
        return ws.get_all_records()
    except:
        return {"error": "Standings sheet not found"}

@app.get("/api/leaders")
async def get_leaders():
    # Uses your existing logic from utils.py
    data = utils.get_master_stats_data()
    # Sort by points and return top 10
    sorted_players = sorted(data.values(), key=lambda x: x.get('Points', 0), reverse=True)
    return sorted_players[:10]

@app.get("/api/teams")
async def get_teams():
    config = utils.load_config()
    return config.get("team_ids", {})
