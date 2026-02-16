"""Waitlist backend for the landing page.

Run with: uvicorn server:app --reload --port 8000
"""

import os
import re
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "waitlist.db"

app = FastAPI(title="Waitlist API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WaitlistRequest(BaseModel):
    email: str


class WaitlistResponse(BaseModel):
    success: bool
    message: str


class CountResponse(BaseModel):
    count: int


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    return db


@app.on_event("startup")
async def startup():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await get_db()
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS waitlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.commit()
    finally:
        await db.close()


@app.post("/api/waitlist", response_model=WaitlistResponse)
async def join_waitlist(req: WaitlistRequest):
    email = req.email.strip().lower()

    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Invalid email format")

    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO waitlist (email, created_at) VALUES (?, ?)",
            (email, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
    finally:
        await db.close()

    return WaitlistResponse(success=True, message="You're on the list!")


@app.get("/api/waitlist/count", response_model=CountResponse)
async def waitlist_count():
    db = await get_db()
    try:
        async with db.execute("SELECT COUNT(*) FROM waitlist") as cursor:
            row = await cursor.fetchone()
            return CountResponse(count=row[0])
    finally:
        await db.close()
