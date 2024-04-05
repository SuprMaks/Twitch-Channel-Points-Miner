import json
import urllib3.request

from logging import getLogger
from plum import dispatch
from typing import Optional

from TwitchChannelPointsMiner.classes.TwitchGQLQuery import TwitchGQLQuery
from TwitchChannelPointsMiner.constants import GQLConst

logger = getLogger(__name__)


class TwitchGQL(object):
    __slots__ = ['_pool', '_url', 'headers', '_timeout', '_method']

    def __init__(self, pool: urllib3.PoolManager, url: str = GQLConst.url,
                 headers: Optional[dict] = None, timeout=4, method='POST'):
        self._url = url
        self.headers = headers or {}
        self._timeout = timeout
        self._method = method.upper()
        self._pool = pool

    @dispatch
    def __call__(
            self,
            operation_name,
            sha256_hash,
            variables=None,
            timeout=None,
    ):
        headers = self.headers.copy()

        if 'Accept' not in headers:
            headers['Accept'] = 'application/json; charset=utf-8'

        if self._method == 'POST':
            get_data = self.prepare_http_post
            get_http_request = self._get_http_post_request
        else:
            get_data = self.prepare_http_get
            get_http_request = self._get_http_get_request

        return self._exec_req(headers,
                              get_http_request(get_data(operation_name, sha256_hash, variables), headers),
                              timeout)

    @dispatch
    def __call__(self, query: dict, variables=None, timeout=None):
        operation_name = None
        sha256_hash = None
        if 'operationName' in query:
            operation_name = query['operationName']
            sha256_hash = query['sha256Hash']
            if 'variables' in query:
                variables = variables or query['variables']
        else:
            pass
        return self.__call__(operation_name, sha256_hash, variables, timeout)

    @dispatch
    def __call__(self, q: list, timeout=None) -> dict:
        headers = self.headers.copy()

        if 'Accept' not in headers:
            headers['Accept'] = 'application/json; charset=utf-8'

        if len(q) == 1:
            q = q[0]
            return self.__call__(q, None, timeout)
        else:
            if self._method == 'POST':
                get_data = self.prepare_http_post
                get_http_request = self._get_http_post_request
            else:
                get_data = self.prepare_http_get
                get_http_request = self._get_http_get_request

            pr_q = [get_data(rq['operationName'],
                             rq['sha256Hash'],
                             rq['variables'] if 'variables' in rq else None) for rq in q]

            resp = self._exec_req(headers, get_http_request(pr_q, headers), timeout)

            out = {}
            for i in range(0, len(resp)):
                out[pr_q[i]['operationName']] = resp[i]
            return out

    @dispatch
    def __call__(self, query: TwitchGQLQuery, timeout=None) -> dict:
        return self.__call__(query.query())

    def _exec_req(self, headers, payload, timeout):
        logger.debug('Query:\n%s', payload)
        try:
            data = json.loads(self._pool.request(method='POST', url=self._url, headers=headers,
                                                 body=payload, timeout=timeout or self._timeout).data.decode('utf-8'))
        # except urllib3.exceptions.HTTPError as e:
        #     logger.error(
        #         f"Error with TwitchGQL request req ({payload}): {e}"
        #     )
        #     raise urllib3.exceptions.HTTPError from e

        except json.JSONDecodeError as e:
            logger.error(
                f"Error with TwitchGQL json decode req ({payload}): {e}"
            )
            raise json.JSONDecodeError from e

        def check_out_data(data):
            if data:
                if isinstance(data, dict):
                    if e := data.get('errors'):
                        if (isinstance(e, list) and len(e) == 1 and
                                (path := e[0]['path']) and (e := e[0]['message'].lower())):
                            if e == 'service timeout':
                                logger.error(f"TwitchGQL {e} path: {path}")
                            else:
                                logger.error(f"TwitchGQL {e} path: {path} {payload}")
                        else:
                            logger.error(
                                f"{e} in TwitchGQL response data {payload}"
                            )

        if data:
            if isinstance(data, dict):
                check_out_data(data)
            elif isinstance(data, list):
                for rec in data:
                    check_out_data(rec)
        return data

    @staticmethod
    def prepare_http_post(operation_name, sha256_hash, variables):
        params = {'operationName': operation_name}
        if variables:
            params['variables'] = variables
        params['extensions'] = {
            'persistedQuery': {
                'version': 1,
                'sha256Hash': sha256_hash,
            }
        }

        return params

    @staticmethod
    def prepare_http_get(operation_name, sha256_hash, variables):
        params = {}
        if operation_name:
            params['operationName'] = operation_name

        if variables:
            params['variables'] = json.dumps(variables)
        return json.dumps(params).encode('utf-8')

    def _get_http_post_request(self, post_data, headers):
        post_data = json.dumps(post_data).encode('utf-8')
        # headers.update(
        #     {
        #         'Content-Type': 'application/json; charset=utf-8',
        #         'Content-Length': len(post_data),
        #     }
        # )
        return post_data

        # return (post_data
        #     url=self._url, data=post_data, headers=headers, method='POST'
        # )

    def _get_http_get_request(self, data, headers):
        data = json.dumps(data).encode('utf-8')
        return data
        # return urllib.request.Request(url=self._url, headers=headers, method='GET')
