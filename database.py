import aiosqlite
import os
from typing import List, Optional, Tuple
import json
import numpy as np

DB_PATH = "ads.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ad_type TEXT NOT NULL CHECK(ad_type IN ('found', 'lost')),
                item_type TEXT NOT NULL,
                description TEXT,
                photo_file_id TEXT,
                location_key TEXT NOT NULL,
                place_detail TEXT,
                contact_type TEXT CHECK(contact_type IN ('drop', 'contact')),
                contact_info TEXT,
                embedding BLOB,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        # Индексы для быстрого поиска
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ads_status ON ads(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_ads_active_type_loc ON ads(ad_type, item_type, location_key) WHERE status = 'active'")
        await db.commit()

async def ensure_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def create_ad(
    user_id: int,
    ad_type: str,
    item_type: str,
    description: str,
    photo_file_id: Optional[str],
    location_key: str,
    place_detail: str,
    contact_type: str,
    contact_info: str,
    embedding: np.ndarray
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO ads (
                user_id, ad_type, item_type, description, photo_file_id,
                location_key, place_detail, contact_type, contact_info, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, ad_type, item_type, description, photo_file_id,
            location_key, place_detail, contact_type, contact_info, embedding.tobytes()
        ))
        await db.commit()
        return cursor.lastrowid

async def get_active_ads_by_type_and_location(
    item_type: str,
    location_key: Optional[str] = None
) -> List[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        if location_key:
            query = """
                SELECT id, user_id, ad_type, item_type, description, photo_file_id,
                       location_key, place_detail, contact_type, contact_info, embedding
                FROM ads
                WHERE status = 'active' AND item_type = ? AND location_key = ?
            """
            params = (item_type, location_key)
        else:
            query = """
                SELECT id, user_id, ad_type, item_type, description, photo_file_id,
                       location_key, place_detail, contact_type, contact_info, embedding
                FROM ads
                WHERE status = 'active' AND item_type = ?
            """
            params = (item_type,)
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return rows

async def get_user_ads(user_id: int, status: str = 'active') -> List[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, ad_type, item_type, description, location_key, place_detail,
                   contact_type, contact_info, status, created_at
            FROM ads
            WHERE user_id = ? AND status = ?
            ORDER BY created_at DESC
        """, (user_id, status))
        return await cursor.fetchall()

async def archive_ad(ad_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE ads SET status = 'archived'
            WHERE id = ? AND user_id = ?
        """, (ad_id, user_id))
        await db.commit()
        return cursor.rowcount > 0

async def get_ad_by_id(ad_id: int) -> Optional[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
        return await cursor.fetchone()

# Утилита: из BLOB → np.ndarray
def blob_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)