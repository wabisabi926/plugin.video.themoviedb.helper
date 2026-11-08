from tmdbhelper.lib.sync.providers.ratings import RatingsSupplier


class DoubanRatingsSupplier(RatingsSupplier):
    def get_ratings(self):
        return self.provider.api.get_ratings(imdb_id=self.imdb_id) or {}
