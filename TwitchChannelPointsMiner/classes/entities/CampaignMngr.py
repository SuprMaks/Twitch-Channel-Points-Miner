from locked_dict.locked_dict import LockedDict
from plum import dispatch
from logging import getLogger
from typing import Optional

from TwitchChannelPointsMiner.classes.entities.Singleton import Singleton
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign

logger = getLogger(__name__)


class CampaignMngr(LockedDict, metaclass=Singleton):
    @dispatch
    def __call__(self, other: Campaign) -> Campaign:
        with self:
            if other.id not in self:
                self[other.id] = other
            elif other.name != (curr:=self[other.id]).name:
                logger.error(f"Existing campaign {curr} with different name than new {other}")
        return self[other.id]

    @dispatch
    def __call__(self, other: dict) -> Optional[Campaign]:
        if all(k in other for k in ('id', 'name')):
            return self.__call__(Campaign(other))
        return None
