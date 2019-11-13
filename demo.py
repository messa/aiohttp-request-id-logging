# 05_aiohttp.py

from aiohttp import web
from aiohttp.web_log import AccessLogger
from aiohttp.web_exceptions import HTTPException
from asyncio import CancelledError
from contextvars import ContextVar
import asyncio
import logging
import secrets
import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
import os


logger = logging.getLogger(__name__)


# contextvar that contains given request tracing id
request_id = ContextVar('request_id')


def setup_log_record_factory():
    '''
    Wrap logging request factory so that [{request_id}] is prepended to each message
    '''
    old_factory = logging.getLogRecordFactory()

    def new_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        req_id = request_id.get(None)
        record.requestIdPrefix = f'[{req_id}] ' if req_id else ''
        return record

    logging.setLogRecordFactory(new_factory)


async def hello(request):
    '''
    Sample hello world handler.

    It sleeps and logs so that you can test the behavior of running
    multiple parallel handlers.
    '''
    logger.info('Started processing request')
    await asyncio.sleep(1)
    logger.info('Doing something')
    await asyncio.sleep(1)
    return web.Response(text="Hello, world!\n")

async def fail(request):
    '''
    Sample hello world handler.

    It sleeps and logs so that you can test the behavior of running
    multiple parallel handlers.
    '''
    logger.info('Started processing request f')
    await asyncio.sleep(1)
    raise Exception('pokusny fail 4444444')
    await asyncio.sleep(1)
    return web.Response(text="Hello, world!\n")


async def log_error(request):
    '''
    Sample hello world handler.

    It sleeps and logs so that you can test the behavior of running
    multiple parallel handlers.
    '''
    with sentry_sdk.push_scope() as scope:
        scope.set_tag('scopetest', 'foobar2')
        logger.info('Started processing request log_error')
        await asyncio.sleep(1)
        logger.error('nejaky error zzzzzzzz')
        await asyncio.sleep(1)
        return web.Response(text="Hello, world!\n")


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(threadName)s] %(name)-14s %(levelname)5s: %(requestIdPrefix)s%(message)s')

setup_log_record_factory()


sentry_dsn = os.environ.get('SENTRY_DSN')

if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[AioHttpIntegration()]
    )


@web.middleware
async def add_request_id_middleware(request, handler):
    '''
    Aiohttp middleware that sets request_id contextvar and request['request_id']
    to some random value identifying the given request.
    '''
    req_id = secrets.token_urlsafe(5).replace('_', 'x').replace('-', 'X')
    request['request_id'] = req_id
    with sentry_sdk.push_scope() as scope:
        scope.set_tag('request_id', req_id)
        token = request_id.set(req_id)
        try:
            try:
                logger.info('Processing %s %s (%s)', request.method, request.path, handler)
                return await handler(request)
            except CancelledError as e:
                logger.info('(Cancelled)')
                raise e
            except HTTPException as e:
                logger.debug('HTTPException: %r', e)
                raise e
            except Exception as e:
                logger.exception('Error handling request: %r', e)
                resp = web.Response(
                    status=500,
                    text='500 Internal Server Error\n',
                    content_type='text/plain')
                resp.force_close()
                return resp
        finally:
            request_id.reset(token)


app = web.Application(middlewares=[add_request_id_middleware])
app.add_routes([web.get('/', hello)])
app.add_routes([web.get('/f', fail)])
app.add_routes([web.get('/e', log_error)])


class CustomAccessLogger (AccessLogger):

    def log(self, request, response, time):
        token = request_id.set(request['request_id'])
        try:
            super().log(request, response, time)
        finally:
            request_id.reset(token)


web.run_app(
    app,
    access_log_class=CustomAccessLogger,
    access_log_format=AccessLogger.LOG_FORMAT.replace(' %t ', ' ') + ' %Tf')
