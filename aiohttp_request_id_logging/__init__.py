from asyncio import CancelledError
from aiohttp import web
from aiohttp.web_exceptions import HTTPException
from aiohttp.web_log import AccessLogger as _AccessLogger
from contextvars import ContextVar
from contextlib import ExitStack
import logging
from secrets import token_urlsafe

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None


# contextvar that contains given request tracing id
request_id = ContextVar('request_id')

logger = logging.getLogger(__name__)


def setup_logging_request_id_prefix():
    '''
    Wrap logging request factory so that every log record gets ab attribute
    record.requestIdPrefix.
    '''
    # make sure we are doing this only once
    if getattr(logging, 'request_id_log_record_factory_set_up', False):
        return
    logging.request_id_log_record_factory_set_up = True

    old_factory = logging.getLogRecordFactory()

    def new_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        req_id = request_id.get(None)
        record.requestIdPrefix = f'[{req_id}] ' if req_id else ''
        return record

    logging.setLogRecordFactory(new_factory)


class RequestIdContextAccessLogger (_AccessLogger):

    def log(self, request, response, time):
        token = request_id.set(request['request_id'])
        try:
            super().log(request, response, time)
        finally:
            request_id.reset(token)


def generate_request_id():
    '''
    Used in request_id_middleware to generate the request id
    '''
    req_id = token_urlsafe(5)
    req_id = req_id.replace('_', 'x').replace('-', 'X')
    return req_id


def request_id_middleware(request_id_factory=None):
    request_id_factory = request_id_factory or generate_request_id

    @web.middleware
    async def _request_id_middleware(request, handler):
        '''
        Aiohttp middleware that sets request_id contextvar and request['request_id']
        to some random value identifying the given request.
        '''
        req_id = request_id_factory()
        request['request_id'] = req_id
        token = request_id.set(req_id)
        try:
            with ExitStack() as stack:
                if sentry_sdk:
                    scope = stack.enter_context(sentry_sdk.push_scope())
                    scope.set_tag('request_id', req_id)
                return await _call_handler(request, handler)
        finally:
            request_id.reset(token)

    return _request_id_middleware


async def _call_handler(request, handler):
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
        # We are processing 500 error right here, because if we let it
        # the web server to process, it would be outside of the request_id
        # contextvar scope.
        # (And also outside the sentry scope, if sentry is enabled.)
        logger.exception('Error handling request: %r', e)
        resp = web.Response(
            status=500,
            text='500 Internal Server Error\n',
            content_type='text/plain')
        resp.force_close()
        return resp