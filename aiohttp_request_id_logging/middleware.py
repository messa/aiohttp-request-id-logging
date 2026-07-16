from aiohttp import web
from aiohttp.typedefs import Handler
from aiohttp.web_exceptions import HTTPException
from asyncio import CancelledError
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from contextvars import ContextVar
from logging import getLogger
from typing import Any
import warnings

from . import random_request_id_factory, REQUEST_ID_KEY, FALLBACK_REQUEST_ID_KEY, request_id, noop
from .errors import RequestIdKeyAlreadySetError


logger = getLogger(__name__)


class RequestIdMiddleware:
    """
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
      add_response_request_id_header method, which keeps a header already
      set by the handler; pass noop to disable the header
    - request_id_header_name: name of the response header with the request
      id; default: "X-Request-Id"
    - no_fallback_request_id_key: if True, store the request id only under
      REQUEST_ID_KEY and not under the backward compatibility plain string
      key request['request_id'] (sets the fallback_request_id_key attribute
      to None); default: False

    Each parameter overrides the method or class attribute of the same name.
    The behavior can also be customized by subclassing - overriding the class
    attributes (request_id_factory, request_id_header_name, log_function_name)
    or the methods: get_request_id, before_request, call_handler,
    after_request, get_response_for_exception, log_request_start,
    set_request_keys, setup_sentry_scope, add_response_request_id_header,
    get_function_name.

    request_id_middleware is a backward compatibility wrapper function
    creating an instance of this class.
    """

    __middleware_version__ = 1  # aiohttp 3 needs this; this is what @web.middleware is setting

    # Default values - can be overridden when subclassing
    request_id_factory: Callable[[], str] = staticmethod(random_request_id_factory)
    request_id_header_name: str = "X-Request-Id"
    log_function_name: bool = True
    request_id_key = REQUEST_ID_KEY
    fallback_request_id_key: str | None = FALLBACK_REQUEST_ID_KEY
    request_id_cv: ContextVar[str] = request_id

    def __init__(
        self,
        *,
        request_id_factory: Callable[[], str] | None = None,
        log_request_start: Callable[[web.Request, Handler], None] | None = None,
        log_function_name: bool | None = None,
        add_response_request_id_header: Callable[[web.StreamResponse, str], None] | None = None,
        request_id_header_name: str | None = None,
        no_fallback_request_id_key: bool = False,
    ):
        # Set self.request_id_factory
        if request_id_factory is not None:
            self.request_id_factory = request_id_factory
        if not callable(self.request_id_factory):
            raise TypeError("request_id_factory must be a callable")

        # Set self.log_request_start
        if log_request_start is not None:
            self.log_request_start = log_request_start
        if not callable(self.log_request_start):
            raise TypeError("log_request_start must be a callable; pass noop to disable the message")

        # Set self.log_function_name
        if log_function_name is not None:
            self.log_function_name = log_function_name
        if not isinstance(self.log_function_name, bool):
            raise TypeError("log_function_name must be a bool")

        # Set self.add_response_request_id_header
        if add_response_request_id_header is not None:
            self.add_response_request_id_header = add_response_request_id_header
        if not callable(self.add_response_request_id_header):
            raise TypeError("add_response_request_id_header must be a callable; pass noop to disable the header")

        # Set self.request_id_header_name
        if request_id_header_name is not None:
            self.request_id_header_name = request_id_header_name
        if not isinstance(self.request_id_header_name, str):
            raise TypeError("request_id_header_name must be a str")

        if no_fallback_request_id_key:
            self.fallback_request_id_key = None

        self.sentry_make_scope = self.resolve_sentry_make_scope()

    async def __call__(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        """
        The middleware entrypoint - process one request.

        Obtains the request id from get_request_id, sets the request_id
        ContextVar for the whole duration of the request processing and
        delegates the rest to before_request, call_handler and after_request.
        """
        req_id = self.get_request_id(request)
        with ExitStack() as stack:
            # Set request id context variable as a first thing
            token = self.request_id_cv.set(req_id)
            stack.callback(lambda: self.request_id_cv.reset(token))

            await self.before_request(request, handler, req_id, stack)
            response = await self.call_handler(request, handler, req_id, stack)
            await self.after_request(request, handler, response, req_id, stack)
            return response

    def get_request_id(self, request: web.Request) -> str:
        """
        Return the request id for the given request.

        The default implementation generates a new id using
        request_id_factory. Override this to e.g. adopt a request id from
        an incoming header - but validate the value, it is controlled by
        the client (see examples/demo_customization_subclassing.py).
        """
        return self.request_id_factory()

    async def before_request(self, request: web.Request, handler: Handler, req_id: str, stack: ExitStack) -> None:
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

    async def call_handler(
        self,
        request: web.Request,
        handler: Handler,
        req_id: str,
        stack: ExitStack,
    ) -> web.StreamResponse:
        """
        Call handler and return response.

        If handler raises an exception, convert it to response object.
        """
        try:
            response = await handler(request)
        except CancelledError as e:
            logger.info("(Cancelled)")
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

    def get_response_for_exception(self, exc: Exception) -> web.StreamResponse:
        """
        Create the 500 response for an unhandled exception from the handler.
        """
        response = web.Response(status=500, text="500 Internal Server Error\n")
        response.force_close()
        return response

    async def after_request(
        self,
        request: web.Request,
        handler: Handler,
        response: web.StreamResponse,
        req_id: str,
        stack: ExitStack,
    ) -> None:
        """
        Called after the handler returns (or its exception is converted
        to a response). Adds the request id response header.
        """
        self.add_response_request_id_header(response, req_id)

    def log_request_start(self, request: web.Request, handler: Handler) -> None:
        """
        Log the "Processing GET / (...)" message at the start of the request.
        """
        if self.log_function_name:
            logger.info("Processing %s %s (%s)", request.method, request.path, self.get_function_name(handler))
        else:
            logger.info("Processing %s %s", request.method, request.path)

    def set_request_keys(self, request: web.Request, req_id: str) -> None:
        """
        Set request["request_id"] - both str and AppKey keys
        """
        if self.request_id_key in request:
            raise RequestIdKeyAlreadySetError(request[self.request_id_key])
        request[self.request_id_key] = req_id

        if self.fallback_request_id_key is not None:
            assert self.fallback_request_id_key != self.request_id_key
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", getattr(web, "NotAppKeyWarning", UserWarning))

                if self.fallback_request_id_key in request:
                    raise RequestIdKeyAlreadySetError(request[self.fallback_request_id_key])
                request[self.fallback_request_id_key] = req_id

    @staticmethod
    def resolve_sentry_make_scope() -> Callable[[], AbstractContextManager[Any]] | None:
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

    def setup_sentry_scope(self, req_id: str, stack: ExitStack) -> None:
        """
        Create a new Sentry scope (entered into the given ExitStack)
        and add the request_id tag to it.

        Does nothing if sentry_sdk is not installed.
        """
        if self.sentry_make_scope is not None:
            scope = stack.enter_context(self.sentry_make_scope())
            scope.set_tag("request_id", req_id)

    def add_response_request_id_header(self, response: web.StreamResponse, req_id: str) -> None:
        """
        Add the request id response header (named by request_id_header_name).

        The header is silently not added (a missing response request id
        header is not a serious problem) when:

        - the response already contains the header, for example the handler
          echoes the request id of an upstream proxy,
        - the response was already prepared (a streaming or WebSocket
          handler called response.prepare()) - its headers were already
          sent to the client and cannot be changed anymore; to have the
          header on streaming responses, set it in the handler before
          calling prepare().
        """
        try:
            if response.prepared:
                # Mutating response.headers now would succeed, but the change
                # would never reach the client.
                return
            if self.request_id_header_name in response.headers:
                return
            response.headers[self.request_id_header_name] = req_id
        except Exception as e:
            # Let's consider this response header non critical
            logger.debug("Could not set response.headers[%r]: %r", self.request_id_header_name, e)

    @staticmethod
    def get_function_name(f: Callable[..., Any]) -> str:
        """
        Return a human-readable handler name for the request start message.
        """
        try:
            return f"{f.__module__}:{f.__name__}"
        except Exception:
            return str(f)


def request_id_middleware(
    *,
    request_id_factory: Callable[[], str] | None = None,
    log_function_name: bool = True,
    log_request_start: bool = True,
) -> RequestIdMiddleware:
    """
    Backward compatibility function for creating a RequestIdMiddleware instance.

    Unlike the RequestIdMiddleware constructor, log_request_start is a bool
    here - log_request_start=False translates to log_request_start=noop.
    """
    if request_id_factory is not None and not callable(request_id_factory):
        raise TypeError("request_id_factory must be a callable")
    if not isinstance(log_function_name, bool):
        raise TypeError("log_function_name must be a bool")
    if not isinstance(log_request_start, bool):
        raise TypeError("log_request_start must be a bool here; the RequestIdMiddleware constructor takes a callable")
    return RequestIdMiddleware(
        request_id_factory=request_id_factory,
        log_function_name=log_function_name,
        log_request_start=None if log_request_start else noop,
    )
