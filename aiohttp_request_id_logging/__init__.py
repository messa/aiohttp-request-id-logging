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
    Wrap logging request factory so that every log record gets an attribute
    record.requestIdPrefix.

    You can then use it in log format as "%(requestIdPrefix)s".
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
    Used in request_id_middleware to generate the request id
    '''
    req_id = token_urlsafe(request_id_default_length)[:request_id_default_length]
    req_id = req_id.replace('_', 'x').replace('-', 'X')
    return req_id


# old name for backward compatibility
generate_request_id = random_request_id_factory


class SequentialRequestIdFactory:
    '''
    Can be used in request_id_middleware to generate the request id
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

    __middleware_version__ = 1  # aiohttp 3 needs this; this is what @web.middleware is setting

    def __init__(
        self,
        request_id_factory=None,
        log_function_name=True,
    ):
        self.request_id_factory = request_id_factory or default_request_id_factory
        self.log_function_name = log_function_name
        self.request_id_cv = request_id
        self.sentry_make_scope = _resolve_sentry_make_scope()

    async def __call__(self, request, handler):
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
        # Sentry scope comes first so that the following log messages
        # are captured in it (as breadcrumbs).
        self.setup_sentry_scope(req_id, stack)
        self.log_request_start(request, handler)
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
        pass

    def log_request_start(self, request, handler):
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
        try:
            return f'{f.__module__}:{f.__name__}'
        except Exception:
            return str(f)


# old name for backward compatibility - request_id_middleware() used to be
# a factory function returning the middleware
request_id_middleware = RequestIdMiddleware
