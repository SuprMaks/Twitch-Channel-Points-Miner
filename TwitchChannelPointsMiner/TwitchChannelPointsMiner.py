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

from TwitchChannelPointsMiner.classes.Chat import ChatPresence, ThreadChat
from TwitchChannelPointsMiner.classes.entities.PubsubTopic import PubsubTopic
from TwitchChannelPointsMiner.classes.entities.Streamer import (
    Streamer,
    StreamerSettings,
)
from TwitchChannelPointsMiner.classes.Exceptions import StreamerDoesNotExistException
from TwitchChannelPointsMiner.classes.Settings import FollowersOrder, Priority, Settings
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.classes.WebSocketsPool import WebSocketsPool
from TwitchChannelPointsMiner.logger import LoggerSettings, configure_loggers
from TwitchChannelPointsMiner.utils import (
    _millify,
    at_least_one_value_in_settings_is,
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
        "_streamers_archive",
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

        # This disables certificate verification and allows the connection to proceed, but also makes it vulnerable to man-in-the-middle (MITM) attacks.
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

        if enable_analytics is True:
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
        self._streamers_archive = {}

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
        if Settings.enable_analytics is True:
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
        streamers: list = [],
        blacklist: list = [],
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
                #del streamer.mutex
                self._streamers_dict[username] = streamer

        self.run(blacklist=blacklist, followers=followers, followers_order=followers_order)

    def upd_streamers_list(self,
                           blacklist: list = [],
                           followers: bool = False,
                           followers_order: FollowersOrder = FollowersOrder.ASC,):
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

        def is_key_value_in_object_dict(d, key, val):
            for i, v in d.items():
                if hasattr(v, key) and getattr(v, key) == val:
                    return i
            return None

        make_predictions = False

        while self._running:
            new_streamers = {}
            for username, val in self._streamers_dict.items():
                if is_key_value_in_object_dict(self.streamers, 'username', username) is None:
                    new_streamers[username] = copy.deepcopy(val)

            if followers is True:
                followers_array = self.twitch.get_followers(
                    order=followers_order)
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

                        if self.streamers[id].settings.follow_raid is True:
                            self.ws_pool.unsubscribe(
                                PubsubTopic("raid",
                                            streamer=streamer))

                        if self.streamers[id].settings.make_predictions is True:
                            self.ws_pool.unsubscribe(
                                PubsubTopic("predictions-channel-v1",
                                            streamer=streamer)
                            )

                        if self.streamers[id].settings.claim_moments is True:
                            self.ws_pool.unsubscribe(
                                PubsubTopic("community-moments-channel-v1",
                                            streamer=streamer)
                            )

                        logger.info(
                            f"{streamer} is removed from mining list!",
                            extra={
                                "emoji": ":sleeping:",
                            },
                        )

                        with self.streamers as streamers_locked:
                            with streamer:
                                self._streamers_archive[id] = copy.deepcopy(streamer)
                            del streamers_locked[id]

                        if make_predictions and streamer.settings.make_predictions is True:
                            for _, streamer in self.streamers.items():
                                if streamer.settings.make_predictions is True:
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
                    if self._running is False:
                        break

                    time.sleep(random.uniform(0.3, 0.7))

                    try:
                        streamer = (
                            val
                            if isinstance(val, Streamer) is True
                            else Streamer(username, val)
                        )
                        streamer.channel_id = self.twitch.get_channel_id(username)

                        channel_id = int(streamer.channel_id)
                        # Restore history and start points
                        if channel_id in self._streamers_archive:
                            logger.info(
                                f"Restore data for {username}...",
                                extra={"emoji": ":nerd_face:"},
                            )

                            streamer = copy.deepcopy(self._streamers_archive[channel_id])

                            if streamer.username != username:
                                logger.info(
                                    f"New username {streamer.username} → {username}...",
                                    extra={"emoji": ":nerd_face:"},
                                )
                                streamer.username = username
                            if val and isinstance(val, str) and streamer.display_name != val:
                                logger.info(
                                    f"New display_name {streamer.display_name} → {val}...",
                                    extra={"emoji": ":nerd_face:"},
                                )
                                streamer.display_name = val

                        streamer.settings = set_default_settings(
                            streamer.settings, Settings.streamer_settings
                        )
                        streamer.settings.bet = set_default_settings(
                            streamer.settings.bet, Settings.streamer_settings.bet
                        )
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
                        time.sleep(random.uniform(0.3, 0.7))
                        self.twitch.load_channel_points_context(streamer)

                        if channel_id in self._streamers_archive:
                            del self._streamers_archive[channel_id]
                        else:
                            streamer.start_channel_points = streamer.channel_points

                        self.twitch.check_streamer_online(streamer)
                        # self.twitch.viewer_is_mod(streamer)

                        with self.streamers as streamers_locked, streamer:
                            streamers_locked[channel_id] = copy.deepcopy(streamer)

                        self.ws_pool.submit(
                            PubsubTopic("video-playback-by-id",
                                        streamer=self.streamers[channel_id])
                        )

                        if streamer.settings.follow_raid is True:
                            self.ws_pool.submit(
                                PubsubTopic("raid",
                                            streamer=self.streamers[channel_id]))

                        if streamer.settings.make_predictions is True:
                            if make_predictions is False:
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

                        if streamer.settings.claim_moments is True:
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

                    if streamer.is_online:
                        self.twitch.load_channel_points_context(streamer)

    def run(
        self,
        blacklist: list = [],
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

            if self.claim_drops_startup is True:
                self.twitch.claim_all_drops_from_inventory()

            self.ws_pool = WebSocketsPool(
                twitch=self.twitch,
                streamers=self.streamers,
                events_predictions=self.events_predictions,
            )

            self._threads['update_streamers_thread'] = threading.Thread(
                target=self.upd_streamers_list,
                name="Reload streamer list",
                args=(blacklist, followers, followers_order),
            )
            self._threads['update_streamers_thread'].start()

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

            while self._running:
                time.sleep(random.uniform(20, 60))
                # Do an external control for WebSocket. Check if the thread is running
                # Check if is not None because maybe we have already created a new connection on array+1 and now index is None
                for index, ws in enumerate(self.ws_pool.ws):
                    if (
                        ws.is_reconnecting is False
                        and ws.elapsed_last_ping() > 10
                        and internet_connection_available() is True
                    ):
                        logger.info(
                            f"#{index} - The last PING was sent more than 10 minutes ago. Reconnecting to the WebSocket..."
                        )
                        WebSocketsPool.handle_reconnection(
                            self.ws_pool.ws[index])

    def end(self, signum, frame):
        logger.info("CTRL+C Detected! Please wait just a moment!")

        with self.streamers as streamers_locked:
            for _, streamer in streamers_locked.items():
                if (
                    streamer.irc_chat is not None
                    and streamer.settings.chat != ChatPresence.NEVER
                ):
                    streamer.leave_chat()
                    if streamer.irc_chat.is_alive() is True:
                        streamer.irc_chat.join()

        self._running = self.twitch.running = False
        if self.ws_pool is not None:
            self.ws_pool.end()

        for _, thread in self._threads.items():
            if thread is not None:
                thread.join()

        # Check if all the mutex are unlocked.
        # Prevent breaks of .json file
        for _, streamer in self.streamers.items():
            if streamer._lock.locked():
                streamer._lock.acquire()
                streamer._lock.release()

        self.__print_report()

        # Stop the queue listener to make sure all messages have been logged
        self.queue_listener.stop()

        sys.exit(0)

    def __print_report(self):
        print("\n")
        logger.info(
            f"Ending session: '{self.session_id}'", extra={"emoji": ":stop_sign:"}
        )
        if self.logs_file is not None:
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
                    event.bet_confirmed is True
                    and event.streamer.settings.make_predictions is True
                ):
                    logger.info(
                        f"{event.streamer.settings.bet}",
                        extra={"emoji": ":wrench:"},
                    )
                    if event.streamer.settings.bet.filter_condition is not None:
                        logger.info(
                            f"{event.streamer.settings.bet.filter_condition}",
                            extra={"emoji": ":pushpin:"},
                        )
                    logger.info(
                        f"{event.print_recap()}",
                        extra={"emoji": ":bar_chart:"},
                    )

        def print_total(streamer: Streamer):
            if streamer.history != {}:
                logger.info(
                    f"{repr(streamer)}, Total Points Gained (after farming - before farming): "
                    f"{_millify((streamer.channel_points - streamer.start_channel_points))}",
                    extra={"emoji": ":robot:"},
                )
                if streamer.history != {}:
                    logger.info(
                        f"{streamer.print_history()}",
                        extra={"emoji": ":moneybag:"},
                    )

        print("")
        with self.streamers as streamers_locked:
            for _, streamer in streamers_locked.items():
                print_total(streamer)

        for _, streamer in self._streamers_archive.items():
            print_total(streamer)
