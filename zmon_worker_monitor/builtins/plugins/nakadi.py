#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import logging

import requests
import tokens
from zmon_worker.common.http import get_user_agent

from zmon_worker_monitor.adapters.ifunctionfactory_plugin import IFunctionFactoryPlugin

logger = logging.getLogger('zmon-worker.scalyr-function')


class NakadiWrapperFactory(IFunctionFactoryPlugin):
    def __init__(self):
        super(NakadiWrapperFactory, self).__init__()
        self.nakadi_url = None
        self.nakadi_token = None

    def configure(self, conf):
        """
        Called after plugin is loaded to pass the [configuration] section in their plugin info file
        :param conf: configuration dictionary
        """
        # will use OAUTH2_ACCESS_TOKEN_URL environment variable by default
        # will try to read application credentials from CREDENTIALS_DIR
        self.nakadi_url = conf.get('nakadi.url', '')
        self.nakadi_token = conf.get('nakadi.oauth2', '')

        tokens.configure()

        token_configuration = conf.get('oauth2.tokens')

        if token_configuration:
            for part in token_configuration.split(':'):
                token_name, scopes = tuple(part.split('=', 1))
                tokens.manage(token_name, scopes.split(','))

        tokens.manage('uid', ['uid'])

        tokens.start()

    def create(self, factory_ctx):
        base_url = factory_ctx.get('url')
        token = factory_ctx.get('oauth2token')

        return NakadiWrapper(base_url or self.nakadi_url, token or self.nakadi_token or 'uid')


def _to_nakadi_message(method, url, r):
    return 'Error {} nakadi url {}: status code: {}, response text: {}'.format(method, url, r.status_code, r.text)


class NakadiException(Exception):
    def __init__(self, method, url, r):
        super(NakadiException, self).__init__(message=_to_nakadi_message(method, url, r))
        self.r = r


class NakadiWrapper(object):
    def __init__(self, url, token):
        self.url = url
        self.token = token

    def __request(self, url, expected_codes=(200,), data=None):
        headers = {
            'Authorization': 'Bearer {}'.format(tokens.get(self.token)),
            'User-Agent': get_user_agent()
        }

        url = '{}/{}'.format(self.url, url)
        if data is None:
            method = 'get'
            r = requests.get(url=url, headers=headers)
        else:
            method = 'post'
            if isinstance(data, dict) or isinstance(data, list) or isinstance(data, tuple):
                data = json.dumps(data)
            headers['Content-Type'] = 'application/json'
            r = requests.post(url=url, headers=headers, data=data)
        if r.status_code not in expected_codes:
            raise NakadiException(method, url, r)
        return r.json()

    def subscription_stats(self, subscription_id):
        # Gets stats for subscription with id subscription_id
        return self.__request('/subscriptions/{}/stats'.format(subscription_id))

    def distance(self, event_type, cursors_begin, cursors_end):
        # Cursors may be array of cursors or single cursors.
        # Each cursor is a nakadi cursor with format
        # {'partition': '0', 'offset': '000'}
        # In case if it is single cursors the result is just a number.
        # In case of array it will return list of distances (numbers) in the same order as they were requested
        single = isinstance(cursors_begin, dict)
        if single:
            cursors_begin = [cursors_begin]
            cursors_end = [cursors_end]

        data = [
            {'initial_cursor': cursors_begin[i], 'final_cursor': cursors_end[i]}
            for i in range(0, len(cursors_begin))
        ]

        response = self.__request('/event-types/{}/cursor-distances'.format(event_type), data=data)
        if single:
            return response[0]['distance']

        return [v['distance'] for v in response]
