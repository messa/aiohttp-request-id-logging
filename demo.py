from aiohttp.web import Response, RouteTableDef, Application, run_app, AppRunner, TCPSite
from aiohttp.web_log import AccessLogger
from asyncio import sleep, run
from logging import DEBUG, basicConfig, getLogger
import os

try:
    import sentry_sdk
    from sentry_sdk.integrations.aiohttp import AioHttpIntegration
except ImportError:
    sentry_sdk = None

from aiohttp_request_id_logging import (
    setup_logging_request_id_prefix,
    request_id_middleware,
    sequential_request_id_factory,
    RequestIdContextAccessLogger)


logger = getLogger(__name__)

routes = RouteTableDef()


@routes.get('/')
async def hello(request):
    '''
    Sample hello world handler.

    It sleeps and logs so that you can test the behavior of running
    multiple parallel handlers.
    '''
    await sleep(1)
    logger.info('Doing something')
    await sleep(1)
    return Response(text="Hello, world!\n")


@routes.get('/f')
async def fail(request):
    '''
    Sample exception raising handler.
    '''
    await sleep(1)
    raise Exception('test exception')
    await sleep(1)
    return Response(text="Hello, world!\n")


@routes.get('/e')
async def log_error(request):
    '''
    Sample error logging handler.
    '''
    await sleep(1)
    logger.error('test error log')
    await sleep(1)
    return Response(text="Hello, world!\n")


def main():
    basicConfig(
        level=DEBUG,
        format='%(asctime)s [%(threadName)s] %(name)-26s %(levelname)5s: %(requestIdPrefix)s%(message)s')

    setup_logging_request_id_prefix()

    sentry_dsn = os.environ.get('SENTRY_DSN')
    if sentry_dsn and sentry_sdk:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[
                AioHttpIntegration(),
            ])

    app = Application(
        middlewares=[
            request_id_middleware(),
            # Alternatively:
            # request_id_middleware(request_id_factory=sequential_request_id_factory),
        ])
    app.router.add_routes(routes)

    '''
    The simpler way how to run Aiohttp app:

    run_app(
        app,
        access_log_class=RequestIdContextAccessLogger,
        access_log_format=AccessLogger.LOG_FORMAT.replace(' %t ', ' ') + ' %Tf')
    '''

    run(run_my_app(app))


async def run_my_app(app):
    runner = AppRunner(
        app,
        access_log_class=RequestIdContextAccessLogger,
        access_log_format=AccessLogger.LOG_FORMAT.replace(' %t ', ' ') + ' %Tf')
    try:
        await runner.setup()
        site = TCPSite(runner, 'localhost', 8080)
        await site.start()
        while True:
            await sleep(3600)  # sleep forever
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    main()
