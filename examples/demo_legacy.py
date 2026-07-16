"""
Demonstrates the backward compatible request_id_middleware() usage -
the wrapper function kept for applications written against the pre-1.0
API. The legacy RequestIdContextAccessLogger name (an alias of
RequestIdAccessLogger) is used here intentionally for the same reason.
New code should use the RequestIdMiddleware class and the new name
directly (see demo.py).

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
    sentry_sdk = None  # ty: ignore[invalid-assignment]

from aiohttp_request_id_logging import (
    setup_logging_request_id_prefix,
    request_id_middleware,
    sequential_request_id_factory,
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
            request_id_middleware(),
            # Alternatively:
            # request_id_middleware(request_id_factory=sequential_request_id_factory),
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
