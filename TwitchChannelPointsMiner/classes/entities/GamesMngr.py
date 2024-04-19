from logging import getLogger
from locked_dict.locked_dict import LockedDict
from plum import dispatch

from TwitchChannelPointsMiner.classes.entities.Game import Game
from TwitchChannelPointsMiner.classes.entities.Singleton import Singleton

logger = getLogger(__name__)


class GamesMngr(LockedDict, metaclass=Singleton):

    @dispatch
    def __init__(self, game: Game):
        super(GamesMngr, self).__init__()
        self.__call__(game)

    @dispatch
    def __init__(self, mapping=(), **kwargs):
        super().__init__(mapping, **kwargs)

    @dispatch
    def __iadd__(self, other: Game):
        self.__call__(other)
        return self

    @dispatch
    def __call__(self, other: Game) -> Game:
        with self:
            if other.id not in self:
                self[other.id] = other
            elif other.name != (curr_game := self[other.id]).name:
                logger.error(f"Existing game {curr_game} with different name than new {other}")
        return self[other.id]

    @dispatch
    def __call__(self, other: dict) -> Game:
        if all(k in other for k in ('id', 'name')):
            return self.__call__(Game(other['id'],
                                      other['name'],
                                      other['displayName'] if 'displayName' in other else None))
        return Game()


