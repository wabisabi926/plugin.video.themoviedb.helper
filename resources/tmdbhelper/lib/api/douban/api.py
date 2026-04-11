# -*- coding: utf-8 -*-
"""
Douban rating API for TMDB Helper.
Fetches movie rating by IMDb ID via Legacy or Frodo API (load balanced).
Returns letterboxd_rating / letterboxd_votes for drop-in replacement in skins.
"""

import base64
import hashlib
import hmac
import json
import random
from datetime import datetime
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

# --- Legacy API (api.douban.com/v2) ---
LEGACY_IMDB_URL = "https://api.douban.com/v2/movie/imdb/{imdbid}"
LEGACY_API_KEY = "0ab215a8b1977939201640fa14c66bab"

# --- Frodo API (frodo.douban.com/api/v2) ---
FRODO_BASE_URL = "https://frodo.douban.com/api/v2"
FRODO_SEARCH_PATH = "/search/movie"
FRODO_API_KEY = "0dad551ec0f84ed02907ff5c42e8ec70"
FRODO_API_SECRET = "bf7dddc7c9cfe6f7"

FRODO_RATING_PROBABILITY = 0.5
REQUEST_TIMEOUT = 10

USER_AGENTS = [
    "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 product/Mate 40 vendor/HUAWEI model/Mate 40 brand/HUAWEI  rom/android  network/wifi  platform/AndroidPad",
    "api-client/1 com.douban.frodo/7.18.0(230) Android/22 product/MI 9 vendor/Xiaomi model/MI 9 brand/Android  rom/miui6  network/wifi  platform/mobile nd/1",
    "api-client/1 com.douban.frodo/7.1.0(205) Android/29 product/perseus vendor/Xiaomi model/Mi MIX 3  rom/miui6  network/wifi  platform/mobile nd/1",
    "api-client/1 com.douban.frodo/7.3.0(207) Android/22 product/MI 9 vendor/Xiaomi model/MI 9 brand/Android  rom/miui6  network/wifi platform/mobile nd/1",
]
COOKIE_BID = "bid=J9zb1zA5sJc"


def _frodo_sign(url, ts, method="GET"):
    """Frodo API signature (HMAC-SHA1 of method & path & ts, then base64)."""
    path = urlparse(url).path
    raw = "&".join([method.upper(), quote(path, safe=""), ts])
    digest = hmac.new(
        FRODO_API_SECRET.encode(),
        raw.encode(),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode()


def _normalize_rating(r):
    """Return (average, numRaters) from either legacy or Frodo rating dict."""
    if not r:
        return None, None
    average = r.get("average") or r.get("value")
    num_raters = r.get("numRaters") or r.get("count")
    return average, num_raters


def _legacy_imdb_lookup(imdbid):
    """Path A: Resolve IMDb id via legacy API (POST)."""
    url = LEGACY_IMDB_URL.format(imdbid=imdbid)
    post_data = urlencode({"apikey": LEGACY_API_KEY}).encode("utf-8")
    req = Request(
        url,
        data=post_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": random.choice(USER_AGENTS),
            "Cookie": COOKIE_BID,
        },
        method="POST",
    )
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rating = data.get("rating") or {}
    avg, count = _normalize_rating(rating)
    return {"average": avg, "numRaters": count}


def _frodo_search_by_imdb(imdbid):
    """Path B: Search by IMDb id via Frodo API (GET)."""
    path = FRODO_BASE_URL + FRODO_SEARCH_PATH
    ts = datetime.now().strftime("%Y%m%d")
    params = {
        "q": imdbid,
        "count": "1",
        "apiKey": FRODO_API_KEY,
        "_ts": ts,
        "_sig": _frodo_sign(path, ts),
        "os_rom": "android",
    }
    url = path + "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": random.choice(USER_AGENTS)})
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = data.get("items") or []
    if not items:
        raise ValueError("Frodo search returned no results")
    first_item = items[0]
    subject = first_item.get("target") or first_item
    rating = subject.get("rating") or {}
    avg, count = _normalize_rating(rating)
    return {"average": avg, "numRaters": count}


class DoubanAPI(object):
    """
    Fetches Douban rating by IMDb ID. Returns douban_rating / douban_votes
    """

    def get_ratings(self, imdb_id):
        """
        Get rating for a movie by IMDb ID.
        Returns dict with douban_rating (0-100 int) and douban_votes (int),
        or {} on failure.
        """
        if not imdb_id or not (isinstance(imdb_id, str) and imdb_id.startswith("tt")):
            return {}
        try:
            if random.random() < FRODO_RATING_PROBABILITY:
                try:
                    raw = _frodo_search_by_imdb(imdb_id)
                except Exception:
                    raw = _legacy_imdb_lookup(imdb_id)
            else:
                raw = _legacy_imdb_lookup(imdb_id)
        except Exception:
            return {}
        average = raw.get("average")
        num_raters = raw.get("numRaters")
        if average is None:
            return {}
        try:
            avg_float = float(average)
        except (TypeError, ValueError):
            return {}
        # Store as 0-100 scale (same as IMDB/Trakt) for /10 display
        douban_rating = int(round(avg_float * 10))
        douban_votes = int(num_raters) if num_raters is not None else 0
        return {
            "douban_rating": douban_rating,
            "douban_votes": douban_votes,
        }
