# -*- coding: utf-8 -*-
"""
Douban rating API for TMDB Helper.
Based on kfstorm/douban-idatabase architecture.

Features:
- Multiple API sources (Rexxar, Legacy, Frodo)
- Rate limiting with random delay
- Local SQLite caching
- ID mapping (Douban ID <-> IMDb ID)
"""

import base64
import hashlib
import hmac
import json
import random
import time
from datetime import datetime
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

DOUBAN_REXXAR_API_URL = "https://m.douban.com/rexxar/api/v2/movie/{}"
LEGACY_IMDB_URL = "https://api.douban.com/v2/movie/imdb/{imdbid}"
LEGACY_API_KEY = "0ab215a8b1977939201640fa14c66bab"

FRODO_BASE_URL = "https://frodo.douban.com/api/v2"
FRODO_SEARCH_MOVIE_PATH = "/search/movie"
FRODO_SEARCH_TV_PATH = "/search/tv"
FRODO_API_KEY = "0dad551ec0f84ed02907ff5c42e8ec70"
FRODO_API_SECRET = "bf7dddc7c9cfe6f7"

FRODO_RATING_PROBABILITY = 0.3
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1

RATE_LIMIT_MIN_DELAY = 0.5
RATE_LIMIT_MAX_DELAY = 3.0

USER_AGENTS = [
    "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 product/Mate 40 vendor/HUAWEI model/Mate 40 brand/HUAWEI  rom/android  network/wifi  platform/AndroidPad",
    "api-client/1 com.douban.frodo/7.18.0(230) Android/22 product/MI 9 vendor/Xiaomi model/MI 9 brand/Android  rom/miui6  network/wifi  platform/mobile nd/1",
    "api-client/1 com.douban.frodo/7.1.0(205) Android/29 product/perseus vendor/Xiaomi model/Mi MIX 3  rom/miui6  network/wifi  platform/mobile nd/1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.3",
]
COOKIE_BID = "bid=J9zb1zA5sJc"

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.3",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://movie.douban.com/",
    "Origin": "https://movie.douban.com"
}


class _RateLimiter:
    _delays = {}

    @classmethod
    def wait(cls, host):
        delay = random.uniform(RATE_LIMIT_MIN_DELAY, RATE_LIMIT_MAX_DELAY)
        time.sleep(delay)


_rate_limiter = _RateLimiter()


def _frodo_sign(url, ts, method="GET"):
    path = urlparse(url).path
    raw = "&".join([method.upper(), quote(path, safe=""), ts])
    digest = hmac.new(
        FRODO_API_SECRET.encode(),
        raw.encode(),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode()


def _normalize_rating(r):
    if not r:
        return None, None, None
    average = r.get("average") or r.get("value")
    num_raters = r.get("numRaters") or r.get("count")
    douban_id = r.get("subject_id") or r.get("id")
    return average, num_raters, douban_id


def _make_request_with_retry(url, headers=None, data=None, method="GET"):
    for attempt in range(MAX_RETRIES):
        try:
            host = urlparse(url).netloc
            _rate_limiter.wait(host)
            req = Request(url, headers=headers or {}, data=data)
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
            else:
                raise


def _rexxar_api_lookup(douban_id):
    url = DOUBAN_REXXAR_API_URL.format(douban_id)
    headers = COMMON_HEADERS.copy()
    headers["User-Agent"] = random.choice(USER_AGENTS)
    data = _make_request_with_retry(url, headers=headers)
    return data


def _legacy_imdb_lookup(imdbid):
    url = LEGACY_IMDB_URL.format(imdbid=imdbid)
    post_data = urlencode({"apikey": LEGACY_API_KEY}).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        "User-Agent": random.choice(USER_AGENTS),
        "Cookie": COOKIE_BID,
    }
    data = _make_request_with_retry(url, headers=headers, data=post_data, method="POST")
    rating = data.get("rating") or {}
    avg, count, douban_id = _normalize_rating(rating)
    return {"average": avg, "numRaters": count, "douban_id": douban_id}


