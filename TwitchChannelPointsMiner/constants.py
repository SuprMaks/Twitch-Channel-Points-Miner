from enum import Enum
import urllib3.request

# Twitch endpoints
HOST = "www.twitch.tv"
URL = f"https://{HOST}"
IRC = "irc.chat.twitch.tv"
IRC_PORT = 6667
WEBSOCKET = "wss://pubsub-edge.twitch.tv/v1"
CLIENT_ID = "ue6666qo983tsx6so1t0vnawi233wa"        # TV
# CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"      # Browser
# CLIENT_ID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"     # Android App
# CLIENT_ID = "851cqzxpb9bqu9z6galo155du"           # iOS App
DROP_ID = "c2542d6d-cd10-4532-919b-3d19f30a768b"
# CLIENT_VERSION = "32d439b2-bd5b-4e35-b82a-fae10b04da70"  # Android App
CLIENT_VERSION = "ef928475-9403-42f2-8a34-55784bd08e16"  # Browser

USER_AGENTS = {
    "Windows": {
        'CHROME': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        "FIREFOX": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:84.0) Gecko/20100101 Firefox/84.0",
    },
    "Linux": {
        "CHROME": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.96 Safari/537.36",
        "FIREFOX": "Mozilla/5.0 (X11; Linux x86_64; rv:85.0) Gecko/20100101 Firefox/85.0",
    },
    "Android": {
        # "App": "Dalvik/2.1.0 (Linux; U; Android 7.1.2; SM-G975N Build/N2G48C) tv.twitch.android.app/13.4.1/1304010"
        "App": "Dalvik/2.1.0 (Linux; U; Android 7.1.2; SM-G977N Build/LMY48Z) tv.twitch.android.app/14.3.2/1403020",
        "TV": "Mozilla/5.0 (Linux; Android 7.1; Smart Box C1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
    }
}

BRANCH = "master"
GITHUB_url = (
    "https://raw.githubusercontent.com/rdavydov/Twitch-Channel-Points-Miner-v2/"
    + BRANCH
)


RETRY_STRATEGY = urllib3.util.Retry(
    total=5,
    connect=3,
    redirect=3,
    # raise_on_redirect=False,
    status=3,
    # other=5,
    respect_retry_after_header=True,
    backoff_factor=2)

# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
TWITCH_POOL = urllib3.PoolManager(retries=RETRY_STRATEGY,
                                  timeout=urllib3.Timeout(total=5),
                                  num_pools=10,
                                  maxsize=2,
                                  block=True)


class GQLConst(str, Enum):
    url = "https://gql.twitch.tv/gql"
    integrity_url = "https://gql.twitch.tv/integrity"

    def __str__(self):
        return self.value
