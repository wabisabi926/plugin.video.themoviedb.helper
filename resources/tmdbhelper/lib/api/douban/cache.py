# -*- coding: utf-8 -*-
"""
SQLite cache database for Douban ratings.
"""

import os
import sqlite3
from datetime import datetime, timedelta

CACHE_EXPIRE_DAYS_MOVIE = 30
CACHE_EXPIRE_DAYS_TV = 30
CACHE_EXPIRE_DAYS_HOT = 15


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
                expiry_at TIMESTAMP,
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

    def _get_expiry_days(self, votes, tmdb_type):
        """根据评分数量和类型计算缓存过期天数"""
        if tmdb_type == 'tv':
            return CACHE_EXPIRE_DAYS_TV
        if votes and votes > 10000:
            return CACHE_EXPIRE_DAYS_HOT
        return CACHE_EXPIRE_DAYS_MOVIE

    def _get_expiry_at(self, votes, tmdb_type):
        """计算缓存过期时间点"""
        days = self._get_expiry_days(votes, tmdb_type)
        return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    def get_cache_by_imdb(self, imdb_id, tmdb_type='movie'):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM douban_cache 
            WHERE imdb_id = ? AND tmdb_type = ? AND expiry_at > CURRENT_TIMESTAMP
            ORDER BY updated_at DESC LIMIT 1
        """, (imdb_id, tmdb_type))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_cache_by_douban(self, douban_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM douban_cache 
            WHERE douban_id = ? AND expiry_at > CURRENT_TIMESTAMP
            ORDER BY updated_at DESC LIMIT 1
        """, (douban_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_cache_by_title(self, title, year=None, tmdb_type='movie'):
        cursor = self.conn.cursor()
        if year:
            cursor.execute("""
                SELECT * FROM douban_cache 
                WHERE title = ? AND year = ? AND tmdb_type = ? AND expiry_at > CURRENT_TIMESTAMP
                ORDER BY updated_at DESC LIMIT 1
            """, (title, year, tmdb_type))
        else:
            cursor.execute("""
                SELECT * FROM douban_cache 
                WHERE title = ? AND tmdb_type = ? AND expiry_at > CURRENT_TIMESTAMP
                ORDER BY updated_at DESC LIMIT 1
            """, (title, tmdb_type))
        row = cursor.fetchone()
        return dict(row) if row else None

    def set_cache(self, douban_id, imdb_id=None, title=None, year=None, rating=None, votes=None, tmdb_type='movie'):
        expiry_at = self._get_expiry_at(votes, tmdb_type)
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO douban_cache 
            (douban_id, imdb_id, title, year, rating, votes, tmdb_type, expiry_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (douban_id, imdb_id, title, year, rating, votes, tmdb_type, expiry_at))
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