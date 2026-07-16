from asyncio import CancelledError
from contextlib import ExitStack
from logging import getLogger
import warnings

from aiohttp import web
from aiohttp.web_exceptions import HTTPException

from .errors import RequestIdKeyAlreadySetError

# These names live in the package __init__ (tests monkeypatch e.g. sentry_sdk
# there); this works because __init__ imports this module as its last statement.
from . import (
    request_id,
    REQUEST_ID_KEY,
    default_request_id_factory,
    _resolve_sentry_make_scope,
)


logger = getLogger(__name__)


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
