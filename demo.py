from aiohttp import web
from aiohttp.web_log import AccessLogger
import asyncio
import logging
import os

try:
    import sentry_sdk
    from sentry_sdk.integrations.aiohttp import AioHttpIntegration
except ImportError:
    sentry_sdk = None

from aiohttp_request_id_logging import (
    setup_logging_request_id_prefix,
    request_id_middleware,
    RequestIdContextAccessLogger)


logger = logging.getLogger(__name__)


async def hello(request):
    '''
    Sample hello world handler.

    It sleeps and logs so that you can test the behavior of running
    multiple parallel handlers.
    '''
    await asyncio.sleep(1)
    logger.info('Doing something')
    await asyncio.sleep(1)
    return web.Response(text="Hello, world!\n")


async def fail(request):
    '''
    Sample exception raising handler.
    '''
    await asyncio.sleep(1)
    raise Exception('test exception')
    await asyncio.sleep(1)
    return web.Response(text="Hello, world!\n")


async def log_error(request):
    '''
    Sample error logging handler.
    '''
    await asyncio.sleep(1)
    logger.error('test error log')
    await asyncio.sleep(1)
    return web.Response(text="Hello, world!\n")


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(threadName)s] %(name)-26s %(levelname)5s: %(requestIdPrefix)s%(message)s')

setup_logging_request_id_prefix()


sentry_dsn = os.environ.get('SENTRY_DSN')
if sentry_dsn and sentry_sdk:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[
            AioHttpIntegration(),
        ])


app = web.Application(
    middlewares=[
        request_id_middleware(),
    ])
app.add_routes([web.get('/', hello)])
app.add_routes([web.get('/f', fail)])
app.add_routes([web.get('/e', log_error)])


web.run_app(
    app,
    access_log_class=RequestIdContextAccessLogger,
    access_log_format=AccessLogger.LOG_FORMAT.replace(' %t ', ' ') + ' %Tf')
