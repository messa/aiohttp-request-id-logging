'''
Adds a request (correlation) id to log messages in aiohttp web applications.

See README.md for usage and reference documentation.
'''

from os import getpid
from aiohttp import web
from aiohttp.web_log import AccessLogger as _AccessLogger
from contextvars import ContextVar
import logging
import warnings
from secrets import token_urlsafe

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

from .errors import RequestIdKeyAlreadySetError  # noqa: F401


# contextvar that contains given request tracing id
request_id = ContextVar('request_id')

try:
    # key for storing the request id in the request; aiohttp recommends
    # web.RequestKey instances instead of plain strings
    REQUEST_ID_KEY = web.RequestKey('request_id', str)
except AttributeError:
    # older aiohttp without web.RequestKey
    REQUEST_ID_KEY = 'request_id'

request_id_default_length = 7

logger = logging.getLogger(__name__)


def setup_logging_request_id_prefix():
    '''
    Wrap logging record factory so that every log record gets two extra attributes:

    - record.requestIdPrefix - "[req:...] ", or an empty string outside of a request
    - record.request_id - the raw request id, or None

    You can then use them in log format as "%(requestIdPrefix)s" or "%(request_id)s".

    Safe to call multiple times - the setup is done only once.
    '''
    # make sure we are doing this only once
    if getattr(logging, 'request_id_log_record_factory_set_up', False):
        return
    logging.request_id_log_record_factory_set_up = True

    old_factory = logging.getLogRecordFactory()

    def new_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        req_id = request_id.get(None)
        record.request_id = req_id
        record.requestIdPrefix = f'[req:{req_id}] ' if req_id else ''
        return record

    logging.setLogRecordFactory(new_factory)


class RequestIdContextAccessLogger (_AccessLogger):
    '''
    Subclass of aiohttp.web_log.AccessLogger that sets the request_id
    ContextVar while writing the access log line.

    Needed because aiohttp writes the access log outside of the middleware
    scope, where the ContextVar is already reset.

    Usage: run_app(app, access_log_class=RequestIdContextAccessLogger)
    '''

    def log(self, request, response, time):
        try:
            request_id_value = request[REQUEST_ID_KEY]
        except KeyError:
            # If there is no request[REQUEST_ID_KEY], for example when an error
            # occurs in a middleware, fall back to just logging without setting
            # the request_id context variable.
            super().log(request, response, time)
            return

        token = request_id.set(request_id_value)
        try:
            super().log(request, response, time)
        finally:
            request_id.reset(token)


def random_request_id_factory():
    '''
    Generate a random request id - a URL-safe string of length
    request_id_default_length.

    This is the default request id factory used in RequestIdMiddleware.
    '''
    req_id = token_urlsafe(request_id_default_length)[:request_id_default_length]
    req_id = req_id.replace('_', 'x').replace('-', 'X')
    return req_id


# old name for backward compatibility
generate_request_id = random_request_id_factory


class SequentialRequestIdFactory:
    '''
    Alternative request id factory producing ids like "Wxyz0001", "Wxyz0002"...
    - a random per-process prefix followed by a sequential number.

    Usage: RequestIdMiddleware(request_id_factory=sequential_request_id_factory)

    Caveat: if the request ids are ever exposed to clients (response header,
    error page...), sequential ids reveal how many requests the server
    processes and how many server processes there are. If that is a concern,
    use the default random_request_id_factory instead.
    '''

    prefix_length = 4

    def __init__(self):
        self._pid = None
        self._prefix = None
        self._next_value = None

    def __call__(self):
        pid = getpid()
        if pid != self._pid:
            self._prefix = self._generate_prefix()
            self._next_value = 0
            self._pid = pid
        value = self._next_value
        self._next_value += 1
        return f'{self._prefix}{value:04}'

    @classmethod
    def _generate_prefix(cls):
        while True:
            prefix = token_urlsafe(cls.prefix_length)[:cls.prefix_length]
            if '_' in prefix or '-' in prefix:
                continue
            # Let's not have any numbers in the prefix so we keep more focus on the appended request number.
            # This is just aesthetic thing.
            if any(c.isdigit() for c in prefix):
                continue
            if 'l' in prefix or 'I' in prefix:
                continue
            return prefix


sequential_request_id_factory = SequentialRequestIdFactory()


default_request_id_factory = random_request_id_factory


def _resolve_sentry_make_scope():
    '''
    Find the function for creating a new Sentry scope, or return None
    if sentry_sdk is not installed (or provides no such function).

    For compatibility with sentry_sdk 1.x and 2.x:
    push_scope is deprecated and will be removed, isolation_scope is its
    recommended replacement for the request-response cycle.
    '''
    if sentry_sdk is None:
        return None
    try:
        return sentry_sdk.isolation_scope
    except AttributeError:
        pass
    try:
        return sentry_sdk.push_scope
    except AttributeError:
        warnings.warn(
            "sentry_sdk does not contain isolation_scope or push_scope. "
            "This is most likely due to a version change to >2.x, "
            "please consult the Sentry documentation on how to fix this. "
            "The `request_id` tag will not be pushed to Sentry.",
            UserWarning,
        )
        return None


# This import must stay at the end of the file - middleware.py imports
# names defined above from this package.
from .middleware import RequestIdMiddleware, request_id_middleware  # noqa: E402,F401
