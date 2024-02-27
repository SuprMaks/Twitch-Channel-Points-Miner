import requests
from time import sleep
from logging import getLogger

logger = getLogger(__name__)


def retransmit(timeout: int):
    r"""
    Trys to call request in loop in case of some error during period of timeout,
    until good response will be received with status code 200

    :param timeout:
    :return:
    """
    def actual_decorator(func):
        def wrapper(*args, **kwargs):
            incr = 0
            while True:
                try:
                    response = func(*args, **kwargs)
                    if response.status_code == 200:
                        return response
                    elif (delay := (1 << (incr := incr + 1))) <= timeout:
                        logger.debug(f"Wrong response status code {response.status_code}, trying to resend {func.__name__}:'{args[0]}' one more time in {delay} sec")
                        sleep(delay)
                    else:
                        return response
                except requests.exceptions.RequestException as e:
                    if (delay := (1 << (incr := incr + 1))) <= timeout:
                        logger.debug(f"Request timeout, trying to resend {func.__name__}:'{args[0]}' one more time in {delay} sec")
                        sleep(delay)
                    else:
                        raise requests.exceptions.RequestException from e
        return wrapper
    return actual_decorator


@retransmit(2 << 6)
def post(url, data=None, json=None, **kwargs):
    return requests.post(url, data=data, json=json, **kwargs)


@retransmit(2 << 6)
def get(url, params=None, **kwargs):
    return requests.get(url, params=params, **kwargs)
