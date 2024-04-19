# For documentation on Twitch GraphQL API see:
# https://www.apollographql.com/docs/
# https://github.com/mauricew/twitch-graphql-api
# Full list of available methods: https://azr.ivr.fi/schema/query.doc.html (a bit outdated)
import json
import logging
import os
import random
import re
import string
import time
# from datetime import datetime
from pathlib import Path
from secrets import choice, token_hex
from threading import RLock
from typing import Optional
from base64 import b64encode
import urllib3.request

from TwitchChannelPointsMiner.classes.entities.CampaignMngr import CampaignMngr
from TwitchChannelPointsMiner.classes.entities.Drop import Drop
from TwitchChannelPointsMiner.classes.Exceptions import StreamerDoesNotExistException
from TwitchChannelPointsMiner.classes.Settings import (
    Events,
    FollowersOrder,
    Priority,
    Settings,
)
from TwitchChannelPointsMiner.classes.TwitchLogin import TwitchLogin
from TwitchChannelPointsMiner.classes.entities.Game import Game
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer
from TwitchChannelPointsMiner.constants import (
    CLIENT_ID,
    CLIENT_VERSION,
    URL,
    TWITCH_POOL,
    HOST,
    USER_AGENTS,
)
from TwitchChannelPointsMiner.classes.entities.GamesMngr import GamesMngr
from TwitchChannelPointsMiner.classes.TwitchGQL import TwitchGQL
from TwitchChannelPointsMiner.classes.TwitchGQLQuery import TwitchGQLQuerys, TwitchGQLQuery
from TwitchChannelPointsMiner.utils import (
    _millify,
    create_chunks,
    internet_connection_available,
    at_least_one_value_in_settings_is,
)

logger = logging.getLogger(__name__)


