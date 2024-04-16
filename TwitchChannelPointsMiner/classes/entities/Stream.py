import logging
import time
from typing import Union, Optional


from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.constants import DROP_ID
from TwitchChannelPointsMiner.classes.entities.Game import Game
from TwitchChannelPointsMiner.classes.entities.LockedObject import LockedObject

logger = logging.getLogger(__name__)


class Stream(LockedObject):
    __slots__ = [
        "_id",
        "_title",
        "game",
        "tags",
        # "stream_up",
        "drops_tags",
        "campaigns",
        "campaigns_ids",
        "_viewers_count",
        "_viewcount_upd",
        "_spade_url",
        "watch_streak_missing",
        "_last_update",
        "online_at",
        "offline_at",
        "minute_watched",
        "_minute_watched_timestamp",
    ]

    def __init__(self):
        super().__init__()
        self._id: Optional[int] = None

        self._title: Optional[str] = None
        self.game: Game = Game()
        self.tags = []

        self.drops_tags = False
        self.campaigns = []
        self.campaigns_ids = []

        # self.stream_up = 0
        self.online_at = 0
        self.offline_at = 0

        self._viewers_count: int = 0
        self._viewcount_upd: int = 0

        self._last_update: float = 0

        self._spade_url: Optional[str] = None

        self.init_watch_streak()

    def __repr__(self):
        return f"Stream(title={self._title}, game={self.game}, tags={self.__str_tags()})"

    def __str__(self):
        return f"{self._title}" if Settings.logger.less else self.__repr__()

    @property
    def id(self) -> Optional[str]:
        if id := self._id:
            return str(id)
        return None

    @id.setter
    def id(self, id: Optional[Union[int, str]]):
        if id and (id :=int(id)):
            self._id = id
        else:
            self._id = None

    @property
    def title(self) -> Optional[str]:
        return self._title

    @title.setter
    def title(self, title: Optional[str]):
        if title and (title := title.strip()):
            self._title = title
        else:
            self._title = None

    @property
    def online(self) -> bool:
        return bool(self._spade_url)

    @property
    def spade_url(self) -> Optional[str]:
        return self._spade_url

    def update(self, id: Optional[Union[int, str]], title: Optional[str],
               game: Game, tags, viewers_count: Union[str, int]):

        with self:
            self.id = id
            self.title = title
            self.game = game

            # #343 temporary workaround
            self.tags = tags or []
            # ------------------------
            if viewers_count and (viewers_count:=int(viewers_count)):
                self._viewers_count = viewers_count
            else:
                self._viewers_count = 0

            self.drops_tags = (
                DROP_ID in [tag["id"] for tag in self.tags] and self.game != {}
            )
            self._last_update = time.time()

        logger.debug(f"Update: {self}")

    def __str_tags(self):
        return (
            None
            if self.tags == []
            else ", ".join([tag["localizedName"] for tag in self.tags])
        )

    # @property
    # def stream_up_elapsed(self):
    #     if stream_up := self.stream_up:
    #         return time.time() - stream_up
    #     return 0

    @property
    def viewcount_upd_elapsed(self):
        if viewcount_upd := self._viewcount_upd:
            return time.time() - viewcount_upd
        return 0

    @property
    def viewers_count(self):
        return self.viewers_count

    @viewers_count.setter
    def viewers_count(self, viewers: int):
        with self:
            self._viewers_count = viewers
            self._viewcount_upd = time.time()

    @property
    def viewcount_upd(self):
        return self._viewcount_upd

    @property
    def update_elapsed(self):
        if last_upd := self._last_update:
            return time.time() - last_upd
        return 0

    def init_watch_streak(self):
        with self:
            self.watch_streak_missing = True
            self.minute_watched = 0
            self._minute_watched_timestamp = 0

    def update_minute_watched(self):
        with self:
            if self._minute_watched_timestamp:
                self.minute_watched += round((time.time() - self._minute_watched_timestamp) / 60, 5)
            self._minute_watched_timestamp = time.time()
