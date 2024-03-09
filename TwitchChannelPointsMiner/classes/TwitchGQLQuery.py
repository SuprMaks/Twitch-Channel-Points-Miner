from enum import Enum
from typing import Optional


class TwitchGQLQuery:
    __slots__ = [
        "_query"
    ]

    def __init__(self, q: dict, v: Optional[dict] = None):
        t = q.copy()
        if v:
            t['variables'] = v.copy()
        self._query = [t]

    def __call__(self, q: dict, v: Optional[dict] = None):
        t = q.copy()
        if v:
            t['variables'] = v.copy()
        self._query.append(t)
        return self

    def query(self):
        return self._query.copy()


class TwitchGQLQuerys(dict, Enum):
    WithIsStreamLiveQuery = {
        "operationName": "WithIsStreamLiveQuery",
        "sha256Hash": "04e46329a6786ff3a81c01c50bfa5d725902507a0deb83b0edbf7abe7a3716ea",
    }
    VideoPlayerStreamInfoOverlayChannel = {
        "operationName": "VideoPlayerStreamInfoOverlayChannel",
        "sha256Hash": "a5f2e34d626a9f4f5c0204f910bab2194948a9502089be558bb6e779a9e1b3d2",
    }
    ClaimCommunityPoints = {
        "operationName": "ClaimCommunityPoints",
        "sha256Hash": "46aaeebe02c99afdf4fc97c7c0cba964124bf6b0af229395f1f6d1feed05b3d0",
    }
    CommunityMomentCallout_Claim = {
        "operationName": "CommunityMomentCallout_Claim",
        "sha256Hash": "e2d67415aead910f7f9ceb45a77b750a1e1d9622c936d832328a0689e054db62",
    }
    DropsPage_ClaimDropRewards = {
        "operationName": "DropsPage_ClaimDropRewards",
        "sha256Hash": "a455deea71bdc9015b78eb49f4acfbce8baa7ccbedd28e549bb025bd0f751930",
    }
    ChannelPointsContext = {
        "operationName": "ChannelPointsContext",
        "sha256Hash": "1530a003a7d374b0380b79db0be0534f30ff46e61cffa2bc0e2468a909fbc024",
    }
    JoinRaid = {
        "operationName": "JoinRaid",
        "sha256Hash": "c6a332a86d1087fbbb1a8623aa01bd1313d2386e7c63be60fdb2d1901f01a4ae",
    }
    ModViewChannelQuery = {
        "operationName": "ModViewChannelQuery",
        "sha256Hash": "df5d55b6401389afb12d3017c9b2cf1237164220c8ef4ed754eae8188068a807",
    }
    Inventory = {
        "operationName": "Inventory",
        "sha256Hash": "37fea486d6179047c41d0f549088a4c3a7dd60c05c70956a1490262f532dccd9",
        "variables": {"fetchRewardCampaigns": True},
    }
    MakePrediction = {
        "operationName": "MakePrediction",
        "sha256Hash": "b44682ecc88358817009f20e69d75081b1e58825bb40aa53d5dbadcc17c881d8",
    }
    ViewerDropsDashboard = {
        "operationName": "ViewerDropsDashboard",
        "sha256Hash": "8d5d9b5e3f088f9d1ff39eb2caab11f7a4cf7a3353da9ce82b5778226ff37268",
        "variables": {"fetchRewardCampaigns": True},
    }
    DropCampaignDetails = {
        "operationName": "DropCampaignDetails",
        "sha256Hash": "f6396f5ffdde867a8f6f6da18286e4baf02e5b98d14689a69b5af320a4c7b7b8",
    }
    DropsHighlightService_AvailableDrops = {
        "operationName": "DropsHighlightService_AvailableDrops",
        "sha256Hash": "9a62a09bce5b53e26e64a671e530bc599cb6aab1e5ba3cbd5d85966d3940716f",
    }
    ReportMenuItem = {  # Use for replace https://api.twitch.tv/helix/users?login={self.username}
        "operationName": "ReportMenuItem",
        "sha256Hash": "8f3628981255345ca5e5453dfd844efffb01d6413a9931498836e6268692a30c",
    }
    PersonalSections = {
            "operationName": "PersonalSections",
            "sha256Hash": "9fbdfb00156f754c26bde81eb47436dee146655c92682328457037da1a48ed39",
            "variables": {
                "input": {
                    "sectionInputs": ["FOLLOWED_SECTION"],
                    "recommendationContext": {"platform": "web"},
                },
                "channelLogin": None,
                "withChannelUser": False,
                "creatorAnniversariesExperimentEnabled": False,
            },
    }
    ChannelFollows = {
        "operationName": "ChannelFollows",
        "sha256Hash": "eecf815273d3d949e5cf0085cc5084cd8a1b5b7b6f7990cf43cb0beadf546907",
        "variables": {"limit": 100, "order": "ASC"},
    }
    RealtimeStreamTagList = {
        "operationName": "RealtimeStreamTagList",
        "sha256Hash": "9d952e4aacd4f8bb9f159bd4d5886d72c398007249a8b09e604a651fc2f8ac17",
        "variables": {
            "channelLogin": ""
        },
    }
