#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# (c) 2013 Chris Betz
import logging
logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    import simplejson as json
except ImportError:
    import json

import inspect
import time
import requests

__version__ = 0.2
__author__ = u'Christopher Betz'

AUTH_ENDPOINT = 'https://untappd.com/oauth/authenticate/'
TOKEN_ENDPOINT = 'https://untappd.com/oauth/authorize/'
API_ENDPOINT = 'https://api.untappd.com/v4'

# Number of times to retry http requests
NUM_REQUEST_RETRIES = 3

# Generic untappd exception
class UntappdException(Exception): pass
# Specific exceptions
class InvalidAuth(UntappdException): pass

ERROR_TYPES = {
    'invalid_auth': InvalidAuth
}

class Untappd(object):
    """Untappd V4 API wrapper"""

    def __init__(self, client_id=None, client_secret=None, redirect_url=None,):
        """Sets up the api object"""
        # Set up requester
        self.requester = self.Requester(client_id, client_secret)
        # Set up OAuth
        self.oauth = self.OAuth(self.requester, client_id, client_secret, redirect_url)
        # Dynamically enable endpoints
        self._attach_endpoints()

    def _attach_endpoints(self):
        """Dynamically attach endpoint callables to this client"""
        for name, endpoint in inspect.getmembers(self):
            if inspect.isclass(endpoint) and issubclass(endpoint, self._Endpoint) and (endpoint is not self._Endpoint):
                endpoint_instance = endpoint(self.base_requester)
                setattr(self, endpoint_instance.endpoint, endpoint_instance)

    def set_access_token(self, access_token):
        """Update the access token to use"""
        self.requester.set_access_token(access_token)

    class OAuth(object):
        """Handles OAuth authentication procedures and helps retrieve tokens"""
        def __init__(self, requester, client_id, client_secret, redirect_url):
            self.requester = requester
            self.client_id = client_id
            self.client_secret = client_secret
            self.redirect_url = redirect_url

        def get_auth_url(self):
            """Gets the url a user needs to access to give up a user token"""
            data = {
                'client_id': self.client_id,
                'response_type': u'code',
                'redirect_url': self.redirect_url,
            }
            return '{AUTH_ENDPOINT}?{params}'.format(AUTH_ENDPOINT=AUTH_ENDPOINT, params=urllib.urlencode(data))

        def get_access_token(self, code):
            """Gets the auth token from a user's response"""
            if not code:
                logging.error(u'Code not provided')
                return None
            payload = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': u'authorization_code',
                'redirect_url': self.redirect_url,
                'code': unicode(code),
            }
            # Build the token uri to request
            url = u'{TOKEN_ENDPOINT}?{params}'.format(
                TOKEN_ENDPOINT=TOKEN_ENDPOINT,
                params=urllib.urlencode(data))
            logging.debug(u'GET: {0}'.format(url))
            # Get the response from the token uri and attempt to parse
            data = self.requester.GET(TOKEN_ENDPOINT, payload=payload, enrich_payload=False)
            return data.get('response').get('access_token')


    class Requester(object):
        """Api requesting object"""
        def __init__(self, client_id=None, client_secret=None):
            """Sets up the api object"""
            self.client_id = client_id
            self.client_secret = client_secret
            self.userless = True

        def set_access_token(self, access_token):
            """Set the OAuth token for this requester"""
            self.access_token = access_token
            self.userless = False

        def GET(self, url, **kwargs):
            """GET request that returns processed data"""
            return self._request('GET', url, **kwargs)

        def POST(self, url, **kwargs):
            """POST request that returns processed data"""
            return self._request('POST', url, **kwargs)

        def _enrich_payload(self, payload={}):
            """Enrich the payload dict"""
            if self.userless:
                payload['client_id'] = self.client_id
                payload['client_secret'] = self.client_secret
            else:
                payload['access_token'] = self.access_token
            return payload

        def _request(self, method, url, **kwargs):
            """Performs the passed request and returns meaningful data"""
            if kwargs is None:
                kwargs = {}
            url = '{url}{path}'.format(url=url, path=kwargs.get('path'))
            if kwargs.get('enrich_payload', True):
                payload = self._enrich_payload(kwargs.get('payload', {}))
            else:
                payload = kwargs.get('payload')
            logging.debug(u'{method} url: {url} payload:{payload}'.format(method=method, url=url, payload=u'* {0}'.format(payload) if payload else u''))
            """Tries to load data from an endpoint using retries"""
            try_number = 1
            while try_number <= NUM_REQUEST_RETRIES:
                try:
                    return self._process_request(method, url, payload)
                except UntappdException as e:
                    # Some errors don't bear repeating
                    if e.__class__ in [InvalidAuth]: raise
                    if (try_number == NUM_REQUEST_RETRIES): raise
                    try_number += 1
                time.sleep(1)

        def _process_request(self, method, url, payload):
            try:
                if method == 'GET':
                    response = requests.get(url, params=payload)
                else if method == 'POST':
                    response = requests.post(url, data=payload)
                else:
                    error_message = u'Invalid request method'
                    logging.error(error_message)
                    raise UntappdException(error_message)
                data = self._convert_json_to_data(response)
                if response.status_code == requests.codes.ok:
                    return data
                return self._check_response(data)

            except requests.exceptions.RequestException as e:
                logging.error(e)
                raise UntappdException(u'Error connecting with Untappd API')

        def _convert_json_to_data(json_string):
            """Convert a response string to data"""
            try:
                return json.loads(json_string)
            except ValueError as e:
                logging.error('Invalid response: {0}'.format(e))
                raise UntappdException(e)

        def _check_response(data):
            """Processes the response data"""
            # Check the meta-data for why this request failed
            meta = data.get('meta')
            if meta:
                # see: https://untappd.com/api/docs/v4
                if meta.get('code') in (200, 409): return data
                exc = ERROR_TYPES.get(meta.get('error_type'))
                if exc:
                    raise exc(meta.get('error_detail'))
                else:
                    logging.error(u'Unknown error type: {0}'.format(meta.get('error_type')))
                    raise UntappdException(meta.get('error_detail'))
            else:
                logging.error(u'Response format invalid, missing meta property') # body is printed in warning above
                raise UntappdException('Missing meta')

    class _Endpoint(object):
        """Generic endpoint class"""
        def __init__(self, requester):
            """Stores the request function for retrieving data"""
            self.requester = requester

        def __call__(self, id):
            return self.GET('info/{id}'.format(id=id))

        def search(self, query, **kwargs):
            if not self.searchable:
                error_message = u'This Untappd API endpoint is not searchable'
                logging.error(error_message)
                raise UntappdException(error_message)
            payload = {'q' : query}
            if kwargs and self.search_options:
                for option in self.search_options:
                    if option in kwargs:
                        payload[option] = kwargs[option]
            return self.GET('search', payload=payload, reverse_parts=True)

        def _expand_path(self, path=None, reverse_parts=False):
            """Gets the expanded path, given this endpoint"""
            if reverse_parts:
                parts = (path, self.endpoint)
            else:
                parts = (self.endpoint, path)
            return '/{expanded_path}'.format(expanded_path='/'.join(p for p in parts if p))

        def GET(self, path=None, **kwargs):
            """Use the requester to get the data"""
            reverse_parts = kwargs.pop('reverse_parts', False)
            return self.requester.GET(API_ENDPOINT, path=self._expand_path(path, reverse_parts), **kwargs)

        def POST(self, path=None, **kwargs):
            """Use the requester to post the data"""
            reverse_parts = kwargs.pop('reverse_parts', False)
            return self.requester.POST(API_ENDPOINT, path=self._expand_path(path, reverse_parts), **kwargs)

    class Beer(_Endpoint):
        endpoint = 'beer'
        searchable = True
        search_options = ('offset', 'limit', 'sort')

    class User(_Endpoint):
        endpoint = 'user'
        searchable = False

    class Venue(_Endpoint):
        endpoint = 'venue'
        searchable = False

    class Brewery(_Endpoint):
        endpoint = 'brewery'
        searchable = True
        search_options = ('offset', 'limit')
