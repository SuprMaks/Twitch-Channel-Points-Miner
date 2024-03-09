from locked_dict.locked_dict import LockedDict
from plum import dispatch
from typing import Union, Optional

from TwitchChannelPointsMiner.classes.entities.Singleton import Singleton
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer, StreamerSettings


class StreamerStorage(LockedDict, metaclass=Singleton):
    @dispatch
    def __call__(self, streamer: Streamer) -> Optional[Streamer]:
        if channel_id:=streamer.channel_id:
            with self:
                if channel_id not in self:
                    self[channel_id] = streamer
                return self[channel_id]
        return None

    @dispatch
    def __call__(self, channel_id: Union[str, int], username: str, display_name: str = '',
                 settings: StreamerSettings = StreamerSettings()) -> Optional[Streamer]:
        if channel_id and (channel_id:=int(channel_id)):
            return self.__call__(Streamer(channel_id, username, display_name, settings))
        return None
