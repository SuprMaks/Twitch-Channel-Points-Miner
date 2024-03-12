import json
import logging
import time
import ssl
from websocket import WebSocketApp, ABNF
from threading import Thread

from TwitchChannelPointsMiner.utils import create_nonce
from TwitchChannelPointsMiner.classes.Settings import Settings

logger = logging.getLogger(__name__)


class TwitchWebSocket(Thread, WebSocketApp):
    def __init__(self, index, parent_pool, *args, **kw):
        Thread.__init__(self,
                        name = f"WebSocket #{index}",
                        target=self.run_forever,
                        args=(None, {"cert_reqs": ssl.CERT_NONE} if Settings.disable_ssl_cert_verification else None, ),
                        daemon=True)
        WebSocketApp.__init__(self, *args, **kw)

        # Custom attribute
        self.index = index

        self.parent_pool = parent_pool

        self.is_reconnecting = False
        self.forced_close = False

        self.topics = []
        self.pending_topics = []

        self.twitch = parent_pool.twitch
        self.streamers = parent_pool.streamers
        self.events_predictions = parent_pool.events_predictions

        self.last_message_timestamp = None
        self.last_message_type_channel = None

        self.last_ping_tm = self.last_pong_tm = time.time()

    def __bool__(self):
        return bool(self.sock) and self.sock.connected

    def __request(self, type: str, topic, auth_token=None):
        data = {"topics": [str(topic)]}
        if topic.is_user_topic() and auth_token is not None:
            data["auth_token"] = auth_token
        nonce = create_nonce()
        self.send({"type": type.upper(), "nonce": nonce, "data": data})

    def listen(self, topic, auth_token=None):
        self.__request('LISTEN', topic, auth_token)

    def unlisten(self, topic, auth_token=None):
        self.__request('UNLISTEN', topic, auth_token)

    def send(self, data, opcode=ABNF.OPCODE_TEXT):
        request_str = json.dumps(data, separators=(",", ":"))
        logger.debug(f"#{self.index} - Send: {request_str}")
        super().send(request_str, opcode)

    @property
    def elapsed_last_pong(self):
        if self.last_pong_tm:
            return (time.time() - self.last_pong_tm) // 60
        return 0

    @property
    def elapsed_last_ping(self):
        if self.last_ping_tm:
            return (time.time() - self.last_ping_tm) // 60
        return 0
