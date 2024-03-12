import json
import logging
import os
import time
from datetime import datetime
from plum import dispatch
from typing import Union, Optional
from locked_dict.locked_dict import LockedDict


from TwitchChannelPointsMiner.classes.Chat import ChatPresence, ThreadChat
from TwitchChannelPointsMiner.classes.entities.Bet import BetSettings, DelayMode
from TwitchChannelPointsMiner.classes.entities.Stream import Stream
from TwitchChannelPointsMiner.classes.Settings import Events, Settings
from TwitchChannelPointsMiner.constants import URL
from TwitchChannelPointsMiner.utils import _millify
from TwitchChannelPointsMiner.classes.entities.LockedObject import LockedObject

logger = logging.getLogger(__name__)


class StreamerSettings(object):
    __slots__ = [
        "make_predictions",
        "follow_raid",
        "claim_drops",
        "claim_moments",
        "watch_streak",
        "bet",
        "chat",
    ]

    def __init__(
        self,
        make_predictions: bool = None,
        follow_raid: bool = None,
        claim_drops: bool = None,
        claim_moments: bool = None,
        watch_streak: bool = None,
        bet: BetSettings = None,
        chat: ChatPresence = None,
    ):
        self.make_predictions = make_predictions
        self.follow_raid = follow_raid
        self.claim_drops = claim_drops
        self.claim_moments = claim_moments
        self.watch_streak = watch_streak
        self.bet = bet
        self.chat = chat

    def default(self):
        for name in [
            "make_predictions",
            "follow_raid",
            "claim_drops",
            "claim_moments",
            "watch_streak",
        ]:
            if getattr(self, name) is None:
                setattr(self, name, True)
        if self.bet is None:
            self.bet = BetSettings()
        if self.chat is None:
            self.chat = ChatPresence.ONLINE

    def __repr__(self):
        return f"BetSettings(make_predictions={self.make_predictions}, follow_raid={self.follow_raid}, "\
               "claim_drops={self.claim_drops}, claim_moments={self.claim_moments}, watch_streak={self.watch_streak}, "\
               "bet={self.bet}, chat={self.chat})"