def _frodo_search(query, search_type='movie'):
    path = FRODO_SEARCH_MOVIE_PATH if search_type == 'movie' else FRODO_SEARCH_TV_PATH
    path = FRODO_BASE_URL + path
    ts = datetime.now().strftime("%Y%m%d")
    params = {
        "q": query,
        "count": "1",
        "apiKey": FRODO_API_KEY,
        "_ts": ts,
        "_sig": _frodo_sign(path, ts),
        "os_rom": "android",
    }
    url = path + "?" + urlencode(params)
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    data = _make_request_with_retry(url, headers=headers)
    return data


def _frodo_search_by_title(title, year=None, search_type='movie'):
    query = f"{title} {year}" if year else title
    data = _frodo_search(query, search_type)
    items = data.get("items") or []
    if not items:
        raise ValueError("Frodo search returned no results")
    first_item = items[0]
    subject = first_item.get("target") or first_item
    rating = subject.get("rating") or {}
    avg, count, douban_id = _normalize_rating(rating)
    return {"average": avg, "numRaters": count, "douban_id": douban_id}


def _frodo_search_by_imdb(imdbid, search_type='movie'):
    data = _frodo_search(imdbid, search_type)
    items = data.get("items") or []
    if not items:
        raise ValueError("Frodo search returned no results")
    first_item = items[0]
    subject = first_item.get("target") or first_item
    rating = subject.get("rating") or {}
    avg, count, douban_id = _normalize_rating(rating)
    return {"average": avg, "numRaters": count, "douban_id": douban_id}


class DoubanCache:
    def __init__(self):
        self._cache = None

    @property
    def cache(self):
        if self._cache is None:
            from tmdbhelper.lib.api.douban.cache import DoubanCacheDatabase
            self._cache = DoubanCacheDatabase()
        return self._cache

    def get_by_imdb(self, imdb_id):
        row = self.cache.get_cache_by_imdb(imdb_id)
        if row and row['rating']:
            return {
                "douban_id": row['douban_id'],
                "rating": row['rating'],
                "votes": row['votes'],
            }
        return None

    def get_by_douban(self, douban_id):
        row = self.cache.get_cache_by_douban(douban_id)
        if row and row['rating']:
            return {
                "douban_id": row['douban_id'],
                "rating": row['rating'],
                "votes": row['votes'],
                "imdb_id": row['imdb_id'],
            }
        return None

    def get_by_title(self, title, year=None):
        row = self.cache.get_cache_by_title(title, year)
        if row and row['rating']:
            return {
                "douban_id": row['douban_id'],
                "rating": row['rating'],
                "votes": row['votes'],
                "imdb_id": row['imdb_id'],
            }
        return None

    def save(self, douban_id, imdb_id=None, title=None, year=None, rating=None, votes=None):
        self.cache.set_cache(douban_id, imdb_id, title, year, rating, votes)

    def get_stats(self):
        return self.cache.get_stats()


