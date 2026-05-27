# -*- coding: utf-8 -*-
from tmdbhelper.lib.files.dbdata import DatabaseCore, DatabaseMethod

DATABASE_NAME = 'database_08'

CACHE_EXPIRE_DAYS_MOVIE = 30
CACHE_EXPIRE_DAYS_TV = 30
CACHE_EXPIRE_DAYS_HOT = 15


class DoubanCacheDatabase(DatabaseCore, DatabaseMethod):
    database_version = 1
    database_changes = {}
    _basefolder = 'special://temp/tmdbhelper/'
    _fileutils = None

    @property
    def database_tables(self):
        return {
            'douban_cache': self.douban_cache_columns,
            'douban_queue': self.douban_queue_columns,
        }

    @property
    def douban_cache_columns(self):
        return {
            'douban_id': {
                'data': 'TEXT PRIMARY KEY',
                'indexed': False,
            },
            'imdb_id': {
                'data': 'TEXT',
                'indexed': True,
            },
            'title': {
                'data': 'TEXT',
                'indexed': False,
            },
            'year': {
                'data': 'INTEGER',
                'indexed': True,
            },
            'rating': {
                'data': 'REAL',
                'indexed': False,
            },
            'votes': {
                'data': 'INTEGER',
                'indexed': False,
            },
            'tmdb_type': {
                'data': 'TEXT DEFAULT "movie"',
                'indexed': True,
            },
            'update_time': {
                'data': 'INTEGER',
                'indexed': False,
            },
            'expiry': {
                'data': 'INTEGER',
                'indexed': True,
            },
        }

    @property
    def douban_queue_columns(self):
        return {
            'item_id': {
                'data': 'TEXT PRIMARY KEY',
                'indexed': False,
            },
            'query_type': {
                'data': 'TEXT',
                'indexed': True,
            },
            'query_value': {
                'data': 'TEXT',
                'indexed': False,
            },
            'priority': {
                'data': 'INTEGER DEFAULT 0',
                'indexed': True,
            },
            'add_time': {
                'data': 'INTEGER',
                'indexed': False,
            },
        }

    def __init__(self):
        from tmdbhelper.lib.files.futils import FileUtils
        self._fileutils = FileUtils()
        super().__init__(folder=DATABASE_NAME, filename='douban_cache.db')

    @staticmethod
    def get_current_timestamp():
        from tmdbhelper.lib.addon.tmdate import set_timestamp
        return set_timestamp(0, set_int=True)

    def _get_expiry_seconds(self, votes, tmdb_type):
        days = self._get_expiry_days(votes, tmdb_type)
        return days * 86400

    def _get_expiry_days(self, votes, tmdb_type):
        if tmdb_type == 'tv':
            return CACHE_EXPIRE_DAYS_TV
        if votes and votes > 10000:
            return CACHE_EXPIRE_DAYS_HOT
        return CACHE_EXPIRE_DAYS_MOVIE

    def is_expired(self, expiry):
        return self.get_current_timestamp() >= expiry

    def get_cache_by_imdb(self, imdb_id, tmdb_type='movie'):
        if not imdb_id:
            return None
        current_time = self.get_current_timestamp()
        cursor = self.execute_sql(
            'SELECT * FROM douban_cache WHERE imdb_id=? AND tmdb_type=? AND expiry>? LIMIT 1',
            data=(imdb_id, tmdb_type, current_time),
            read_only=True)
        if cursor:
            return cursor.fetchone()

    def get_cache_by_douban(self, douban_id):
        if not douban_id:
            return None
        current_time = self.get_current_timestamp()
        cursor = self.execute_sql(
            'SELECT * FROM douban_cache WHERE douban_id=? AND expiry>? LIMIT 1',
            data=(douban_id, current_time),
            read_only=True)
        if cursor:
            return cursor.fetchone()

    def get_cache_by_title(self, title, year=None, tmdb_type='movie'):
        if not title:
            return None
        current_time = self.get_current_timestamp()
        if year:
            cursor = self.execute_sql(
                'SELECT * FROM douban_cache WHERE title=? AND year=? AND tmdb_type=? AND expiry>? LIMIT 1',
                data=(title, year, tmdb_type, current_time),
                read_only=True)
        else:
            cursor = self.execute_sql(
                'SELECT * FROM douban_cache WHERE title=? AND tmdb_type=? AND expiry>? LIMIT 1',
                data=(title, tmdb_type, current_time),
                read_only=True)
        if cursor:
            return cursor.fetchone()

    def set_cache(self, douban_id, imdb_id=None, title=None, year=None, rating=None, votes=None, tmdb_type='movie'):
        current_time = self.get_current_timestamp()
        expiry_seconds = self._get_expiry_seconds(votes, tmdb_type)
        expiry = current_time + expiry_seconds
        self.execute_sql(
            '''INSERT OR REPLACE INTO douban_cache
               (douban_id, imdb_id, title, year, rating, votes, tmdb_type, update_time, expiry)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            data=(douban_id, imdb_id, title, year, rating, votes, tmdb_type, current_time, expiry))

    def add_to_queue(self, item_id, query_type, query_value, priority=0):
        current_time = self.get_current_timestamp()
        self.execute_sql(
            '''INSERT OR IGNORE INTO douban_queue
               (item_id, query_type, query_value, priority, add_time)
               VALUES (?, ?, ?, ?, ?)''',
            data=(item_id, query_type, query_value, priority, current_time))

    def get_from_queue(self, limit=10):
        cursor = self.execute_sql(
            'SELECT * FROM douban_queue ORDER BY priority DESC, add_time ASC LIMIT ?',
            data=(limit,),
            read_only=True)
        if cursor:
            return cursor.fetchall()

    def remove_from_queue(self, item_id):
        self.execute_sql(
            'DELETE FROM douban_queue WHERE item_id=?',
            data=(item_id,))

    def get_queue_count(self):
        cursor = self.execute_sql(
            'SELECT COUNT(*) FROM douban_queue',
            read_only=True)
        if cursor:
            return cursor.fetchone()[0]
        return 0

    def clear_expired_cache(self):
        current_time = self.get_current_timestamp()
        self.execute_sql(
            'DELETE FROM douban_cache WHERE expiry<?',
            data=(current_time,))

    def get_stats(self):
        current_time = self.get_current_timestamp()
        cursor = self.execute_sql(
            'SELECT COUNT(*) FROM douban_cache WHERE expiry>?',
            data=(current_time,),
            read_only=True)
        cached_count = cursor.fetchone()[0] if cursor else 0
        queue_count = self.get_queue_count()
        return {
            'cached_count': cached_count,
            'queue_count': queue_count,
        }