class Twitch(object):
    __slots__ = [
        "cookies_file",
        "user_agent",
        "twitch_login",
        "_running",
        "device_id",
        # "integrity",
        # "integrity_expire",
        "client_session",
        "client_version",
        "twilight_build_id_pattern",
        "twitch_gql",
        "_internet_lock"
    ]

    def __init__(self, username, user_agent, password=None):
        cookies_path = os.path.join(Path().absolute(), "cookies")
        Path(cookies_path).mkdir(parents=True, exist_ok=True)
        self.cookies_file = os.path.join(cookies_path, f"{username}.pkl")
        self.user_agent = user_agent
        self.device_id = "".join(
            choice(string.ascii_letters + string.digits) for _ in range(32)
        )
        self.twitch_login = TwitchLogin(
            CLIENT_ID, self.device_id,
            username, self.user_agent,
            password=password
        )
        self._running = True
        # self.integrity = None
        # self.integrity_expire = 0
        self.client_session = token_hex(16)
        self.client_version = CLIENT_VERSION
        self.twilight_build_id_pattern = re.compile(
            r"window\.__twilightBuildID=\"([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}"
            "-4[0-9A-Fa-f]{3}-[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12})\";"
        )
        self.twitch_gql = TwitchGQL(pool=TWITCH_POOL)
        self._internet_lock = RLock()

    def twitch_gql_no_internet(self, *args, **kwargs):
        while True:
            try:
                return self.twitch_gql(*args, **kwargs)
            except (urllib3.exceptions.NewConnectionError,
                    urllib3.exceptions.ConnectionError,
                    urllib3.exceptions.MaxRetryError,
                    urllib3.exceptions.ConnectTimeoutError,
                    urllib3.exceptions.ReadTimeoutError) as e:
                logger.warning("Seems like TwitchGQL has connection issue")
                if self.check_connection_handler(6):
                    logger.error(f"TwitchGQL url error {e}")

    def login(self):
        if not os.path.isfile(self.cookies_file):
            if self.twitch_login.login_flow():
                self.twitch_login.save_cookies(self.cookies_file)
        else:
            self.twitch_login.load_cookies(self.cookies_file)
            self.twitch_login.set_token(self.twitch_login.get_auth_token())

        self.twitch_gql.headers = {
            "Authorization": f"OAuth {self.twitch_login.get_auth_token()}",
            "Client-Id": CLIENT_ID,
            # "Client-Integrity": self.post_integrity(),
            "Client-Session-Id": self.client_session,
            "Client-Version": self.update_client_version(),
            "User-Agent": self.user_agent,
            "X-Device-Id": self.device_id,
            "Connection": "keep-alive",
        }

    # === STREAMER / STREAM / INFO === #
    def get_spade_url(self, streamer: Streamer):
        # fixes AttributeError: 'NoneType' object has no attribute 'group'
        # headers = {"User-Agent": self.user_agent}
        headers = {"User-Agent": USER_AGENTS["Linux"]["FIREFOX"]}

        def get_st_url():
            result = None

            main_page_request = TWITCH_POOL.request('GET', streamer.streamer_url, headers=headers)
            if main_page_request.status != 200:
                ...
            # old domain static.twitchcdn.net
            elif (l := re.search("(https://(?:static.twitchcdn.net|assets.twitch.tv)/config/settings.*?js)",
                                main_page_request.data.decode('utf-8'))):
                result = l.group(1)

            if not result:
                logger.debug("Error with 'get_spade_url': no match 'settings_url'")
            return result

        def get_spd_url(settings_url: Optional[str]):
            if settings_url:
                settings_request = TWITCH_POOL.request('GET', settings_url, headers=headers)
                if settings_request.status != 200:
                    ...
                elif l := re.search('"spade_url":"(.*?)"', settings_request.data.decode('utf-8')):
                    streamer.stream_spade_url = spade_url = l.group(1)
                    if not spade_url:
                        logger.debug("Error with 'get_spade_url': no match 'spade_url'")

        try:
            get_spd_url(get_st_url())
        except urllib3.exceptions.RequestError as e:
            logger.error(f"Something went wrong during extraction of 'spade_url': {e}")
        except (urllib3.exceptions.NewConnectionError,
                urllib3.exceptions.ConnectionError,
                urllib3.exceptions.MaxRetryError,
                urllib3.exceptions.ConnectTimeoutError,
                urllib3.exceptions.ReadTimeoutError) as e:
            # logger.error(f"No internet connection or server not responding")
            if self.check_connection_handler(6):
                logger.error(f"Get spade url error {e}")

    # def get_broadcast_id(self, streamer):
    #     # json_data = copy.deepcopy(GQLOperations.WithIsStreamLiveQuery)
    #     # json_data["variables"] = {"id": streamer.channel_id}
    #     response = self._twitch_gql(TwitchGQLQuerys.WithIsStreamLiveQuery, {"id": streamer.channel_id})
    #     stream = response["data"]["user"]["stream"]
    #     if not response or response.get('errors') or not stream:
    #         raise StreamerIsOfflineException
    #     else:
    #         return stream["id"]

    def upd_stream_info(self, streamer: Streamer, response=None) -> bool:
        if not response:
            response = self.twitch_gql_no_internet(TwitchGQLQuerys.VideoPlayerStreamInfoOverlayChannel,
                                                   {"channel": streamer.username})

        if response and not response.get('errors') and response["data"]["user"]["stream"]:
            stream_info = response["data"]["user"]
            streamer.stream.update(
                id=stream_info["stream"]["id"],
                title=stream_info["broadcastSettings"]["title"],
                game=GamesMngr()(stream_info["broadcastSettings"]["game"])
                if stream_info["broadcastSettings"]["game"] else Game(),
                tags=stream_info["stream"]["tags"],
                viewers_count=stream_info["stream"]["viewersCount"],
            )
            return True
        return False

    def pull_stream_online_status_info(self, streamer: Streamer, response: Optional[dict] = None):
        if not response:
            query = TwitchGQLQuery()
            if streamer.settings.claim_drops and int(streamer.channel_id):
                query(TwitchGQLQuerys.DropsHighlightService_AvailableDrops, {"channelID": streamer.channel_id})
            response = self.twitch_gql_no_internet(query(TwitchGQLQuerys.VideoPlayerStreamInfoOverlayChannel,
                                                   {"channel": streamer.username}))
        elif (streamer.settings.claim_drops and
              int(streamer.channel_id) and
              TwitchGQLQuerys.DropsHighlightService_AvailableDrops.name not in response):
            response[TwitchGQLQuerys.DropsHighlightService_AvailableDrops.name] =\
                self.twitch_gql_no_internet(TwitchGQLQuerys.DropsHighlightService_AvailableDrops,
                                            {"channelID": streamer.channel_id})

        if TwitchGQLQuerys.VideoPlayerStreamInfoOverlayChannel.name in response:
            if self.upd_stream_info(streamer, response[TwitchGQLQuerys.VideoPlayerStreamInfoOverlayChannel.name]):
                if not streamer.online:
                    self.get_spade_url(streamer)
            else:
                streamer.offline()

        if streamer.settings.claim_drops and TwitchGQLQuerys.DropsHighlightService_AvailableDrops.name in response:
            # Update also the campaigns_ids so we are sure to tracking the correct campaign
            streamer.stream.campaigns_ids = (
                self.__get_campaign_ids_from_streamer(streamer,
                                                      response[TwitchGQLQuerys.DropsHighlightService_AvailableDrops.name]))

    @staticmethod
    def channel_id_process(response):
        if "data" in response and "user" in response["data"] and response["data"]["user"]:
            return response["data"]["user"]["id"]
        else:
            raise StreamerDoesNotExistException

    def get_channel_id(self, streamer_username) -> Optional[str]:
        return self.channel_id_process(self.twitch_gql(TwitchGQLQuerys.ReportMenuItem,
                                                       {"channelLogin": streamer_username}))

    def get_followers(self, limit: int = 100, order: FollowersOrder = FollowersOrder.ASC) -> dict:
        variables = {"limit": limit, "order": str(order)}
        has_next = True
        follows = {}
        while has_next:
            json_response = self.twitch_gql_no_internet(TwitchGQLQuerys.ChannelFollows, variables)
            try:
                follows_response = json_response["data"]["user"]["follows"]
                for f in follows_response["edges"]:
                    follows[f["node"]["login"].lower().strip()] = f["node"]["displayName"].strip()
                    variables["cursor"] = f["cursor"]

                has_next = follows_response["pageInfo"]["hasNextPage"]
            except KeyError:
                return {}
        return follows

    def update_raid(self, streamer, raid):
        if streamer.raid != raid:
            streamer.raid = raid

            self.twitch_gql(TwitchGQLQuerys.JoinRaid, {"input": {"raidID": raid.id}})

            logger.info(
                f"Joining raid from {streamer} to {raid.target_streamer}!",
                extra={"emoji": ":performing_arts:",
                       "event": Events.JOIN_RAID,
                       "links": {
                           streamer.printable_display_name: streamer.streamer_url,
                           raid.target_streamer.printable_display_name: raid.target_streamer.streamer_url
                       }
                       },
            )

    def viewer_is_mod(self, streamer):
        response = self.twitch_gql(TwitchGQLQuerys.ModViewChannelQuery, {"channelLogin": streamer.username})

        try:
            streamer.viewer_is_mod = response["data"]["user"]["self"]["isModerator"]
        except (ValueError, KeyError):
            streamer.viewer_is_mod = False

    # === 'GLOBALS' METHODS === #
    # Create chunk of sleep of speed-up the break loop after CTRL+C
    def __chuncked_sleep(self, seconds, chunk_size=3):
        sleep_time = max(seconds, 0) / chunk_size
        for i in range(0, chunk_size):
            time.sleep(sleep_time)
            if not self._running:
                break

    def check_connection_handler(self, chunk_size) -> bool:
        connection_stable = True
        # The success rate It's very hight usually. Why we have failed?
        # Check internet connection ...
        with self._internet_lock:
            logger.warning("Checking internet connection...")
            while not internet_connection_available():
                connection_stable = False
                random_sleep = 1  # random.randint(1, 3)
                logger.warning(
                    f"No internet connection available! Retry after {random_sleep}m"
                )
                self.__chuncked_sleep(random_sleep * 60, chunk_size=chunk_size)
            else:
                logger.warning("Internet connection is good")
                time.sleep(1)

        return connection_stable

    """
    def post_gql_request(self, json_data):
        try:
            response = try_post(
                GQLOperations.url,
                json=json_data,
                headers={
                    "Authorization": f"OAuth {self.twitch_login.get_auth_token()}",
                    "Client-Id": CLIENT_ID,
                    # "Client-Integrity": self.post_integrity(),
                    "Client-Session-Id": self.client_session,
                    "Client-Version": self.update_client_version(),
                    "User-Agent": self.user_agent,
                    "X-Device-Id": self.device_id,
                },
                timeout=5,
            )
            logger.debug(
                f"Data: {json_data}, Status code: {response.status_code}, Content: {response.text}"
            )
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Error with GQLOperations ({json_data['operationName']}): {e}"
            )
            return {}

    # Request for Integrity Token
    # Twitch needs Authorization, Client-Id, X-Device-Id to generate JWT which is used for authorize gql requests
    # Regenerate Integrity Token 5 minutes before expire
    def post_integrity(self):
        if (
            self.integrity_expire - datetime.now().timestamp() * 1000 > 5 * 60 * 1000
            and self.integrity is not None
        ):
            return self.integrity
        try:
            response = requests.post(
                GQLOperations.integrity_url,
                json={},
                headers={
                    "Authorization": f"OAuth {self.twitch_login.get_auth_token()}",
                    "Client-Id": CLIENT_ID,
                    "Client-Session-Id": self.client_session,
                    "Client-Version": self.update_client_version(),
                    "User-Agent": self.user_agent,
                    "X-Device-Id": self.device_id,
                },
            )
            logger.debug(
                f"Data: [], Status code: {response.status_code}, Content: {response.text}"
            )
            self.integrity = response.json().get("token", None)
            # logger.info(f"integrity: {self.integrity}")

            if self.isBadBot(self.integrity) is True:
                logger.info(
                    "Uh-oh, Twitch has detected this miner as a \"Bad Bot\". Don't worry.")

            self.integrity_expire = response.json().get("expiration", 0)
            # logger.info(f"integrity_expire: {self.integrity_expire}")
            return self.integrity
        except requests.exceptions.RequestException as e:
            logger.error(f"Error with post_integrity: {e}")
            return self.integrity

    # verify the integrity token's contents for the "is_bad_bot" flag
    def isBadBot(self, integrity):
        stripped_token: str = self.integrity.split('.')[2] + "=="
        messy_json: str = urlsafe_b64decode(
            stripped_token.encode()).decode(errors="ignore")
        match = re.search(r'(.+)(?<="}).+$', messy_json)
        if match is None:
            # raise MinerException("Unable to parse the integrity token")
            logger.info("Unable to parse the integrity token. Don't worry.")
            return
        decoded_header = json.loads(match.group(1))
        # logger.info(f"decoded_header: {decoded_header}")
        if decoded_header.get("is_bad_bot", "false") != "false":
            return True
        else:
            return False"""

    def update_client_version(self):
        try:
            response = TWITCH_POOL.request('GET', URL)
            if response.status != 200:
                logger.debug(
                    f"Error with update_client_version: {response.status_code}"
                )
                return self.client_version
            matcher = re.search(self.twilight_build_id_pattern, response.data.decode('utf-8'))
            if not matcher:
                logger.debug("Error with update_client_version: no match")
                return self.client_version
            self.client_version = matcher.group(1)
            logger.debug(f"Client version: {self.client_version}")
            return self.client_version
        except urllib3.exceptions.RequestError as e:
            logger.debug(f"Error with update_client_version: {e}")
            return self.client_version

    def send_minute_watched_events(self, streamers, priority, stream_watching_limit: int = 2, chunk_size=6):
        iteration_timestamp = None
        while self._running:
            streamers_online = []
            streamers_watching = []
            try:
                with streamers:
                    for index, streamer in streamers.items():
                        with streamer:
                            if streamer.online and (time.time() - streamer.stream.online_at) > 30:
                                streamers_online.append({'streamer': streamer,
                                                         'url': streamer.stream.spade_url,
                                                         'payload': streamer.payload(),
                                                         'name': str(streamer)})

                for prior in priority:
                    if (length := len(streamers_watching)) >= stream_watching_limit:
                        break

                    if prior == Priority.ORDER:
                        # Get the first 2 items, they are already in order
                        streamers_watching += streamers_online[:stream_watching_limit - length]

                    elif prior in [Priority.POINTS_ASCENDING, Priority.POINTS_DESCENDING]:
                        streamers_watching += sorted(
                            streamers_online,
                            key=lambda x: x['streamer'].channel_points,
                            reverse=(
                                True if prior == Priority.POINTS_DESCENDING else False
                            ),
                        )[:stream_watching_limit - length]

                    elif prior == Priority.STREAK:
                        """
                        Check if we need need to change priority based on watch streak
                        Viewers receive points for returning for x consecutive streams.
                        Each stream must be at least 10 minutes long and it must have been at least 30 minutes since
                        the last stream ended.
                        Watch at least 6m for get the +10
                        """
                        for data in streamers_online:
                            with data['streamer'] as streamer:
                                if (
                                    streamer.settings.watch_streak
                                    and streamer.stream.watch_streak_missing
                                    and (time.time() - streamer.stream.offline_at) > 30 * 60
                                    and streamer.stream.minute_watched < 7  # fix #425
                                ):
                                    streamers_watching.append(data)
                                    if len(streamers_watching) == stream_watching_limit:
                                        break

                    elif prior == Priority.DROPS:
                        for data in streamers_online:
                            if data['streamer'].drops_condition():
                                streamers_watching.append(data)
                                if len(streamers_watching) == stream_watching_limit:
                                    break

                    elif prior == Priority.SUBSCRIBED:
                        streamers_with_multiplier = [
                            data
                            for data in streamers_online
                            if data['streamer'].activeMultipliers
                        ]
                        streamers_with_multiplier = sorted(
                            streamers_with_multiplier,
                            key=lambda x: data['streamer'].total_points_multiplier,
                            reverse=True,
                        )
                        streamers_watching += streamers_with_multiplier[:stream_watching_limit - length]

                    """
                    Twitch has a limit - you can't watch more than 2 channels at one time.
                    We take the first two streamers from the list as they have the highest priority
                    (based on order or WatchStreak).
                    """

                    # cached_payload = {}
                    # for index in streamers_watching[:stream_watching_limit]:
                    #     streamer = streamers_locked[index]
                    #     cached_payload[index] = [streamer.stream.spade_url,
                    #                              streamer.payload(),
                    #                              str(streamer)]
                    #     last = index

                streamers_watching = streamers_watching[:stream_watching_limit]

                period = 60 / max(len(streamers_watching), 1)
                for data in streamers_watching:
                    # with streamers:
                    streamer = data['streamer']
                    url = data['url']
                    payload = data['payload']
                    name = data['name']

                    payload.update({
                        "player": "site",
                        "live": True,

                        'browser': self.user_agent[(self.user_agent.find('/') + 1):],
                        'user_agent': self.user_agent,

                        'device_id': self.device_id,
                        'distinct_id': self.device_id,
                        'session_device_id': self.device_id,
                        'host': HOST,

                        'login': self.twitch_login.username,
                        'user_id': self.twitch_login.get_user_id(),
                    })
                    payload = [{"event": "minute-watched", "properties": payload}]
                    payload = json.dumps(payload, separators=(",", ":"))
                    payload = (b64encode(payload.encode("utf-8"))).decode("utf-8")

                    if iteration_timestamp and \
                       (delay:=(iteration_timestamp + period - time.time())) > 0:
                        self.__chuncked_sleep(delay, chunk_size=chunk_size)
                    try:
                        response = TWITCH_POOL.request_encode_body(method='POST',
                                                                   url=url,
                                                                   # body=f"data={payload}",
                                                                   encode_multipart=False,
                                                                   timeout=urllib3.Timeout(total=period / 2),
                                                                   headers={
                                                                       'Accept': '*/*',
                                                                       'Accept-Encoding': 'gzip, deflate',
                                                                       'User-Agent': self.user_agent,
                                                                       'Connection': 'keep-alive'},
                                                                   fields={'data': payload})
                        logger.debug(
                            f"Send minute watched request for {name} - Status code: {response.status}"
                        )
                        if response.status == 204:
                            iteration_timestamp = time.time()

                            streamer.stream.update_minute_watched()

                            """
                            Remember, you can only earn progress towards a time-based Drop on one participating 
                            channel at a time.  [ ! ! ! ]
                            You can also check your progress towards Drops within a campaign anytime by viewing 
                            the Drops Inventory.
                            For time-based Drops, if you are unable to claim the Drop in time, you will be able 
                            to claim it from the inventory page until the Drops campaign ends.
                            """
                            with streamer:
                                for campaign in streamer.stream.campaigns:
                                    for drop in campaign.drops:
                                        # We could add .has_preconditions_met condition inside is_printable
                                        if drop.has_preconditions_met and drop.is_printable:
                                            drop_messages = [
                                                f"{streamer} is streaming {streamer.stream}",
                                                f"Campaign: {campaign}",
                                                f"Drop: {drop}",
                                                f"{drop.progress_bar()}",
                                            ]
                                            for single_line in drop_messages:
                                                logger.info(
                                                    single_line,
                                                    extra={
                                                        "event": Events.DROP_STATUS,
                                                        "skip_telegram": True,
                                                        "skip_discord": True,
                                                        "skip_webhook": True,
                                                        "skip_matrix": True,
                                                    },
                                                )

                                            if Settings.logger.telegram:
                                                Settings.logger.telegram.send(
                                                    "\n".join(drop_messages),
                                                    Events.DROP_STATUS,
                                                )

                                            if Settings.logger.discord:
                                                Settings.logger.discord.send(
                                                    "\n".join(drop_messages),
                                                    Events.DROP_STATUS,
                                                )
                                            if Settings.logger.webhook:
                                                Settings.logger.webhook.send(
                                                    "\n".join(drop_messages),
                                                    Events.DROP_STATUS,
                                                )

                    except urllib3.exceptions.ConnectionError as e:
                        logger.warning(f"Error while trying to send minute watched: {e}")
                        iteration_timestamp = time.time()
                    except (urllib3.exceptions.MaxRetryError,
                            urllib3.exceptions.ConnectTimeoutError,
                            urllib3.exceptions.ReadTimeoutError):
                        self.check_connection_handler(chunk_size)

                if not streamers_watching:
                    self.__chuncked_sleep(30, chunk_size=chunk_size)
            except Exception:
                logger.error("Exception raised in send minute watched", exc_info=True)

    # === CHANNEL POINTS / PREDICTION === #
    # Load the amount of current points for a channel, check if a bonus is available
    def load_channel_points_context(self, streamer: Streamer, response=None):
        if not response:
            response = self.twitch_gql_no_internet(TwitchGQLQuerys.ChannelPointsContext,
                                                   {"channelLogin": streamer.username})

        if response:
            if response["data"]["community"]:
                channel = response["data"]["community"]["channel"]
                community_points = channel["self"]["communityPoints"]
                with streamer:
                    streamer.channel_points = community_points["balance"]
                    streamer.activeMultipliers = community_points["activeMultipliers"]

                if community_points["availableClaim"]:
                    self.claim_bonus(streamer, community_points["availableClaim"]["id"])
            else:
                raise StreamerDoesNotExistException

    def make_predictions(self, event):
        decision = event.bet.calculate(event.streamer.channel_points)
        # selector_index = 0 if decision["choice"] == "A" else 1

        logger.info(
            f"Going to complete bet for {event}",
            extra={
                "emoji": ":four_leaf_clover:",
                "event": Events.BET_GENERAL,
                "links": {event.streamer.printable_display_name: event.streamer.streamer_url}
            },
        )
        if event.status == "ACTIVE":
            skip, compared_value = event.bet.skip()
            if skip:
                logger.info(
                    f"Skip betting for the event {event}",
                    extra={
                        "emoji": ":pushpin:",
                        "event": Events.BET_FILTERS,
                        "links": {event.streamer.printable_display_name: event.streamer.streamer_url}
                    },
                )
                logger.info(
                    f"Skip settings {event.bet.settings.filter_condition}, current value is: {compared_value}",
                    extra={
                        "emoji": ":pushpin:",
                        "event": Events.BET_FILTERS,
                    },
                )
            else:
                if decision["amount"] >= 10:
                    logger.info(
                        # f"Place {_millify(decision['amount'])} channel points on: "
                        # f"{event.bet.get_outcome(selector_index)}",
                        f"Place {_millify(decision['amount'])} channel points on: "
                        f"{event.bet.get_outcome(decision['choice'])}",
                        extra={
                            "emoji": ":four_leaf_clover:",
                            "event": Events.BET_GENERAL,
                        },
                    )

                    # json_data = copy.deepcopy(GQLOperations.MakePrediction)
                    # json_data["variables"] = {
                    #     "input": {
                    #         "eventID": event.event_id,
                    #         "outcomeID": decision["id"],
                    #         "points": decision["amount"],
                    #         "transactionID": token_hex(16),
                    #     }
                    # }
                    response = self.twitch_gql(TwitchGQLQuerys.MakePrediction, {
                        "input": {
                            "eventID": event.event_id,
                            "outcomeID": decision["id"],
                            "points": decision["amount"],
                            "transactionID": token_hex(16),
                        }
                    })
                    if (
                        "data" in response
                        and "makePrediction" in response["data"]
                        and "error" in response["data"]["makePrediction"]
                        and response["data"]["makePrediction"]["error"]
                    ):
                        error_code = response["data"]["makePrediction"]["error"]["code"]
                        logger.error(
                            f"Failed to place bet, error: {error_code}",
                            extra={
                                "emoji": ":four_leaf_clover:",
                                "event": Events.BET_FAILED,
                            },
                        )
                else:
                    logger.info(
                        f"Bet won't be placed as the amount {_millify(decision['amount'])}"
                        " is less than the minimum required 10",
                        extra={
                            "emoji": ":four_leaf_clover:",
                            "event": Events.BET_GENERAL,
                        },
                    )
        else:
            logger.info(
                f"Oh no! The event is not active anymore! Current status: {event.status}",
                extra={
                    "emoji": ":disappointed_relieved:",
                    "event": Events.BET_FAILED,
                },
            )

    def claim_bonus(self, streamer, claim_id):
        if not Settings.logger.less:
            logger.info(
                f"Claiming the bonus for {streamer}!",
                extra={"emoji": ":gift:", "event": Events.BONUS_CLAIM},
            )

        self.twitch_gql_no_internet(TwitchGQLQuerys.ClaimCommunityPoints, {
            "input": {"channelID": streamer.channel_id, "claimID": claim_id}
        })

    # === MOMENTS === #
    def claim_moment(self, streamer, moment_id):
        if not Settings.logger.less:
            logger.info(
                f"Claiming the moment for {streamer}!",
                extra={"emoji": ":video_camera:",
                       "event": Events.MOMENT_CLAIM},
            )

        self.twitch_gql(TwitchGQLQuerys.CommunityMomentCallout_Claim, {"input": {"momentID": moment_id}})

    # === CAMPAIGNS / DROPS / INVENTORY === #
    def __get_campaign_ids_from_streamer(self, streamer: Streamer, response=None):
        if not response:
            response = self.twitch_gql_no_internet(TwitchGQLQuerys.DropsHighlightService_AvailableDrops,
                                                   {"channelID": streamer.channel_id})
        try:
            return (
                [item["id"] for item in response["data"]["channel"]["viewerDropCampaigns"]]
                if response["data"]["channel"]["viewerDropCampaigns"]
                else []
            )
        except (ValueError, KeyError, TypeError):
            return []

    def __get_inventory(self):
        response = self.twitch_gql_no_internet(TwitchGQLQuerys.Inventory)

        try:
            return response["data"]["currentUser"]["inventory"] if response else {}
        except (ValueError, KeyError, TypeError):
            return {}

    def __get_drops_dashboard(self, status=None):
        response = self.twitch_gql_no_internet(TwitchGQLQuerys.ViewerDropsDashboard)
        campaigns = response["data"]["currentUser"]["dropCampaigns"] or []

        if status:
            campaigns = list(
                filter(lambda x: x["status"] == status.upper(), campaigns)) or []

        return campaigns

    def __get_campaigns_details(self, campaigns):
        result = []
        chunks = create_chunks(campaigns, 20)
        for chunk in chunks:
            json_data = []
            for campaign in chunk:
                json_data.append(TwitchGQLQuerys.DropCampaignDetails)
                json_data[-1]["variables"] = {
                    "dropID": campaign["id"],
                    "channelLogin": f"{self.twitch_login.get_user_id()}",
                }

            for _, r in self.twitch_gql_no_internet(json_data).items():
                if r["data"]["user"]:
                    result.append(r["data"]["user"]["dropCampaign"])
        return result

    def __sync_campaigns(self, campaigns):
        # We need the inventory only for get the real updated value/progress
        # Get data from inventory and sync current status with streamers.campaigns
        inventory = self.__get_inventory()
        if inventory and inventory["dropCampaignsInProgress"]:
            # Iterate all campaigns from dashboard (only active, with working drops)
            # In this array we have also the campaigns never started from us (not in nventory)
            for campaign in campaigns:
                campaign.clear_drops()  # Remove all the claimed drops
                # Iterate all campaigns currently in progress from out inventory
                for progress in inventory["dropCampaignsInProgress"]:
                    if progress["id"] == campaign.id:
                        campaign.in_inventory = True
                        campaign.sync_drops(progress["timeBasedDrops"], self.claim_drop)
                        # Remove all the claimed drops
                        campaign.clear_drops()
                        break
        return campaigns

    def claim_drop(self, drop):
        logger.info(
            f"Claim {drop}", extra={"emoji": ":package:", "event": Events.DROP_CLAIM}
        )

        response = self.twitch_gql_no_internet(TwitchGQLQuerys.DropsPage_ClaimDropRewards,
                                               {"input": {"dropInstanceID": drop.drop_instance_id}})
        try:
            # response["data"]["claimDropRewards"] can be null and respose["data"]["errors"] != []
            # or response["data"]["claimDropRewards"]["status"] === DROP_INSTANCE_ALREADY_CLAIMED
            if ("claimDropRewards" in response["data"]) and not response["data"]["claimDropRewards"]:
                return False
            elif ("errors" in response["data"]) and (response["data"]["errors"]):
                return False
            elif ("claimDropRewards" in response["data"]) and (
                response["data"]["claimDropRewards"]["status"]
                in ["ELIGIBLE_FOR_ALL", "DROP_INSTANCE_ALREADY_CLAIMED"]
            ):
                return True
            else:
                return False
        except (ValueError, KeyError):
            return False

    def claim_all_drops_from_inventory(self):
        inventory = self.__get_inventory()
        if inventory and "dropCampaignsInProgress" in inventory and inventory["dropCampaignsInProgress"]:
            for campaign in inventory["dropCampaignsInProgress"]:
                for drop_dict in campaign["timeBasedDrops"]:
                    drop = Drop(drop_dict)
                    drop.update(drop_dict["self"])
                    if drop.is_claimable:
                        drop.is_claimed = self.claim_drop(drop)
                        time.sleep(random.uniform(5, 10))

    def sync_campaigns(self, streamers, chunk_size=6):
        campaigns_update = 0
        while self._running:
            # If we have at least one streamer with settings = claim_drops True
            # Spawn a thread for sync inventory and dashboard
            with streamers:
                claim_drops = at_least_one_value_in_settings_is(streamers, "claim_drops", True)

            try:
                # Get update from dashboard each 60minutes
                if (claim_drops and
                        (campaigns_update == 0
                            # or ((time.time() - campaigns_update) / 60) > 60

                            # TEMPORARY AUTO DROP CLAIMING FIX
                            # 30 minutes instead of 60 minutes
                            or ((time.time() - campaigns_update) / 30) > 30)
                    #####################################
                ):
                    campaigns_update = time.time()

                    # TEMPORARY AUTO DROP CLAIMING FIX
                    self.claim_all_drops_from_inventory()
                    #####################################

                    # Get full details from current ACTIVE campaigns
                    # Use dashboard so we can explore new drops not currently active in our Inventory
                    campaigns_details = self.__get_campaigns_details(self.__get_drops_dashboard(status="ACTIVE"))
                    campaigns = []

                    # Going to clear array and structure. Remove all the timeBasedDrops expired or not started yet
                    for details in campaigns_details:
                        if details:
                            campaign = CampaignMngr()(details)
                            if campaign.dt_match:
                                # Remove all the drops already claimed or with dt not matching
                                campaign.clear_drops()
                                if campaign.drops:
                                    campaigns.append(campaign)

                    # Divide et impera :)
                    campaigns = self.__sync_campaigns(campaigns)

                    # Check if user It's currently streaming the same game present in campaigns_details
                    with streamers:
                        for i, streamer in streamers.items():
                            if streamer.drops_condition():
                                # yes! The streamer[i] have the drops_tags enabled and we
                                # It's currently stream a game with campaign active!
                                # With 'campaigns_ids' we are also sure that this streamer have the campaign active.
                                # yes! The streamer[index] have the drops_tags enabled and we
                                # It's currently stream a game with campaign active!
                                streamer.stream.campaigns = list(
                                    filter(
                                        lambda x: x.drops
                                        and x.game == streamer.stream.game
                                        and x.id in streamer.stream.campaigns_ids,
                                        campaigns,
                                    )
                                )

                self.__chuncked_sleep(60, chunk_size=chunk_size)
            except (ValueError, KeyError) as e:
                logger.error(f"Error while syncing inventory: {e}")
                # self.check_connection_handler(chunk_size)
