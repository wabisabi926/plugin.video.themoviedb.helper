# -*- coding: utf-8 -*-
"""
SQLite cache database for Douban ratings.
"""

import os
import sqlite3
from datetime import datetime, timedelta

CACHE_EXPIRE_DAYS_MOVIE = 7
CACHE_EXPIRE_DAYS_TV = 14
CACHE_EXPIRE_DAYS_HOT = 3


class DoubanCacheDatabase:
    def __init__(self):
        from tmdbhelper.lib.files.futils import get_addon_data_path
        self.db_path = os.path.join(get_addon_data_path(), "douban_cache.db")
        self._conn = None
        self._ensure_tables()

    @property
    def conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS douban_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                douban_id TEXT NOT NULL,
                imdb_id TEXT,
                title TEXT,
                year INTEGER,
                rating REAL,
                votes INTEGER,
                tmdb_type TEXT DEFAULT 'movie',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(douban_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_douban_cache_imdb_id ON douban_cache(imdb_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_douban_cache_title ON douban_cache(title)
        """)
        self.conn.commit()

    def _get_expiry_time(self, rating_count, tmdb_type):
        if tmdb_type == 'tv':
            days = CACHE_EXPIRE_DAYS_TV
        elif rating_count and rating_count > 10000:
            days = CACHE_EXPIRE_DAYS_HOT
        else:
            days = CACHE_EXPIRE_DAYS_MOVIE
        return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    def get_cache_by_imdb(self, imdb_id):
        cursor = self.conn.cursor()
        expiry = self._get_expiry_time(None, 'movie')
        cursor.execute("""
            SELECT * FROM douban_cache 
            WHERE imdb_id = ? AND updated_at >= ?
            ORDER BY updated_at DESC LIMIT 1
        """, (imdb_id, expiry))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_cache_by_douban(self, douban_id):
        cursor = self.conn.cursor()
        expiry = self._get_expiry_time(None, 'movie')
        cursor.execute("""
            SELECT * FROM douban_cache 
            WHERE douban_id = ? AND updated_at >= ?
            ORDER BY updated_at DESC LIMIT 1
        """, (douban_id, expiry))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_cache_by_title(self, title, year=None):
        cursor = self.conn.cursor()
        expiry = self._get_expiry_time(None, 'movie')
        if year:
            cursor.execute("""
                SELECT * FROM douban_cache 
                WHERE title = ? AND year = ? AND updated_at >= ?
                ORDER BY updated_at DESC LIMIT 1
            """, (title, year, expiry))
        else:
            cursor.execute("""
                SELECT * FROM douban_cache 
                WHERE title = ? AND updated_at >= ?
                ORDER BY updated_at DESC LIMIT 1
            """, (title, expiry))
        row = cursor.fetchone()
        return dict(row) if row else None

    def set_cache(self, douban_id, imdb_id=None, title=None, year=None, rating=None, votes=None):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO douban_cache 
            (douban_id, imdb_id, title, year, rating, votes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (douban_id, imdb_id, title, year, rating, votes))
        self.conn.commit()

    def get_stats(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM douban_cache")
        count = cursor.fetchone()[0]
        return {"cached_count": count}

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None