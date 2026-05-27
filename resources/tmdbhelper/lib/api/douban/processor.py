# -*- coding: utf-8 -*-
"""
Background processor for Douban ratings.
"""

import threading
import time
import queue


class DoubanRatingProcessor:
    def __init__(self, api):
        self._api = api
        self._queue = queue.Queue()
        self._running = False
        self._thread = None

    def start(self):
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._process_queue, daemon=True)
            self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join()

    def add_to_queue(self, imdb_id=None, title=None, year=None, tmdb_type='movie'):
        self._queue.put({
            'imdb_id': imdb_id,
            'title': title,
            'year': year,
            'tmdb_type': tmdb_type
        })

    def _process_queue(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1)
                try:
                    if item.get('imdb_id'):
                        self._api.get_ratings(
                            imdb_id=item['imdb_id'],
                            tmdb_type=item.get('tmdb_type', 'movie')
                        )
                    elif item.get('title'):
                        self._api.get_ratings_by_title(
                            title=item['title'],
                            year=item.get('year'),
                            tmdb_type=item.get('tmdb_type', 'movie')
                        )
                except Exception:
                    pass
                self._queue.task_done()
                time.sleep(0.5)
            except queue.Empty:
                continue