from jurialmunkey.ftools import cached_property
from tmdbhelper.lib.sync.providers.base import SyncProvider
from tmdbhelper.lib.sync.providers.douban.ratings import DoubanRatingsSupplier


class Provider(SyncProvider):
    interface_version = 4
    provider_id = 'douban'
    display_name = 'Douban'
    addon_id = 'plugin.video.themoviedb.helper'
    ratings_classes = {
        'movie': DoubanRatingsSupplier,
        'tvshow': DoubanRatingsSupplier,
    }

    @cached_property
    def api(self):
        return self.get_api()

    def get_api(self):
        from tmdbhelper.lib.api.douban.api import DoubanAPI
        return DoubanAPI()

    def is_authorized(self):
        return True