class Streamer(LockedObject):
    __slots__ = [
        "_username",
        "_channel_id",
        "_display_name",
        "settings",

        # "_online",
        "online_at",
        "offline_at",
        "irc_chat",

        "start_channel_points",
        "channel_points",
        "viewer_is_mod",
        "activeMultipliers",
        "stream",
        "raid",
        "history",
    ]

    @dispatch
    def __init__(self, username: str, settings: StreamerSettings = StreamerSettings()):
        super().__init__()
        self._username: str = username.lower().strip()
        self._display_name: str = ''
        self._channel_id: int = 0
        self.settings = settings
        # self._online = False
        self.online_at = 0
        self.offline_at = 0
        self.start_channel_points: int = 0
        self.channel_points: int = 0
        self.viewer_is_mod = False
        self.activeMultipliers = None
        self.irc_chat = None

        self.stream = Stream()

        self.raid = None
        self.history = LockedDict()

    @dispatch
    def __init__(self, username: str, display_name: str = '', settings: StreamerSettings = StreamerSettings()):
        self.__init__(username, settings)
        self.display_name = display_name

    @dispatch
    def __init__(self, channel_id: Union[str, int], username: str,
                 display_name: str = '', settings: StreamerSettings = StreamerSettings()):
        self.__init__(username, display_name, settings)
        self.channel_id = channel_id

    def __repr__(self):
        return f"Streamer(username={self.username}, channel_id={self.channel_id}, "\
               f"channel_points={self.channel_points_printable})"

    def __str__(self):
        # display_name = self.display_name
        # if self.username != display_name.lower():
        #     display_name = f"{self.display_name}({self.username})"
        return (
            f"{self.printable_display_name}"
            f"{' ' + self.gained_points_printable + ('/' if self.channel_points else '') if self.gained_points else ''}"
            f"{('' if self.gained_points else ' ') + self.channel_points_printable if self.channel_points else ''}"
            if Settings.logger.less
            else self.__repr__()
        )

    def __bool__(self):
        return self.channel_id or self.username

    @property
    def printable_display_name(self) -> str:
        display_name = self.display_name
        if self.username != display_name.lower():
            display_name = f"{self.display_name}({self.username})"
        return display_name

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, data: str):
        self._username = data.lower().strip()

    @property
    def display_name(self) -> str:
        if self._display_name:
            return self._display_name
        return self.username

    @display_name.setter
    def display_name(self, data: str):
        self._display_name = data.strip()

    @property
    def channel_id(self) -> str:
        return str(self._channel_id)

    @channel_id.setter
    def channel_id(self, data: Union[str, int]):
        if data and (data:=int(data)):
            self._channel_id = data

    @property
    def streamer_url(self):
        return f"{URL}/{self.username}"

    @property
    def online(self) -> bool:
        return self.stream.online

    def offline(self):
        self.stream_spade_url = None

    def stream_spade_url(self, url: Optional[str]):
        with self.stream, self:
            self.stream._spade_url = url
            if url is not (online:=self.online):
                if url:
                    self.online_at = time.time()
                    self.stream.init_watch_streak()
                else:
                    self.offline_at = time.time()

        self.toggle_chat()

        logger.info(
            f"{self} is {'Online' if online else 'Offline'}!",
            extra={
                "emoji": ":partying_face:" if online else ":sleeping:",
                "event": Events.STREAMER_ONLINE if online else Events.STREAMER_OFFLINE,
                "links": {self.printable_display_name: self.streamer_url}
            },
        )

    stream_spade_url = property(None, stream_spade_url)

    # @online.setter
    # def online(self, d: bool):
    #     if d is not self._online:
    #         if d:
    #             self.online_at = time.time()
    #             self.stream.init_watch_streak()
    #         else:
    #             self.offline_at = time.time()
    #
    #         self._online = d
    #
    #     self.toggle_chat()
    #
    #     logger.info(
    #         f"{self} is {'Online' if self._online else 'Offline'}!",
    #         extra={
    #             "emoji": ":partying_face:" if self._online else ":sleeping:",
    #             "event": Events.STREAMER_ONLINE if self._online else Events.STREAMER_OFFLINE,
    #             "links": {self.printable_display_name: self.streamer_url}
    #         },
    #     )

    @property
    def channel_points_printable(self) -> str:
        return _millify(self.channel_points)

    @property
    def gained_points(self) -> int:
        # with self:
        return self.channel_points - self.start_channel_points

    @property
    def gained_points_printable(self) -> str:
        diff = self.gained_points
        return f"{'+' if diff > 0 else ''}{_millify(diff)}"

    def print_history(self):
        with self.history:
            return ", ".join(
                [
                    f"{key}({self.history[key]['counter']} times, {_millify(self.history[key]['amount'])} gained)"
                    for key in sorted(self.history)
                    if self.history[key]["counter"] != 0
                ]
            )

    def update_history(self, reason_code, earned, counter=1):
        with self.history:
            if reason_code not in self.history:
                self.history[reason_code] = {"counter": 0, "amount": 0}
            self.history[reason_code]["counter"] += counter
            self.history[reason_code]["amount"] += earned

        if reason_code == "WATCH_STREAK":
            self.stream.watch_streak_missing = False

    def drops_condition(self):
        with self:
            return (
                self.settings.claim_drops
                and self.online
                # and self.stream.drops_tags is True
                and self.stream.campaigns_ids
            )

    @property
    def total_points_multiplier(self):
        with self:
            return (
                sum(
                    map(
                        lambda x: x["factor"],
                        self.activeMultipliers,
                    ),
                )
                if self.activeMultipliers is not None
                else 0
            )

    def get_prediction_window(self, prediction_window_seconds):
        delay_mode = self.settings.bet.delay_mode
        delay = self.settings.bet.delay
        if delay_mode == DelayMode.FROM_START:
            return min(delay, prediction_window_seconds)
        elif delay_mode == DelayMode.FROM_END:
            return max(prediction_window_seconds - delay, 0)
        elif delay_mode == DelayMode.PERCENTAGE:
            return prediction_window_seconds * delay
        else:
            return prediction_window_seconds

    # === ANALYTICS === #
    def persistent_annotations(self, event_type, event_text):
        event_type = event_type.upper()
        if event_type in ["WATCH_STREAK", "WIN", "PREDICTION_MADE", "LOSE"]:
            primary_color = (
                "#45c1ff"  # blue #45c1ff yellow #ffe045 green #36b535 red #ff4545
                if event_type == "WATCH_STREAK"
                else ("#ffe045" if event_type == "PREDICTION_MADE"
                      else ("#36b535" if event_type == "WIN" else "#ff4545"))
            )
            data = {
                "borderColor": primary_color,
                "label": {
                    "style": {"color": "#000", "background": primary_color},
                    "text": event_text,
                },
            }
            self.__save_json("annotations", data)

    def persistent_series(self, event_type="Watch"):
        self.__save_json("series", event_type=event_type)

    def __save_json(self, key, data={}, event_type="Watch"):
        # https://stackoverflow.com/questions/4676195/why-do-i-need-to-multiply-unix-timestamps-by-1000-in-javascript
        now = datetime.now().replace(microsecond=0)
        data.update({"x": round(datetime.timestamp(now) * 1000)})

        if key == "series":
            data.update({"y": self.channel_points})
            if event_type is not None:
                data.update({"z": event_type.replace("_", " ").title()})

        fname = os.path.join(Settings.analytics_path, f"{self.username}.json")
        temp_fname = fname + '.temp'  # Temporary file name

        # Create and write to the temporary file
        with self, open(temp_fname, "w") as temp_file:
            json_data = json.load(
                open(fname, "r")) if os.path.isfile(fname) else {}
            if key not in json_data:
                json_data[key] = []
            json_data[key].append(data)
            json.dump(json_data, temp_file, indent=4)

        # Replace the original file with the temporary file
        os.replace(temp_fname, fname)

    def leave_chat(self):
        if self.irc_chat is not None:
            self.irc_chat.stop()

            # Recreate a new thread to start again
            # raise RuntimeError("threads can only be started once")
            self.irc_chat = ThreadChat(
                self.irc_chat.username,
                self.irc_chat.token,
                self.username,
            )

    def __join_chat(self):
        if self.irc_chat is not None:
            if self.irc_chat.is_alive() is False:
                self.irc_chat.start()

    def toggle_chat(self):
        if self.settings.chat == ChatPresence.ALWAYS:
            self.__join_chat()
        elif self.settings.chat != ChatPresence.NEVER:
            if self.online:
                if self.settings.chat == ChatPresence.ONLINE:
                    self.__join_chat()
                elif self.settings.chat == ChatPresence.OFFLINE:
                    self.leave_chat()
            else:
                if self.settings.chat == ChatPresence.ONLINE:
                    self.leave_chat()
                elif self.settings.chat == ChatPresence.OFFLINE:
                    self.__join_chat()

    def payload(self):
        with self:
            data = {
                "channel": self.username,
                "channel_id": self.channel_id,
                "broadcast_id": self.stream.id,
                # "player": "site",
                # "user_id": self.twitch_login.get_user_id(),
                # "live": True,

                # 'game_id': str(self.stream.game.id),
                # 'game': self.stream.game.name,

                "url": self.streamer_url,
            }

        if self.settings.claim_drops:
            with self.stream.game:
                data.update({'game_id': str(self.stream.game.id),
                             'game': self.stream.game.name})

        return data
