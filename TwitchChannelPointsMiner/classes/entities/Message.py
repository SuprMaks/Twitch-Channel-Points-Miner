from dateutil import parser
from datetime import datetime, timezone
import json
import time

from TwitchChannelPointsMiner.utils import server_time


class Message(object):
    __slots__ = [
        "topic",
        "topic_user",
        "message",
        "type",
        "data",
        "timestamp",
        "server_timestamp",
        "created_timestamp",
        "channel_id",
        "identifier",
    ]

    def __init__(self, data):
        self.created_timestamp = time.time()

        self.topic, self.topic_user = data["topic"].split(".")

        self.message = json.loads(data["message"])
        self.type = self.message["type"]

        self.data = self.message["data"] if "data" in self.message else None

        self.server_timestamp = self._get_timestamp()
        self.timestamp = datetime.fromtimestamp(self.server_timestamp
                                                if self.server_timestamp
                                                else self.created_timestamp, timezone.utc).isoformat() + "Z"
        self.channel_id = self.__get_channel_id()

        self.identifier = f"{self.type}.{self.topic}.{self.channel_id}"

    def __repr__(self):
        return f"{self.message}"

    def __str__(self):
        return f"{self.message}"

    @property
    def server_timestamp_diff(self):
        return self.created_timestamp - self.server_timestamp if self.server_timestamp else 0

    @staticmethod
    def _server_timestamp_parse(message_data):
        return message_data["server_time"] if message_data and "server_time" in message_data else None

    def _get_timestamp(self):
        return (parser.isoparse(self.data["timestamp"]).timestamp()
                if "timestamp" in self.data
                else self._server_timestamp_parse(self.data)) \
            if self.data \
            else self._server_timestamp_parse(self.message)

    def __get_channel_id(self):
        return (
            self.topic_user
            if self.data is None
            else (
                self.data["prediction"]["channel_id"]
                if "prediction" in self.data
                else (
                    self.data["claim"]["channel_id"]
                    if "claim" in self.data
                    else (
                        self.data["channel_id"]
                        if "channel_id" in self.data
                        else (
                            self.data["balance"]["channel_id"]
                            if "balance" in self.data
                            else self.topic_user
                        )
                    )
                )
            )
        )
