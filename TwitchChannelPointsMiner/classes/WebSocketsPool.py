import json
import logging
import random
import time
# import os
from threading import Thread, Timer
# from pathlib import Path

from dateutil import parser

from TwitchChannelPointsMiner.classes.TwitchGQLQuery import TwitchGQLQuerys, TwitchGQLQuery
from TwitchChannelPointsMiner.classes.entities.EventPrediction import EventPrediction
from TwitchChannelPointsMiner.classes.entities.Message import Message
from TwitchChannelPointsMiner.classes.entities.Raid import Raid
from TwitchChannelPointsMiner.classes.Settings import Events, Settings
from TwitchChannelPointsMiner.classes.TwitchWebSocket import TwitchWebSocket
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer
from TwitchChannelPointsMiner.classes.entities.StreamerStorage import StreamerStorage
from TwitchChannelPointsMiner.constants import WEBSOCKET
from TwitchChannelPointsMiner.utils import internet_connection_available, float_round

logger = logging.getLogger(__name__)


class WebSocketsPool:
    __slots__ = ["ws", "twitch", "streamers", "events_predictions", "request_queue"]

    def __init__(self, twitch, streamers, events_predictions):
        self.ws = []
        self.twitch = twitch
        self.streamers = streamers
        self.events_predictions = events_predictions
        self.request_queue = []
        Thread(name='WebSocketsPool_watchdog', target=self._watchdog, daemon=True).start()
        Thread(name='WebSocketsPool_ping/pong(er)', target=self._pingponger, daemon=True).start()
        Thread(name='WebSocketsPool_request_processor', target=self._request_processor, daemon=True).start()

    def _pingponger(self):
        while True:
            delay_sum = 0
            for index, ws in enumerate(self.ws):
                if ws:
                    while delay_sum < (target_delay:=30 / len(self.ws)):
                        time.sleep((chunk:=target_delay / 4))
                        delay_sum += chunk
                    if ws:
                        ws.send({"type": "PING"})
                        ws.last_ping_tm = time.time()
                    delay_sum = 0

    def _watchdog(self):
        while True:
            time.sleep(random.uniform(20, 60))
            # Do an external control for WebSocket. Check if the thread is running
            # Check if is not None because maybe we have already created a new connection on array+1
            # and now index is None
            if internet_connection_available():
                for index, ws in enumerate(self.ws):
                    if not ws.is_reconnecting:
                        if ws.elapsed_last_ping > 5:
                            logger.info(
                                f"#{index} - The last PING was sent more than 5 minutes ago. "
                                "Reconnecting to the WebSocket..."
                            )
                            self.handle_reconnection(ws)
                        elif ws.elapsed_last_pong > 3:
                            logger.info(f"#{ws.index} - The last PONG was received more than 3 minutes ago")
                            self.handle_reconnection(ws)

    def _request_processor(self):
        queues = {}
        while True:
            # Group queues by operations
            while self.request_queue:
                task = self.request_queue.pop(0)
                if (op:=task['name']) not in queues:
                    queues[op] = []
                del task['name']
                queues[op].append(task)

            if queues:
                pack = {}
                query = TwitchGQLQuery()
                for op, queue in queues.items():
                    if queue:
                        task = queue.pop(0)
                        if op == 'claim_bonus':
                            pack[TwitchGQLQuerys.ClaimCommunityPoints.name] = task
                            query(TwitchGQLQuerys.ClaimCommunityPoints,
                                  {"input": {"channelID": task['streamer'].channel_id, "claimID": task['message_id']}})
                        elif op == 'update_raid':
                            # if task['streamer'].raid != task['raid']:
                            #     task['streamer'].raid = task['raid']
                            pack[TwitchGQLQuerys.JoinRaid.name] = task
                            query(TwitchGQLQuerys.JoinRaid,
                                  {"input": {"raidID": task['raid'].id}})
                        elif op == 'claim_moment':
                            pack[TwitchGQLQuerys.CommunityMomentCallout_Claim.name] = task
                            query(TwitchGQLQuerys.CommunityMomentCallout_Claim,
                                  {"input": {"momentID": task['moment_id']}})
                        elif op == 'pull_stream_online_status_info':
                            pack[TwitchGQLQuerys.VideoPlayerStreamInfoOverlayChannel.name] = task
                            query(TwitchGQLQuerys.VideoPlayerStreamInfoOverlayChannel,
                                  {"channel": task['streamer'].username})

                if query:
                    response_pack = self.twitch.twitch_gql_no_internet(query)
                    if len(query._query) > 1:
                        logger.info(f"{query.query()}")
                        logger.info(f"{response_pack}")
                    if response_pack:
                        for name, response in response_pack.items():
                            if e := response.get('errors'):
                                logger.error(f"TwitchGQL error in response {e}")
                                continue
                            if name == TwitchGQLQuerys.ClaimCommunityPoints.name:
                                if Settings.logger.less is False:
                                    logger.info(
                                        f"Claiming the bonus for "
                                        f"{pack[TwitchGQLQuerys.ClaimCommunityPoints.name]['streamer']}!",
                                        extra={"emoji": ":gift:", "event": Events.BONUS_CLAIM},
                                    )
                            elif name == TwitchGQLQuerys.JoinRaid.name:
                                logger.info(
                                    f"Joining raid from {pack[TwitchGQLQuerys.JoinRaid.name]['streamer']} to "
                                    f"{pack[TwitchGQLQuerys.JoinRaid.name]['raid'].target_streamer}!",
                                    extra={"emoji": ":performing_arts:",
                                           "event": Events.JOIN_RAID,
                                           "links": {
                                               pack[TwitchGQLQuerys.JoinRaid.name]['streamer'].printable_display_name:
                                                   pack[TwitchGQLQuerys.JoinRaid.name]['streamer'].streamer_url,
                                               pack[TwitchGQLQuerys.JoinRaid.name]['raid'].target_streamer.printable_display_name:
                                                   pack[TwitchGQLQuerys.JoinRaid.name]['raid'].target_streamer.streamer_url
                                           }
                                           },
                                )
                            elif name == TwitchGQLQuerys.CommunityMomentCallout_Claim.name:
                                if not Settings.logger.less:
                                    logger.info(
                                        f"Claiming the moment for "
                                        f"{pack[TwitchGQLQuerys.CommunityMomentCallout_Claim.name]['streamer']}!",
                                        extra={"emoji": ":video_camera:",
                                               "event": Events.MOMENT_CLAIM},
                                    )
            time.sleep(2)

    """
    API Limits
    - Clients can listen to up to 50 topics per connection.
    Trying to listen to more topics will result in an error message.
    - We recommend that a single client IP address establishes no more than 10 simultaneous connections.
    The two limits above are likely to be relaxed for approved third-party applications,
    as we start to better understand third-party requirements.
    """

    def submit(self, topic):
        # Check if we need to create a new WebSocket instance
        if not self.ws or len(self.ws[-1].topics) >= 50:
            self.ws.append(self.__new(len(self.ws)))
            self.__start(-1)

        self.__submit(-1, topic)

    def __submit(self, index, topic):
        # Topic in topics should never happen. Anyway prevent any types of duplicates
        if topic not in self.ws[index].topics:
            self.ws[index].topics.append(topic)

        if self.ws[index]:
            self.ws[index].listen(topic, self.twitch.twitch_login.get_auth_token())
        else:
            self.ws[index].pending_topics.append(topic)

    def unsubscribe(self, topic):
        for index, ws in enumerate(self.ws):
            if ws.is_opened is False:
                if topic in ws.pending_topics:
                    self.ws[index].pending_topics.remove(topic)
            else:
                self.ws[index].unlisten(topic, self.twitch.twitch_login.get_auth_token())

            if topic in ws.topics:
                self.ws[index].topics.remove(topic)

    def __new(self, index):
        return TwitchWebSocket(
            index=index,
            parent_pool=self,
            url=WEBSOCKET,
            on_message=WebSocketsPool.on_message,
            on_open=WebSocketsPool.on_open,
            on_error=WebSocketsPool.on_error,
            on_close=WebSocketsPool.on_close
            # on_close=WebSocketsPool.handle_reconnection, # Do nothing.
        )

    def __start(self, index):
        if self.ws:
            self.ws[index].start()

    def end(self):
        for index in range(0, len(self.ws)):
            self.ws[index].forced_close = True
            self.ws[index].close()

    @staticmethod
    def on_open(ws):
        while ws.pending_topics:
            topic = ws.pending_topics.pop(0)
            ws.listen(topic, ws.twitch.twitch_login.get_auth_token())
            if topic not in ws.topics:
                ws.topics.append(topic)

    @staticmethod
    def on_error(ws, error):
        # Connection lost | [WinError 10054] An existing connection was forcibly closed by the remote host
        # Connection already closed | Connection is already closed (raise WebSocketConnectionClosedException)
        logger.error(f"#{ws.index} - WebSocket error: {error}")

    @staticmethod
    def on_close(ws, close_status_code, close_reason):
        logger.info(f"#{ws.index} - WebSocket closed")
        # On close please reconnect automatically
        WebSocketsPool.handle_reconnection(ws)

    @staticmethod
    def handle_reconnection(ws):
        # Reconnect only if ws.is_reconnecting is False to prevent more than 1 ws from being created
        if ws.is_reconnecting is False:
            # Close the current WebSocket.
            ws.keep_running = False
            # Reconnect only if ws.forced_close is False (replace the keep_running)

            # Set the current socket as reconnecting status
            # So the external ping check will be locked
            ws.is_reconnecting = True

            if ws.forced_close is False:
                logger.info(
                    f"#{ws.index} - Reconnecting to Twitch PubSub server in ~60 seconds"
                )
                # time.sleep(30)

                ws.twitch.check_connection_handler(10)

                # Why not create a new ws on the same array index? Let's try.
                self = ws.parent_pool
                # Create a new connection.
                self.ws[ws.index] = self.__new(ws.index)

                self.__start(ws.index)  # Start a new thread.
                time.sleep(30)

                for topic in ws.topics:
                    self.__submit(ws.index, topic)
            ws.is_reconnecting = False

    @staticmethod
    def on_message(ws, message):
        logger.debug(f"#{ws.index} - Received: {message.strip()}")
        response = json.loads(message)

        if response["type"] == "MESSAGE":
            # We should create a Message class ...
            message = Message(response["data"])

            # If we have more than one PubSub connection, messages may be duplicated
            # Check the concatenation between message_type.top.channel_id
            if (
                ws.last_message_type_channel
                and ws.last_message_timestamp
                and ws.last_message_timestamp == message.timestamp
                and ws.last_message_type_channel == message.identifier
            ):
                return

            ws.last_message_timestamp = message.timestamp
            ws.last_message_type_channel = message.identifier

            if (streamer_index:=int(message.channel_id)) in ws.streamers:
                streamer = ws.streamers[streamer_index]
                try:
                    if message.topic == "community-points-user-v1":
                        if message.type in ["points-earned", "points-spent"]:
                            balance = message.data["balance"]["balance"]
                            streamer.channel_points = balance
                            # Analytics switch
                            if Settings.enable_analytics:
                                streamer.persistent_series(
                                    event_type=message.data["point_gain"]["reason_code"]
                                    if message.type == "points-earned"
                                    else "Spent"
                                )

                        if message.type == "points-earned":
                            earned = message.data["point_gain"]["total_points"]
                            reason_code = message.data["point_gain"]["reason_code"]

                            logger.info(
                                f"+{earned} → {streamer} - Reason: {reason_code}.",
                                extra={
                                    "emoji": ":rocket:",
                                    "event": Events.get(f"GAIN_FOR_{reason_code}"),
                                    "links": {streamer.printable_display_name: streamer.streamer_url}
                                },
                            )
                            streamer.update_history(
                                reason_code, earned
                            )
                            # Analytics switch
                            if Settings.enable_analytics:
                                streamer.persistent_annotations(
                                    reason_code, f"+{earned} - {reason_code}"
                                )
                        elif message.type == "claim-available":
                            ws.request_queue.append({'name': 'claim_bonus',
                                                     'streamer': streamer,
                                                     'message_id': message.data["claim"]["id"]})
                            # ws.twitch.claim_bonus(
                            #     streamer,
                            #     message.data["claim"]["id"],
                            # )

                    elif message.topic == "video-playback-by-id":
                        # There is stream-up message type, but it's sent earlier than the API updates
                        if message.type == "stream-up":
                            # streamer.stream.stream_up = time.time()
                            streamer.stream.online_at = time.time()
                        elif message.type == "stream-down":
                            streamer.offline()
                        elif message.type == "viewcount":
                            if 'viewers' in message.message:
                                streamer.stream.viewers_count = int(message.message['viewers'])
                            # if not streamer.stream.stream_up or streamer.stream.stream_up_elapsed > 120:
                                # ws.twitch.pull_stream_online_status_info(streamer)

                    elif message.topic == "raid":
                        if message.type == "raid_update_v2":
                            raid = Raid(
                                message.message["raid"]["id"],
                                message.message["raid"]["viewer_count"],
                                StreamerStorage()(Streamer(message.message["raid"]["target_id"],
                                                           message.message["raid"]["target_login"],
                                                           message.message["raid"]["target_display_name"]))
                            )
                            if streamer.raid != raid:
                                streamer.raid = raid
                                ws.request_queue.append({'name': 'update_raid',
                                                         'streamer': streamer,
                                                         'raid': raid})
                            # if streamer.raid != raid:
                            #     streamer.raid = raid
                            #     ws.request_queue.append(TwitchGQLQuery(TwitchGQLQuerys.JoinRaid,
                            #                                            {"input": {"raidID": raid.id}}))
                            # ws.twitch.update_raid(streamer, raid)

                    elif message.topic == "community-moments-channel-v1":
                        if message.type == "active":
                            ws.request_queue.append({'name': 'claim_moment',
                                                     'streamer': streamer,
                                                     'moment_id': message.data["moment_id"]})
                            # ws.twitch.claim_moment(
                            #     streamer, message.data["moment_id"]
                            # )

                    elif message.topic == "predictions-channel-v1":

                        event_dict = message.data["event"]
                        event_id = event_dict["id"]
                        event_status = event_dict["status"]

                        if message.type == "event-created" and event_id not in ws.events_predictions:
                            if event_status == "ACTIVE":
                                prediction_window_seconds = float(
                                    event_dict["prediction_window_seconds"]
                                )
                                # Reduce prediction window by 3/6s - Collect more accurate data for decision
                                prediction_window_seconds = streamer.get_prediction_window(prediction_window_seconds)
                                event = EventPrediction(
                                    streamer,
                                    event_id,
                                    event_dict["title"],
                                    parser.parse(event_dict["created_at"]),
                                    prediction_window_seconds,
                                    event_status,
                                    event_dict["outcomes"],
                                )
                                if event.closing_bet_after > 0:
                                    minimum_points = streamer.settings.bet.minimum_points
                                    if not minimum_points or streamer.channel_points > minimum_points:
                                        ws.events_predictions[event_id] = event

                                        place_bet_thread = Timer(
                                            0,
                                            ws.twitch.make_predictions,
                                            (ws.events_predictions[event_id],),
                                        )
                                        place_bet_thread.daemon = True
                                        place_bet_thread.interval = \
                                            start_after = max(float_round(event.closing_bet_after_raw -
                                                                          message.server_timestamp_diff), 0)
                                        place_bet_thread.start()

                                        logger.info(
                                            f"Place the bet after: {start_after}s for: "
                                            f"{ws.events_predictions[event_id]}",
                                            extra={
                                                "emoji": ":alarm_clock:",
                                                "event": Events.BET_START,
                                                "links": {
                                                    ws.events_predictions[event_id].streamer.printable_display_name:
                                                        ws.events_predictions[event_id].streamer.streamer_url
                                                }
                                            },
                                        )
                                    else:
                                        logger.info(
                                            f"{streamer} have only {streamer.channel_points} "
                                            f"channel points and the minimum for bet is: {minimum_points}",
                                            extra={
                                                "emoji": ":pushpin:",
                                                "event": Events.BET_FILTERS,
                                            },
                                        )

                        elif (
                            message.type == "event-updated"
                            and event_id in ws.events_predictions
                        ):
                            ws.events_predictions[event_id].status = event_status
                            # Game over we can't update anymore the values... The bet was placed!
                            if (
                                ws.events_predictions[event_id].bet_placed is False
                                and ws.events_predictions[event_id].bet.decision == {}
                            ):
                                ws.events_predictions[event_id].bet.update_outcomes(
                                    event_dict["outcomes"]
                                )

                    elif message.topic == "predictions-user-v1":
                        event_id = message.data["prediction"]["event_id"]
                        if event_id in ws.events_predictions:
                            event_prediction = ws.events_predictions[event_id]
                            if (
                                message.type == "prediction-result"
                                and event_prediction.bet_confirmed
                            ):
                                points = event_prediction.parse_result(
                                    message.data["prediction"]["result"]
                                )

                                decision = event_prediction.bet.get_decision()
                                choice = event_prediction.bet.decision["choice"]

                                logger.info(
                                    (
                                        f"{event_prediction} - Decision: {choice}: {decision['title']} "
                                        f"({decision['color']}) - Result: {event_prediction.result['string']}"
                                    ),
                                    extra={
                                        "emoji": ":bar_chart:",
                                        "event": Events.get(
                                            f"BET_{event_prediction.result['type']}"
                                        ),
                                        "links": {event_prediction.streamer.printable_display_name:
                                                  event_prediction.streamer.streamer_url}
                                    },
                                )

                                streamer.update_history("PREDICTION", points["gained"])

                                # Remove duplicate history records from previous message sent
                                # in community-points-user-v1
                                if event_prediction.result["type"] == "REFUND":
                                    streamer.update_history(
                                        "REFUND",
                                        -points["placed"],
                                        counter=-1,
                                    )
                                elif event_prediction.result["type"] == "WIN":
                                    streamer.update_history(
                                        "PREDICTION",
                                        -points["won"],
                                        counter=-1,
                                    )

                                if event_prediction.result["type"]:
                                    # Analytics switch
                                    if Settings.enable_analytics:
                                        streamer.persistent_annotations(
                                            event_prediction.result["type"],
                                            f"{ws.events_predictions[event_id].title}",
                                        )
                            elif message.type == "prediction-made":
                                event_prediction.bet_confirmed = True
                                # Analytics switch
                                if Settings.enable_analytics:
                                    streamer.persistent_annotations(
                                        "PREDICTION_MADE",
                                        f"Decision: {event_prediction.bet.decision['choice']} - "
                                        f"{event_prediction.title}",
                                    )

                except Exception:
                    logger.error(
                        f"Exception raised for topic: {message.topic} and message: {message}",
                        exc_info=True,
                    )

        elif response["type"] == "RESPONSE" and len(response.get("error", "")) > 0:
            # raise RuntimeError(f"Error while trying to listen for a topic: {response}")
            error_message = response.get("error", "")
            logger.error(f"Error while trying to listen for a topic: {error_message}")
            
            # Check if the error message indicates an authentication issue (ERR_BADAUTH)
            if "ERR_BADAUTH" in error_message:
                # Inform the user about the potential outdated cookie file
                logger.error(f"Received the ERR_BADAUTH error, most likely you have an outdated cookie file"
                             f" \"cookies\\{ws.twitch.twitch_login.username}.pkl\". Delete this file and try again.")
                # Attempt to delete the outdated cookie file
                # try:
                #     cookie_file_path = os.path.join("cookies", f"{username}.pkl")
                #     if os.path.exists(cookie_file_path):
                #         os.remove(cookie_file_path)
                #         logger.info(f"Deleted outdated cookie file for user: {username}")
                #     else:
                #         logger.warning(f"Cookie file not found for user: {username}")
                # except Exception as e:
                #     logger.error(f"Error occurred while deleting cookie file: {str(e)}")

        elif response["type"] == "RECONNECT":
            logger.info(f"#{ws.index} - Reconnection required")
            WebSocketsPool.handle_reconnection(ws)

        elif response["type"] == "PONG":
            ws.last_pong_tm = time.time()
