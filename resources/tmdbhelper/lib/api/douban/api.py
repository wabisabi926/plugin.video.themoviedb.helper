# -*- coding: utf-8 -*-
"""
Douban rating API for TMDB Helper.
Based on kfstorm/douban-idatabase architecture.

Features:
- Multiple API sources (Rexxar, Legacy, Frodo, Mobile Web)
- Rate limiting with random delay
- Local SQLite caching
- ID mapping (Douban ID <-> IMDb ID)
- Enhanced anti-blocking measures
"""

import base64
import hashlib
import hmac
import json
import random
import time
import uuid
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

MOBILE_WEB_SEARCH_URL = "https://m.douban.com/rexxar/api/v2/search/weixin?q={query}&count=1"

FRODO_RATING_PROBABILITY = 0.3
REQUEST_TIMEOUT = 15
MAX_RETRIES = 5
RETRY_BASE_DELAY = 2

RATE_LIMIT_MIN_DELAY = 1.0
RATE_LIMIT_MAX_DELAY = 4.0

USER_AGENTS = [
    "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 product/Mate 40 vendor/HUAWEI model/Mate 40 brand/HUAWEI  rom/android  network/wifi  platform/AndroidPad",
    "api-client/1 com.douban.frodo/7.18.0(230) Android/22 product/MI 9 vendor/Xiaomi model/MI 9 brand/Android  rom/miui6  network/wifi  platform/mobile nd/1",
    "api-client/1 com.douban.frodo/7.1.0(205) Android/29 product/perseus vendor/Xiaomi model/Mi MIX 3  rom/miui6  network/wifi  platform/mobile nd/1",
    "api-client/1 com.douban.frodo/7.25.0(234) Android/30 product/OnePlus8 vendor/OnePlus model/OnePlus8 brand/OnePlus  rom/android  network/wifi  platform/mobile nd/1",
    "api-client/1 com.douban.frodo/7.20.0(228) Android/28 product/Pixel 4 vendor/Google model/Pixel 4 brand/Google  rom/android  network/wifi  platform/mobile nd/1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.3",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.184 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
]

COOKIES = [
    "bid=J9zb1zA5sJc",
    "bid=xy3z8k7L0Md",
    "bid=abc123DEF456",
    "bid=789ghiJKL012",
    "bid=MNOP345qrstu",
]

COMMON_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://movie.douban.com/",
    "Origin": "https://movie.douban.com",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

MOBILE_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": "https://m.douban.com/",
    "X-Requested-With": "XMLHttpRequest",
}


def _generate_bid():
    return "bid=" + str(uuid.uuid4()).replace("-", "")[:11]


def _get_random_user_agent():
    return random.choice(USER_AGENTS)


def _get_random_cookie():
    return random.choice(COOKIES)


class _RateLimiter:
    _delays = {}
    _last_request = {}

    @classmethod
    def wait(cls, host):
        now = time.time()
        last_req = cls._last_request.get(host, 0)
        min_interval = random.uniform(RATE_LIMIT_MIN_DELAY, RATE_LIMIT_MAX_DELAY)
        elapsed = now - last_req
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        cls._last_request[host] = time.time()


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
    average = r.get("average") or r.get("value") or r.get("rating")
    num_raters = r.get("numRaters") or r.get("count") or r.get("votes")
    douban_id = r.get("subject_id") or r.get("id")
    if isinstance(douban_id, int):
        douban_id = str(douban_id)
    return average, num_raters, douban_id


def _make_request_with_retry(url, headers=None, data=None, method="GET"):
    for attempt in range(MAX_RETRIES):
        try:
            host = urlparse(url).netloc
            _rate_limiter.wait(host)
            req = Request(url, headers=headers or {}, data=data, method=method)
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                content_encoding = resp.headers.get("Content-Encoding", "")
                content = resp.read()
                if "gzip" in content_encoding:
                    import gzip
                    content = gzip.decompress(content)
                elif "deflate" in content_encoding:
                    import zlib
                    content = zlib.decompress(content)
                return json.loads(content.decode("utf-8"))
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(delay)
            else:
                raise


def _rexxar_api_lookup(douban_id):
    url = DOUBAN_REXXAR_API_URL.format(douban_id)
    headers = COMMON_HEADERS.copy()
    headers["User-Agent"] = _get_random_user_agent()
    headers["Cookie"] = _get_random_cookie()
    data = _make_request_with_retry(url, headers=headers)
    return data


def _legacy_imdb_lookup(imdbid):
    url = LEGACY_IMDB_URL.format(imdbid=imdbid)
    post_data = urlencode({"apikey": LEGACY_API_KEY}).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        "User-Agent": _get_random_user_agent(),
        "Cookie": _get_random_cookie(),
        "Accept": "application/json",
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
    headers = {
        "User-Agent": _get_random_user_agent(),
        "Cookie": _get_random_cookie(),
        "Accept": "application/json",
    }
    data = _make_request_with_retry(url, headers=headers)
    return data


