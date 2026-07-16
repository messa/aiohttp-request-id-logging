"""
Demonstrates how to customize the RequestIdMiddleware behavior by
subclassing it and overriding class attributes and methods.

Shown here:

- request_id_header_name: default overridden by a class attribute
- request_id_factory: default changed in __init__ - sequential ids
  instead of random ones
- get_request_id: adopt the request id from an incoming header
  (with validation - the value is controlled by the client)
- log_request_start: custom request start message
- after_request: additional behavior after the handler finishes

For customization via constructor parameters (without subclassing)
see demo_customization_injection.py.

Run this file and try:

    curl -i http://localhost:8080/
    curl -i -H 'X-Demo-Request-Id: id-from-proxy-1234' http://localhost:8080/
"""

from aiohttp.web import Response, RouteTableDef, Application, run_app, AppRunner, TCPSite
from aiohttp.web_log import AccessLogger
from argparse import ArgumentParser
from asyncio import sleep, run
from logging import DEBUG, basicConfig, getLogger
from os import environ

try:
    import sentry_sdk
    from sentry_sdk.integrations.aiohttp import AioHttpIntegration
except ImportError:
    sentry_sdk = None

from aiohttp_request_id_logging import (
    setup_logging_request_id_prefix,
    SequentialRequestIdFactory,
    RequestIdMiddleware,
    RequestIdContextAccessLogger,
)


LOG_FORMAT = "%(asctime)s [%(threadName)s] %(name)-37s %(levelname)5s: %(requestIdPrefix)s%(message)s"

logger = getLogger(__name__)

routes = RouteTableDef()


async def demo_sleep():
    if not environ.get("SKIP_SLEEP"):
        await sleep(1)


@routes.get("/")
async def hello(request):
    """
    Sample hello world handler.

    It sleeps and logs so that you can test the behavior of running
    multiple parallel handlers.
    """
    await demo_sleep()
    logger.info("Doing something")
    await demo_sleep()
    return Response(text="Hello, world!\n")


@routes.get("/f")
async def fail(request):
    """
    Sample exception raising handler.
    """
    await demo_sleep()
    raise Exception("test exception")
    await demo_sleep()
    return Response(text="Hello, world!\n")


@routes.get("/e")
async def log_error(request):
    """
    Sample error logging handler.
    """
    await demo_sleep()
    logger.error("test error log")
    await demo_sleep()
    return Response(text="Hello, world!\n")


class CustomRequestIdMiddleware(RequestIdMiddleware):
    """
    RequestIdMiddleware with customized defaults (class attributes)
    and customized behavior (overridden methods).
    """

    # Return the request id to the client in a custom response header
    # (the default is X-Request-Id).
    request_id_header_name = "X-Demo-Request-Id"

    def __init__(self, **kwargs):
        # Generate ids like "Wxyz0001", "Wxyz0002"... instead of random ones.
        kwargs.setdefault("request_id_factory", SequentialRequestIdFactory())
        super().__init__(**kwargs)

    def get_request_id(self, request):
        # Adopt the request id sent by an upstream proxy, if present.
        # Validate it first - the value is controlled by the client and
        # ends up in log lines and in the response header.
        incoming = request.headers.get(self.request_id_header_name)
        if incoming and len(incoming) <= 64 and incoming.isascii() and incoming.isprintable():
            return incoming
        return self.request_id_factory()

    def log_request_start(self, request, handler):
        # Replace the default "Processing GET / (...)" message.
        logger.info("Started processing %s %s (handler: %s)", request.method, request.path_qs, self.get_function_name(handler))

    async def after_request(self, request, handler, response, req_id, stack):
        # Keep the default behavior (adding the response header)...
        await super().after_request(request, handler, response, req_id, stack)
        # ...and also log the response status.
        logger.info("Done, response status: %s", response.status)


def main():
    parser = ArgumentParser()
    parser.add_argument("--host", type=str, default="localhost", help="Host to listen on")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    args = parser.parse_args()

    basicConfig(level=DEBUG, format=LOG_FORMAT)

    setup_logging_request_id_prefix()

    sentry_dsn = environ.get("SENTRY_DSN")
    if sentry_dsn and sentry_sdk:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[
                AioHttpIntegration(),
            ],
        )

    app = Application(
        middlewares=[
            CustomRequestIdMiddleware(),
        ]
    )
    app.router.add_routes(routes)

    """
    The simpler way how to run Aiohttp app:

    run_app(
        app,
        access_log_class=RequestIdContextAccessLogger,
        access_log_format=AccessLogger.LOG_FORMAT.replace(' %t ', ' ') + ' %Tf')
    """

    run(run_my_app(app, args.host, args.port))


async def run_my_app(app, host, port):
    runner = AppRunner(app, access_log_class=RequestIdContextAccessLogger, access_log_format=AccessLogger.LOG_FORMAT.replace(" %t ", " ") + " %Tf")
    try:
        await runner.setup()
        site = TCPSite(runner, host, port)
        await site.start()
        logger.info("Listening on http://%s:%s", host, port)
        while True:
            await sleep(3600)  # sleep forever
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    main()
