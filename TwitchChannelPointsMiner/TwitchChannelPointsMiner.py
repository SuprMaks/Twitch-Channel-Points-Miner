# -*- coding: utf-8 -*-
import copy
import logging
import os
import random
import signal
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from locked_dict.locked_dict import LockedDict
from typing import Optional

from TwitchChannelPointsMiner.classes.Chat import ChatPresence, ThreadChat
from TwitchChannelPointsMiner.classes.TwitchGQLQuery import TwitchGQLQuery, TwitchGQLQuerys
from TwitchChannelPointsMiner.classes.entities.PubsubTopic import PubsubTopic
from TwitchChannelPointsMiner.classes.entities.Streamer import (
    Streamer,
    StreamerSettings,
)
from TwitchChannelPointsMiner.classes.Exceptions import StreamerDoesNotExistException
from TwitchChannelPointsMiner.classes.Settings import FollowersOrder, Priority, Settings
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.classes.WebSocketsPool import WebSocketsPool
from TwitchChannelPointsMiner.classes.entities.StreamerStorage import StreamerStorage
from TwitchChannelPointsMiner.logger import LoggerSettings, configure_loggers
from TwitchChannelPointsMiner.utils import (
    check_versions,
    get_user_agent,
    internet_connection_available,
    set_default_settings,
)

# Suppress:
#   - chardet.charsetprober - [feed]
#   - chardet.charsetprober - [get_confidence]
#   - requests - [Starting new HTTPS connection (1)]
#   - Flask (werkzeug) logs
#   - irc.client - [process_data]
#   - irc.client - [_dispatcher]
#   - irc.client - [_handle_message]
logging.getLogger("chardet.charsetprober").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("irc.client").setLevel(logging.ERROR)
logging.getLogger("seleniumwire").setLevel(logging.ERROR)
logging.getLogger("websocket").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