def _mobile_web_search(query):
    url = MOBILE_WEB_SEARCH_URL.format(query=quote(query))
    headers = MOBILE_HEADERS.copy()
    headers["User-Agent"] = _get_random_user_agent()
    headers["Cookie"] = _get_random_cookie()
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


def _mobile_search_by_imdb(imdbid):
    data = _mobile_web_search(imdbid)
    items = data.get("items") or []
    if not items:
        raise ValueError("Mobile search returned no results")
    first_item = items[0]
    subject = first_item.get("subject") or first_item
    rating = subject.get("rating") or {}
    avg, count, douban_id = _normalize_rating(rating)
    return {"average": avg, "numRaters": count, "douban_id": douban_id}


def _fallback_search(imdbid, search_type='movie'):
    methods = [
        lambda: _frodo_search_by_imdb(imdbid, search_type),
        lambda: _legacy_imdb_lookup(imdbid),
        lambda: _mobile_search_by_imdb(imdbid),
    ]
    for i, method in enumerate(methods):
        try:
            return method()
        except Exception as e:
            if i < len(methods) - 1:
                time.sleep(random.uniform(1, 2))
                continue
            raise


class DoubanCache:
    def __init__(self):
        self._cache = None

    @property
    def cache(self):
        if self._cache is None:
            from tmdbhelper.lib.api.douban.cache import DoubanCacheDatabase
            self._cache = DoubanCacheDatabase()
        return self._cache

    def get_by_imdb(self, imdb_id, tmdb_type='movie'):
        row = self.cache.get_cache_by_imdb(imdb_id, tmdb_type)
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

    def get_by_title(self, title, year=None, tmdb_type='movie'):
        row = self.cache.get_cache_by_title(title, year, tmdb_type)
        if row and row['rating']:
            return {
                "douban_id": row['douban_id'],
                "rating": row['rating'],
                "votes": row['votes'],
                "imdb_id": row['imdb_id'],
            }
        return None

    def save(self, douban_id, imdb_id=None, title=None, year=None, rating=None, votes=None, tmdb_type='movie'):
        self.cache.set_cache(douban_id, imdb_id, title, year, rating, votes, tmdb_type)

    def get_stats(self):
        return self.cache.get_stats()


class DoubanAPI:
    def __init__(self):
        self._cache = None
        self._refresh_probability = 0.05
        self._refresh_cooldown = 86400
        self._last_refresh = 0
        self._consecutive_failures = 0
        self._failure_cooldown = 0

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
        if current_time < self._failure_cooldown:
            return False
        self._last_refresh = current_time
        return True

    def _async_refresh(self, imdb_id=None, title=None, year=None, tmdb_type='movie'):
        if not self._can_refresh():
            return

        def do_refresh():
            try:
                if imdb_id:
                    self.get_ratings(imdb_id, tmdb_type, force_refresh=True)
                elif title:
                    self.get_ratings_by_title(title, year, tmdb_type, force_refresh=True)
            except Exception:
                pass

        import threading
        t = threading.Thread(target=do_refresh, daemon=True)
        t.start()

    def get_ratings(self, imdb_id, tmdb_type='movie', force_refresh=False):
        if not imdb_id or not (isinstance(imdb_id, str) and imdb_id.startswith("tt")):
            return {}
        search_type = 'movie' if tmdb_type == 'movie' else 'tv'
        cached = self.cache.get_by_imdb(imdb_id, tmdb_type)
        if cached and not force_refresh:
            self._async_refresh(imdb_id, title=None, year=None, tmdb_type=tmdb_type)
            return {
                "douban_rating": int(cached['rating'] * 10),
                "douban_votes": cached['votes'],
                "douban_id": cached['douban_id'],
            }
        try:
            raw = _fallback_search(imdb_id, search_type)
            self._consecutive_failures = 0
            self._failure_cooldown = 0
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._failure_cooldown = time.time() + 3600
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
                votes=douban_votes,
                tmdb_type='movie'
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
        cached = self.cache.get_by_title(title, year, tmdb_type)
        if cached and not force_refresh:
            self._async_refresh(imdb_id=None, title=title, year=year, tmdb_type=tmdb_type)
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

    def get_batch_ratings(self, items):
        results = {}
        for key, item in items.items():
            if item.get('imdb_id'):
                results[key] = self.get_ratings(item['imdb_id'], item.get('tmdb_type', 'movie'))
            elif item.get('title') and item.get('year'):
                results[key] = self.get_ratings_by_title(item['title'], item['year'], item.get('tmdb_type', 'movie'))
            else:
                results[key] = {}
            time.sleep(random.uniform(0.5, 1.5))
        return results

    def get_stats(self):
        return self.cache.get_stats()