class DoubanAPI:
    def __init__(self):
        self._cache = None
        self._refresh_probability = 0.05
        self._refresh_cooldown = 86400
        self._last_refresh = 0

    @property
    def cache(self):
        if self._cache is None:
            self._cache = DoubanCache()
        return self._cache

    def _can_refresh(self):
        current_time = time.time()
        if current_time - self._last_refresh < self._refresh_cooldown:
            return False
        if random.random() > self._refresh_probability:
            return False
        self._last_refresh = current_time
        return True

    def _async_refresh(self, imdb_id=None, title=None, year=None, search_type='movie'):
        if not self._can_refresh():
            return

        def do_refresh():
            try:
                if imdb_id:
                    self.get_ratings(imdb_id, search_type, force_refresh=True)
                elif title:
                    self.get_ratings_by_title(title, year, search_type, force_refresh=True)
            except Exception:
                pass

        import threading
        t = threading.Thread(target=do_refresh, daemon=True)
        t.start()

    def get_ratings(self, imdb_id, tmdb_type='movie', force_refresh=False):
        if not imdb_id or not (isinstance(imdb_id, str) and imdb_id.startswith("tt")):
            return {}
        search_type = 'movie' if tmdb_type == 'movie' else 'tv'
        cached = self.cache.get_by_imdb(imdb_id)
        if cached and not force_refresh:
            self._async_refresh(imdb_id, title=None, year=None, search_type=search_type)
            return {
                "douban_rating": int(cached['rating'] * 10),
                "douban_votes": cached['votes'],
                "douban_id": cached['douban_id'],
            }
        try:
            if random.random() < FRODO_RATING_PROBABILITY:
                try:
                    raw = _frodo_search_by_imdb(imdb_id, search_type)
                except Exception:
                    raw = _legacy_imdb_lookup(imdb_id)
            else:
                raw = _legacy_imdb_lookup(imdb_id)
        except Exception:
            if cached:
                return {
                    "douban_rating": int(cached['rating'] * 10),
                    "douban_votes": cached['votes'],
                    "douban_id": cached['douban_id'],
                }
            return {}
        return self._process_and_cache(raw, imdb_id=imdb_id, tmdb_type=tmdb_type)

    def get_ratings_by_douban_id(self, douban_id):
        if not douban_id:
            return {}
        cached = self.cache.get_by_douban(douban_id)
        if cached:
            return {
                "douban_rating": int(cached['rating'] * 10),
                "douban_votes": cached['votes'],
                "douban_id": cached['douban_id'],
            }
        try:
            data = _rexxar_api_lookup(douban_id)
            rating = data.get("rating") or {}
            avg, count, _ = _normalize_rating(rating)
            if avg is None:
                return {}
            douban_rating = int(round(float(avg) * 10))
            douban_votes = int(count) if count else 0
            self.cache.save(
                douban_id=douban_id,
                rating=float(avg),
                votes=douban_votes
            )
            return {
                "douban_rating": douban_rating,
                "douban_votes": douban_votes,
                "douban_id": douban_id,
            }
        except Exception:
            return {}

    def get_ratings_by_title(self, title, year=None, tmdb_type='movie', force_refresh=False):
        if not title:
            return {}
        search_type = 'movie' if tmdb_type == 'movie' else 'tv'
        cached = self.cache.get_by_title(title, year)
        if cached and not force_refresh:
            self._async_refresh(imdb_id=None, title=title, year=year, search_type=search_type)
            return {
                "douban_rating": int(cached['rating'] * 10),
                "douban_votes": cached['votes'],
                "douban_id": cached['douban_id'],
            }
        try:
            raw = _frodo_search_by_title(title, year, search_type)
        except Exception:
            if cached:
                return {
                    "douban_rating": int(cached['rating'] * 10),
                    "douban_votes": cached['votes'],
                    "douban_id": cached['douban_id'],
                }
            return {}
        return self._process_and_cache(raw, title=title, year=year, tmdb_type=tmdb_type)

    def _process_and_cache(self, raw, imdb_id=None, title=None, year=None, tmdb_type='movie'):
        average = raw.get("average")
        num_raters = raw.get("numRaters")
        douban_id = raw.get("douban_id")
        if average is None:
            return {}
        try:
            avg_float = float(average)
        except (TypeError, ValueError):
            return {}
        douban_rating = int(round(avg_float * 10))
        douban_votes = int(num_raters) if num_raters else 0
        if douban_id:
            self.cache.save(
                douban_id=douban_id,
                imdb_id=imdb_id,
                title=title,
                year=year,
                rating=avg_float,
                votes=douban_votes,
                tmdb_type=tmdb_type
            )
        return {
            "douban_rating": douban_rating,
            "douban_votes": douban_votes,
            "douban_id": douban_id,
        }

    def get_batch_ratings(self, items, max_concurrent=5):
        import asyncio
        import aiohttp

        async def async_request(url, headers=None):
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=REQUEST_TIMEOUT) as resp:
                    return await resp.json()

        async def fetch_one(key, item):
            if item.get('imdb_id'):
                return key, self.get_ratings(item['imdb_id'], item.get('tmdb_type', 'movie'))
            elif item.get('title') and item.get('year'):
                return key, self.get_ratings_by_title(item['title'], item['year'], item.get('tmdb_type', 'movie'))
            return key, {}

        async def fetch_all():
            semaphore = asyncio.Semaphore(max_concurrent)

            async def sem_task(key, item):
                async with semaphore:
                    return await fetch_one(key, item)

            tasks = [sem_task(key, item) for key, item in items.items()]
            return await asyncio.gather(*tasks)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(fetch_all())
        return dict(results)

    def get_stats(self):
        return self.cache.get_stats()