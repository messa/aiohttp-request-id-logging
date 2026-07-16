from aiohttp import web
from aiohttp.web_exceptions import HTTPException
from asyncio import CancelledError
from contextlib import ExitStack
from logging import getLogger
import warnings

from . import random_request_id_factory, REQUEST_ID_KEY, FALLBACK_REQUEST_ID_KEY, request_id, noop
from .errors import RequestIdKeyAlreadySetError


logger = getLogger(__name__)


class RequestIdMiddleware:
    '''
    aiohttp middleware that generates a request id for every request,
    stores it in the request_id ContextVar and in the request
    (request[REQUEST_ID_KEY]), adds an X-Request-Id response header,
    and - if sentry_sdk is installed - creates a Sentry scope with
    a request_id tag.

    Constructor parameters (all keyword-only):

    - request_id_factory: zero-argument callable returning the request id
      string; default: random_request_id_factory
    - log_request_start: callable (request, handler) that logs the request
      start message; default: the log_request_start method logging
      "Processing GET / (...)"; pass noop to disable the message
    - log_function_name: include the handler name in the default request
      start message; default: True
    - add_response_request_id_header: callable (response, req_id) that adds
      the request id header to the response; default: the
      add_response_request_id_header method; pass noop to disable the header
    - request_id_header_name: name of the response header with the request
      id; default: "X-Request-Id"

    Each parameter overrides the method or class attribute of the same name.
    The behavior can also be customized by subclassing - overriding the class
    attributes (request_id_factory, request_id_header_name, log_function_name)
    or the methods: before_request, call_handler, after_request,
    get_response_for_exception, log_request_start, set_request_keys,
    setup_sentry_scope, add_response_request_id_header, get_function_name.

    request_id_middleware is a backward compatibility wrapper function
    creating an instance of this class.
    '''

    __middleware_version__ = 1  # aiohttp 3 needs this; this is what @web.middleware is setting

    # Default values - can be overriden when subclassing
    request_id_factory = staticmethod(random_request_id_factory)
    request_id_header_name = "X-Request-Id"
    log_function_name = True
    request_id_key = REQUEST_ID_KEY
    fallback_request_id_key = FALLBACK_REQUEST_ID_KEY
    request_id_cv = request_id

    def __init__(
        self,
        *,
        request_id_factory=None,
        log_request_start=None,
        log_function_name: bool = None,
        add_response_request_id_header=None,
        request_id_header_name: str = None,
        no_fallback_request_id_key: bool = False,
    ):
        # Set self.request_id_factory
        if request_id_factory is not None:
            self.request_id_factory = request_id_factory
        assert callable(self.request_id_factory)

        # Set self.log_request_start
        if log_request_start is not None:
            self.log_request_start = log_request_start
        assert callable(self.log_request_start)

        # Set self.log_function_name
        if log_function_name is not None:
            self.log_function_name = log_function_name
        assert isinstance(self.log_function_name, bool)

        # Set self.add_response_request_id_header
        if add_response_request_id_header is not None:
            self.add_response_request_id_header = add_response_request_id_header
        assert callable(self.add_response_request_id_header)

        # Set self.request_id_header_name
        if request_id_header_name is not None:
            self.request_id_header_name = request_id_header_name
        assert isinstance(self.request_id_header_name, str)

        if no_fallback_request_id_key:
            self.fallback_request_id_key = None

        self.sentry_make_scope = self.resolve_sentry_make_scope()

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
            response = self.get_response_for_exception(e)
        return response

    def get_response_for_exception(self, exc):
        """
        Create the 500 response for an unhandled exception from the handler.
        """
        response = web.Response(status=500, text="500 Internal Server Error\n")
        response.force_close()
        return response

    async def after_request(self, request, handler, response, req_id, stack):
        """
        Called after the handler returns (or its exception is converted
        to a response). Adds the request id response header.
        """
        self.add_response_request_id_header(response, req_id)

    def log_request_start(self, request, handler):
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
        if self.request_id_key in request:
            raise RequestIdKeyAlreadySetError(request[self.request_id_key])
        request[self.request_id_key] = req_id

        if self.fallback_request_id_key is not None:
            assert self.fallback_request_id_key != self.request_id_key
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', getattr(web, 'NotAppKeyWarning', UserWarning))

                if self.fallback_request_id_key in request:
                    raise RequestIdKeyAlreadySetError(request[self.fallback_request_id_key])
                request[self.fallback_request_id_key] = req_id

    @staticmethod
    def resolve_sentry_make_scope():
        """
        Find the function for creating a new Sentry scope, or return None
        if sentry_sdk is not installed (or provides no such function).

        For compatibility with sentry_sdk 1.x and 2.x:
        push_scope is deprecated and will be removed, isolation_scope is its
        recommended replacement for the request-response cycle.
        """
        # Read sentry_sdk from the package at call time so that
        # a replaced aiohttp_request_id_logging.sentry_sdk (e.g. monkeypatched
        # in tests) is taken into account.
        from . import sentry_sdk
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

    def setup_sentry_scope(self, req_id, stack):
        """
        Create a new Sentry scope (entered into the given ExitStack)
        and add the request_id tag to it.

        Does nothing if sentry_sdk is not installed.
        """
        if self.sentry_make_scope is not None:
            scope = stack.enter_context(self.sentry_make_scope())
            scope.set_tag('request_id', req_id)

    def add_response_request_id_header(self, response, req_id):
        """
        Add X-Request-Id to the response headers
        """
        try:
            response.headers[self.request_id_header_name] = req_id
        except Exception as e:
            # Let's consider this response header non critical
            logger.debug("Could not set response.headers[%r]: %r", self.request_id_header_name, e)

    @staticmethod
    def get_function_name(f):
        """
        Return a human-readable handler name for the request start message.
        """
        try:
            return f'{f.__module__}:{f.__name__}'
        except Exception:
            return str(f)


def request_id_middleware(*, request_id_factory=None, log_function_name=True, log_request_start=True):
    """
    Backward compatibility function for creating a RequestIdMiddleware instance.

    Unlike the RequestIdMiddleware constructor, log_request_start is a bool
    here - log_request_start=False translates to log_request_start=noop.
    """
    assert callable(request_id_factory) or request_id_factory is None
    assert isinstance(log_function_name, bool)
    assert isinstance(log_request_start, bool)
    return RequestIdMiddleware(
        request_id_factory=request_id_factory,
        log_function_name=log_function_name,
        log_request_start=None if log_request_start else noop,
    )
