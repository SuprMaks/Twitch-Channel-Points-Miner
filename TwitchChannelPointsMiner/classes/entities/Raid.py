from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer


class Raid(object):
    __slots__ = ["id", "viewer_count", "target_streamer"]

    def __init__(self, raid_id: str, viewer_count: int, target_streamer: Streamer):
        self.id: str = raid_id
        self.viewer_count = viewer_count
        self.target_streamer: Streamer = target_streamer

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.id == other.id
        else:
            return False

    def __repr__(self):
        return f"Raid to {self.target_streamer}"
