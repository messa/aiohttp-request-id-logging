"""
Adds a request (correlation) id to log messages in aiohttp web applications.

Usage:

    from aiohttp.web import Application, Response, RouteTableDef, run_app
    from logging import DEBUG, basicConfig
    from aiohttp_request_id_logging import (
        setup_logging_request_id_prefix,
        RequestIdMiddleware,
        RequestIdAccessLogger,
    )

    routes = RouteTableDef()

    @routes.get('/')
    async def hello(request):
        return Response(text="Hello, world!")

    basicConfig(
        level=DEBUG,
        format='%(asctime)s [%(threadName)s] %(name)-37s %(levelname)5s: %(requestIdPrefix)s%(message)s')

    setup_logging_request_id_prefix()

    app = Application(middlewares=[RequestIdMiddleware()])
    app.router.add_routes(routes)

    run_app(app, access_log_class=RequestIdAccessLogger)

"""

__version__ = "1.0.0"

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # ty: ignore[invalid-assignment]

from .context import request_id, REQUEST_ID_KEY, FALLBACK_REQUEST_ID_KEY
from .errors import RequestIdKeyAlreadySetError
from .middleware import RequestIdMiddleware, request_id_middleware, noop
from .request_id_factories import (
    random_request_id_factory,
    sequential_request_id_factory,
    SequentialRequestIdFactory,
)
from .logging_setup import setup_logging_request_id_prefix, RequestIdAccessLogger


# old names for backward compatibility
generate_request_id = random_request_id_factory
RequestIdContextAccessLogger = RequestIdAccessLogger


__all__ = [
    "RequestIdMiddleware",
    "request_id_middleware",
    "RequestIdKeyAlreadySetError",
    "setup_logging_request_id_prefix",
    "RequestIdAccessLogger",
    "RequestIdContextAccessLogger",
    "random_request_id_factory",
    "generate_request_id",
    "sequential_request_id_factory",
    "SequentialRequestIdFactory",
    "request_id",
    "REQUEST_ID_KEY",
    "FALLBACK_REQUEST_ID_KEY",
    "noop",
]
