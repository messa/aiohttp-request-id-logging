'''
Adds a request (correlation) id to log messages in aiohttp web applications.

See README.md for usage and reference documentation.
'''

from asyncio import CancelledError
from os import getpid
from aiohttp import web
from aiohttp.web_exceptions import HTTPException
from aiohttp.web_log import AccessLogger as _AccessLogger
from contextvars import ContextVar
from contextlib import ExitStack
import logging
import warnings
from secrets import token_urlsafe

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None


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


class RequestIdKeyAlreadySetError (Exception):
    '''
    Raised when the request already contains a request id.

    This most likely means that request_id_middleware is applied twice,
    or that something else also sets the request id in the request.
    '''

    def __init__(self, existing_request_id):
        super().__init__(
            f'The request already contains request id {existing_request_id!r} - '
            'request_id_middleware is most likely applied twice, '
            'or something else also sets the request id')
        self.existing_request_id = existing_request_id


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


class RequestIdMiddleware:
    '''
    aiohttp middleware that generates a request id for every request,
    stores it in the request_id ContextVar and in the request
    (request[REQUEST_ID_KEY]), and - if sentry_sdk is installed - creates
    a Sentry scope with a request_id tag.

    Constructor parameters (all keyword-only):

    - request_id_factory: zero-argument callable returning the request id
      string; default: random_request_id_factory
    - log_request_start: log the "Processing GET / (...)" message at the
      start of each request; default: True
    - log_function_name: include the handler name in the request start
      message; default: True

    The behavior can be customized by subclassing and overriding methods:
    before_request, call_handler, after_request, log_request_start_message,
    set_request_keys, setup_sentry_scope, get_function_name.

    request_id_middleware is a backward compatibility alias of this class.
    '''

    __middleware_version__ = 1  # aiohttp 3 needs this; this is what @web.middleware is setting

    def __init__(
        self,
        *,
        request_id_factory=None,
        log_request_start=True,
        log_function_name=True,
    ):
        assert isinstance(log_request_start, bool)
        assert isinstance(log_function_name, bool)
        self.request_id_factory = request_id_factory or default_request_id_factory
        self.log_request_start = log_request_start
        self.log_function_name = log_function_name
        self.request_id_cv = request_id
        self.sentry_make_scope = _resolve_sentry_make_scope()

    async def __call__(self, request, handler):
        """
        The middleware entrypoint - process one request.

        Sets the request_id ContextVar for the whole duration of the request
        processing and delegates the rest to before_request, call_handler
        and after_request.
        """
        req_id = self.request_id_factory()
        with ExitStack() as stack:
            # Set request id context variable as a first thing
            token = self.request_id_cv.set(req_id)
            stack.callback(lambda: self.request_id_cv.reset(token))

            await self.before_request(request, handler, req_id, stack)
            response = await self.call_handler(request, handler, req_id, stack)
            await self.after_request(request, handler, response, req_id, stack)
            return response

    async def before_request(self, request, handler, req_id, stack):
        """
        Called before the handler: set up the Sentry scope, log the request
        start message and store the request id in the request.

        The stack parameter (a contextlib.ExitStack) can be used to register
        cleanup that runs after the request is processed.
        """
        # Sentry scope comes first so that the following log messages
        # are captured in it (as breadcrumbs).
        self.setup_sentry_scope(req_id, stack)
        if self.log_request_start:
            self.log_request_start_message(request, handler)
        self.set_request_keys(request, req_id)

    async def call_handler(self, request, handler, req_id, stack):
        """
        Call handler and return response.

        If handler raises an exception, convert it to response object.
        """
        try:
            response = await handler(request)
        except CancelledError as e:
            logger.info('(Cancelled)')
            raise e
        except HTTPException as e:
            response = e
        except Exception as e:
            # We are processing 500 error right here, because if we let it
            # the web server to process, it would be outside of the request_id
            # contextvar scope.
            # (And also outside the sentry scope, if sentry is enabled.)
            logger.exception("Error handling request: %r", e)
            response = web.Response(
                status=500,
                text="500 Internal Server Error\n")
            response.force_close()
        return response

    async def after_request(self, request, handler, response, req_id, stack):
        """
        Called after the handler returns (or its exception is converted
        to a response). Does nothing by default - a hook for subclasses.
        """
        pass

    def log_request_start_message(self, request, handler):
        """
        Log the "Processing GET / (...)" message at the start of the request.
        """
        if self.log_function_name:
            logger.info('Processing %s %s (%s)', request.method, request.path, self.get_function_name(handler))
        else:
            logger.info('Processing %s %s', request.method, request.path)

    def set_request_keys(self, request, req_id):
        """
        Set request["request_id"] - both str and AppKey keys
        """
        if REQUEST_ID_KEY in request:
            raise RequestIdKeyAlreadySetError(request[REQUEST_ID_KEY])
        request[REQUEST_ID_KEY] = req_id
        if type(REQUEST_ID_KEY) is not str:
            # Store the request id also under the plain string key for
            # backward compatibility with code reading request['request_id'].
            # aiohttp 3.13/3.14 emits NotAppKeyWarning for str keys
            # (the warning is being removed again in aiohttp master),
            # so silence it here.
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', getattr(web, 'NotAppKeyWarning', UserWarning))
                if "request_id" in request:
                    raise RequestIdKeyAlreadySetError(request["request_id"])
                request['request_id'] = req_id

    def setup_sentry_scope(self, req_id, stack):
        """
        Create a new Sentry scope (entered into the given ExitStack)
        and add the request_id tag to it.

        Does nothing if sentry_sdk is not installed.
        """
        if self.sentry_make_scope is not None:
            scope = stack.enter_context(self.sentry_make_scope())
            scope.set_tag('request_id', req_id)

    @staticmethod
    def get_function_name(f):
        """
        Return a human-readable handler name for the request start message.
        """
        try:
            return f'{f.__module__}:{f.__name__}'
        except Exception:
            return str(f)


# old name for backward compatibility - request_id_middleware() used to be
# a factory function returning the middleware
request_id_middleware = RequestIdMiddleware
