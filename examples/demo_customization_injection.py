"""
Demonstrates how to customize the RequestIdMiddleware behavior by passing
parameters to its constructor - no subclassing needed.

Shown here:

- request_id_factory: generate sequential request ids instead of random ones
- log_request_start: log a custom request start message
- request_id_header_name: return the request id in a custom response header

For customization via subclassing see demo_customization_subclassing.py.

Run this file and try:

    curl -i http://localhost:8080/
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
    noop,
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


def custom_log_request_start(request, handler):
    """
    Custom replacement of the default request start log message.

    It is stored as a plain instance attribute, so it is called without
    the middleware instance - just with (request, handler).
    """
    logger.info("Started processing %s %s from %s", request.method, request.path_qs, request.remote)


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
            RequestIdMiddleware(
                # Generate ids like "Wxyz0001", "Wxyz0002"... instead of random ones.
                request_id_factory=SequentialRequestIdFactory(),
                # Replace the default "Processing GET / (...)" message.
                # Pass noop to disable the message completely.
                log_request_start=custom_log_request_start,
                # Return the request id to the client in a custom response header
                # (the default is X-Request-Id).
                request_id_header_name="X-Demo-Request-Id",
                # More options:
                # log_function_name=False,  # hide the handler name in the default start message
                # add_response_request_id_header=noop,  # do not add the response header at all
            ),
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