class TwitchChannelPointsMiner:
    __slots__ = [
        "username",
        "twitch",
        "stream_watching_limit",
        "claim_drops_startup",
        "enable_analytics",
        "disable_ssl_cert_verification",
        "disable_at_in_nickname",
        "priority",
        "_streamers_dict",
        "streamers",
        "events_predictions",
        "_threads",
        "ws_pool",
        "session_id",
        "_running",
        "start_datetime",
        "_streamers_storage",
        "logs_file",
        "queue_listener",
    ]

    def __init__(
        self,
        username: str,
        password: str = None,
        stream_watching_limit: int = 2,
        claim_drops_startup: bool = False,
        enable_analytics: bool = False,
        disable_ssl_cert_verification: bool = False,
        disable_at_in_nickname: bool = False,
        # Settings for logging and selenium as you can see.
        priority: list = [Priority.STREAK, Priority.DROPS, Priority.ORDER],
        # This settings will be global shared trought Settings class
        logger_settings: LoggerSettings = LoggerSettings(),
        # Default values for all streamers
        streamer_settings: StreamerSettings = StreamerSettings(),
    ):
        # Fixes TypeError: 'NoneType' object is not subscriptable
        if not username or username == "your-twitch-username":
            logger.error(
                "Please edit your runner file (usually run.py) and try again.")
            logger.error("No username, exiting...")
            sys.exit(0)

        # This disables certificate verification and allows the connection to proceed,
        # but also makes it vulnerable to man-in-the-middle (MITM) attacks.
        Settings.disable_ssl_cert_verification = disable_ssl_cert_verification

        Settings.disable_at_in_nickname = disable_at_in_nickname

        import socket

        def is_connected():
            try:
                # resolve the IP address of the Twitch.tv domain name
                socket.gethostbyname("twitch.tv")
                return True
            except OSError:
                pass
            return False

        # check for Twitch.tv connectivity every 5 seconds
        error_printed = False
        while not is_connected():
            if not error_printed:
                logger.error("Waiting for Twitch.tv connectivity...")
                error_printed = True
            time.sleep(5)

        # Analytics switch
        Settings.enable_analytics = enable_analytics

        if enable_analytics:
            Settings.analytics_path = os.path.join(
                Path().absolute(), "analytics", username
            )
            Path(Settings.analytics_path).mkdir(parents=True, exist_ok=True)

        self.username = username

        # Set as global config
        Settings.logger = logger_settings

        # Init as default all the missing values
        streamer_settings.default()
        streamer_settings.bet.default()
        Settings.streamer_settings = streamer_settings

        # user_agent = get_user_agent("FIREFOX")
        user_agent = get_user_agent("CHROME")
        self.twitch = Twitch(self.username, user_agent, password)
        # Just in case clamp in range 1 or 2
        self.stream_watching_limit = max(min(2, stream_watching_limit), 1)
        self.claim_drops_startup = claim_drops_startup
        self.priority = priority if isinstance(priority, list) else [priority]

        self._streamers_dict: dict = {}
        self.streamers = LockedDict()
        self.events_predictions = {}
        self._threads = {}
        self.ws_pool = None

        self.session_id = str(uuid.uuid4())
        self._running = False
        self.start_datetime = None
        self._streamers_storage = StreamerStorage()

        self.logs_file, self.queue_listener = configure_loggers(
            self.username, logger_settings
        )

        # Check for the latest version of the script
        current_version, github_version = check_versions()

        logger.info(
            f"Twitch Channel Points Miner v2-{current_version} (fork by rdavydov)"
        )
        logger.info(
            "https://github.com/rdavydov/Twitch-Channel-Points-Miner-v2")

        if github_version == "0.0.0":
            logger.error(
                "Unable to detect if you have the latest version of this script"
            )
        elif current_version != github_version:
            logger.info(
                f"You are running version {current_version} of this script")
            logger.info(f"The latest version on GitHub is {github_version}")

        for sign in [signal.SIGINT, signal.SIGSEGV, signal.SIGTERM]:
            signal.signal(sign, self.end)

    def analytics(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        refresh: int = 5,
        days_ago: int = 7,
    ):
        # Analytics switch
        if Settings.enable_analytics:
            from TwitchChannelPointsMiner.classes.AnalyticsServer import AnalyticsServer

            http_server = AnalyticsServer(
                host=host, port=port, refresh=refresh, days_ago=days_ago, username=self.username
            )
            http_server.daemon = True
            http_server.name = "Analytics Thread"
            http_server.start()
        else:
            logger.error(
                "Can't start analytics(), please set enable_analytics=True")

    def mine(
        self,
        streamers: Optional[list] = None,
        blacklist: Optional[list] = None,
        followers: bool = False,
        followers_order: FollowersOrder = FollowersOrder.ASC,
    ):
        for streamer in streamers:
            username = (
                streamer.username
                if isinstance(streamer, Streamer)
                else streamer.lower().strip()
            )
            if username not in blacklist:
                self._streamers_dict[username] = streamer

        self.run(blacklist=blacklist, followers=followers, followers_order=followers_order)

    def run(
        self,
        blacklist: Optional[list] = None,
        followers: bool = False,
        followers_order: FollowersOrder = FollowersOrder.ASC,
    ):
        if self._running:
            logger.error("You can't start multiple sessions of this instance!")
        else:
            logger.info(
                f"Start session: '{self.session_id}'", extra={"emoji": ":bomb:"}
            )
            self._running = True
            self.start_datetime = datetime.now()

            self.twitch.login()

            if self.claim_drops_startup:
                self.twitch.claim_all_drops_from_inventory()

            self.ws_pool = WebSocketsPool(
                twitch=self.twitch,
                streamers=self.streamers,
                events_predictions=self.events_predictions,
            )

            # self._threads['upd_work_set'] = threading.Thread(
            #     target=self.upd_work_set,
            #     name="Reload streamer list",
            #     args=(blacklist, followers, followers_order),
            # )
            # self._threads['upd_work_set'].start()

            self._threads['sync_campaigns_thread'] = threading.Thread(
                target=self.twitch.sync_campaigns,
                name="Sync campaigns/inventory",
                args=(self.streamers,),
            )
            self._threads['sync_campaigns_thread'].start()

            self._threads['minute_watcher_thread'] = threading.Thread(
                target=self.twitch.send_minute_watched_events,
                name="Minute watcher",
                args=(self.streamers, self.priority, self.stream_watching_limit),
            )
            self._threads['minute_watcher_thread'].start()


            # Subscribe to community-points-user. Get update for points spent or gains
            user_id = self.twitch.twitch_login.get_user_id()
            # print(f"!!!!!!!!!!!!!! USER_ID: {user_id}")

            # Fixes 'ERR_BADAUTH'
            if not user_id:
                logger.error("No user_id, exiting...")
                self.end(0, 0)

            self.ws_pool.submit(
                PubsubTopic(
                    "community-points-user-v1",
                    user_id=user_id,
                )
            )

            def is_key_value_in_object_dict(d, key, _val):
                for _i, v in d.items():
                    if hasattr(v, key) and getattr(v, key) == _val:
                        return _i
                return None

            make_predictions = False

            while self._running:
                new_streamers = {}
                for username, val in self._streamers_dict.items():
                    if is_key_value_in_object_dict(self.streamers, 'username', username) is None:
                        new_streamers[username] = copy.deepcopy(val)

                if followers:
                    followers_array = self.twitch.get_followers(order=followers_order)
                    logger.info(
                        f"Load {len(followers_array)} followers from your profile!",
                        extra={"emoji": ":clipboard:"},
                    )

                    for id in list(self.streamers):
                        streamer = self.streamers[id]
                        if self.streamers[id].username not in followers_array:
                            self.ws_pool.unsubscribe(
                                PubsubTopic("video-playback-by-id",
                                            streamer=streamer)
                            )

                            if self.streamers[id].settings.follow_raid:
                                self.ws_pool.unsubscribe(
                                    PubsubTopic("raid",
                                                streamer=streamer))

                            if self.streamers[id].settings.make_predictions:
                                self.ws_pool.unsubscribe(
                                    PubsubTopic("predictions-channel-v1",
                                                streamer=streamer)
                                )

                            if self.streamers[id].settings.claim_moments:
                                self.ws_pool.unsubscribe(
                                    PubsubTopic("community-moments-channel-v1",
                                                streamer=streamer)
                                )

                            logger.info(
                                f"{streamer} is removed from mining list!",
                                extra={
                                    "emoji": ":sleeping:",
                                    "links": {streamer.printable_display_name: streamer.streamer_url}
                                },
                            )

                            with self.streamers:
                                with streamer, self._streamers_storage:
                                    self._streamers_storage[id] = streamer
                                del self.streamers[id]

                            if make_predictions and streamer.settings.make_predictions:
                                for _, streamer in self.streamers.items():
                                    if streamer.settings.make_predictions:
                                        break
                                else:
                                    make_predictions = False
                                    self.ws_pool.unsubscribe(
                                        PubsubTopic(
                                            "predictions-user-v1",
                                            user_id=user_id,
                                        )
                                    )

                    for username, display_name in followers_array.items():
                        if username in new_streamers:
                            if isinstance(new_streamers[username], Streamer):
                                new_streamers[username].display_name = display_name
                            else:
                                new_streamers[username] = display_name
                        elif username not in blacklist and \
                                is_key_value_in_object_dict(self.streamers, 'username', username) is None:
                            new_streamers[username] = display_name

                if new_streamers:
                    logger.info(
                        f"Loading data for {len(new_streamers)} streamers. Please wait...",
                        extra={"emoji": ":nerd_face:"},
                    )

                    for username, val in new_streamers.items():
                        if not self._running:
                            break

                        # time.sleep(random.uniform(0.3, 0.7))

                        streamer = val if isinstance(val, Streamer) else Streamer(username, val)
                        try:
                            streamer.settings = set_default_settings(
                                streamer.settings, Settings.streamer_settings
                            )
                            streamer.settings.bet = set_default_settings(
                                streamer.settings.bet, Settings.streamer_settings.bet
                            )

                            response_pack = self.twitch.twitch_gql(
                                TwitchGQLQuery(TwitchGQLQuerys.ReportMenuItem, {"channelLogin": streamer.username})
                                (TwitchGQLQuerys.ChannelPointsContext, {"channelLogin": streamer.username})
                                (TwitchGQLQuerys.VideoPlayerStreamInfoOverlayChannel, {"channel": streamer.username}))
                            if response_pack and (e:=response_pack.get('errors')):
                                logger.error(f"Error with TwitchGQL req : {e}")
                            else:
                                for name, response in response_pack.items():
                                    if name == TwitchGQLQuerys.ReportMenuItem.name:
                                        if channel_id:=self.twitch.get_channel_id_process(response):
                                            channel_id = int(channel_id)
                                            if channel_id:
                                                streamer.channel_id = channel_id
                                                if channel_id in self._streamers_storage:
                                                    streamer = self._streamers_storage[channel_id]
                                                    logger.info(
                                                        f"Restoring data for {streamer.printable_display_name}...",
                                                        extra={
                                                            "emoji": ":nerd_face:",
                                                            "links": {
                                                                streamer.printable_display_name: streamer.streamer_url}
                                                        },
                                                    )
                                            else:
                                                break
                                        else:
                                            break
                                    elif name == TwitchGQLQuerys.ChannelPointsContext.name:
                                        self.twitch.load_channel_points_process(streamer, response)
                                        if streamer.channel_id not in self._streamers_storage:
                                            streamer.start_channel_points = streamer.channel_points
                                    elif name == TwitchGQLQuerys.VideoPlayerStreamInfoOverlayChannel.name:
                                        self.twitch.force_pull_stream_online_status_info(streamer, response)

                            if not streamer.channel_id:
                                continue
                            channel_id = int(streamer.channel_id)

                            # if channel_id:=self.twitch.get_channel_id(username):
                            #     channel_id = int(channel_id)
                            #     streamer.channel_id = channel_id
                            # else:
                            #     continue

                            # Restore history and start points
                            if channel_id in self._streamers_storage:
                                # streamer = self._streamers_storage[channel_id]
                                # logger.info(
                                #     f"Restoring data for {streamer.printable_display_name}...",
                                #     extra={
                                #         "emoji": ":nerd_face:",
                                #         "links": {streamer.printable_display_name: streamer.streamer_url}
                                #     },
                                # )

                                if streamer.username != username:
                                    logger.info(
                                        f"New username {streamer.username} → {username}...",
                                        extra={
                                            "emoji": ":nerd_face:",
                                        },
                                    )
                                    streamer.username = username
                                if val and isinstance(val, str) and streamer.display_name != val:
                                    logger.info(
                                        f"New display_name {streamer.display_name} → {val}...",
                                        extra={
                                            "emoji": ":nerd_face:",
                                            "links": {streamer.display_name: streamer.streamer_url,
                                                      val: streamer.streamer_url}
                                        },
                                    )
                                    streamer.display_name = val

                            if streamer.settings.chat != ChatPresence.NEVER:
                                streamer.irc_chat = ThreadChat(
                                    self.username,
                                    self.twitch.twitch_login.get_auth_token(),
                                    streamer.username,
                                )

                            # Populate the streamers with default values.
                            # 1. Load channel points and auto-claim bonus
                            # 2. Check if streamers are online
                            # 3. DEACTIVATED: Check if the user is a moderator.
                            # (was used before the 5th of April 2021 to deactivate predictions)
                            # time.sleep(random.uniform(0.3, 0.7))
                            # self.twitch.load_channel_points_context(streamer)

                            if channel_id not in self._streamers_storage:
                                with self._streamers_storage:
                                    self._streamers_storage[channel_id] = streamer
                                # streamer.start_channel_points = streamer.channel_points

                            # self.twitch.pull_stream_online_status_info(streamer)
                            # self.twitch.viewer_is_mod(streamer)

                            with self.streamers, streamer:
                                self.streamers[channel_id] = streamer

                            self.ws_pool.submit(
                                PubsubTopic("video-playback-by-id",
                                            streamer=self.streamers[channel_id])
                            )

                            if streamer.settings.follow_raid:
                                self.ws_pool.submit(
                                    PubsubTopic("raid",
                                                streamer=self.streamers[channel_id]))

                            if streamer.settings.make_predictions:
                                if not make_predictions:
                                    make_predictions = True

                                    # Going to subscribe to predictions-user-v1.
                                    # Get update when we place a new prediction (confirm)
                                    self.ws_pool.submit(
                                        PubsubTopic(
                                            "predictions-user-v1",
                                            user_id=user_id,
                                        )
                                    )

                                self.ws_pool.submit(
                                    PubsubTopic("predictions-channel-v1",
                                                streamer=self.streamers[channel_id])
                                )

                            if streamer.settings.claim_moments:
                                self.ws_pool.submit(
                                    PubsubTopic("community-moments-channel-v1",
                                                streamer=self.streamers[channel_id])
                                )
                        except StreamerDoesNotExistException:
                            logger.info(
                                f"Streamer {username} does not exist",
                                extra={"emoji": ":cry:"},
                            )

                if self._running:
                    for i in range(1, int(60 * 30 // 5)):
                        time.sleep(5)
                        if self._running is False:
                            break

                    for _, streamer in self.streamers.items():
                        if self._running is False:
                            break

                        if streamer.online:
                            self.twitch.load_channel_points_context(streamer)

    def end(self, signum, frame):
        logger.info("CTRL+C Detected! Please wait just a moment!")

        with self.streamers as streamers_locked:
            for _, streamer in streamers_locked.items():
                if (
                    streamer.irc_chat
                    and streamer.settings.chat != ChatPresence.NEVER
                ):
                    streamer.leave_chat()
                    if streamer.irc_chat.is_alive():
                        streamer.irc_chat.join()

        self._running = self.twitch._running = False
        if self.ws_pool:
            self.ws_pool.end()

        for _, thread in self._threads.items():
            if thread:
                thread.join()

        # Check if all the mutex are unlocked.
        # Prevent breaks of .json file
        # for _, streamer in self.streamers.items():
        #     if streamer._lock.locked():
        #         streamer._lock.acquire()
        #         streamer._lock.release()

        self.__print_report()

        # Stop the queue listener to make sure all messages have been logged
        self.queue_listener.stop()

        sys.exit(0)

    def __print_report(self):
        print("\n")
        logger.info(
            f"Ending session: '{self.session_id}'", extra={"emoji": ":stop_sign:"}
        )
        if self.logs_file:
            logger.info(
                f"Logs file: {self.logs_file}", extra={"emoji": ":page_facing_up:"}
            )
        logger.info(
            f"Duration {datetime.now() - self.start_datetime}",
            extra={"emoji": ":hourglass:"},
        )

        if self.events_predictions != {}:
            print("")
            for event_id in self.events_predictions:
                event = self.events_predictions[event_id]
                if (
                    event.bet_confirmed
                    and event.streamer.settings.make_predictions
                ):
                    logger.info(
                        f"{event.streamer.settings.bet}",
                        extra={"emoji": ":wrench:"},
                    )
                    if event.streamer.settings.bet.filter_condition:
                        logger.info(
                            f"{event.streamer.settings.bet.filter_condition}",
                            extra={"emoji": ":pushpin:"},
                        )
                    logger.info(
                        f"{event.print_recap()}",
                        extra={
                            "emoji": ":bar_chart:",
                            "links": {event.streamer.printable_display_name: event.streamer.streamer_url}
                        },
                    )

        print("")
        with self._streamers_storage:
            for _, streamer in self._streamers_storage.items():
                with streamer:
                    if streamer.channel_points - streamer.start_channel_points:
                        if streamer.history:
                            logger.info(
                                f"{repr(streamer)}, Total Points Gained (after farming - before farming): "
                                f"{streamer.gained_points_printable}",
                                extra={
                                    "emoji": ":robot:",
                                    "links": {streamer.username: streamer.streamer_url}
                                },
                            )
                            logger.info(
                                f"{streamer.print_history()}",
                                extra={"emoji": ":moneybag:"},
                            )
