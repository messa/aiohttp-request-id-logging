from asyncio import run
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from pytest import raises
import warnings

from aiohttp_request_id_logging import (
    request_id_middleware,
    request_id,
    RequestIdKeyAlreadySetError,
    REQUEST_ID_KEY,
)


async def hello(request):
    # the request_id contextvar should be set while the handler runs
    assert request_id.get() == request[REQUEST_ID_KEY]
    return web.Response(text='Hello, world!\n')


def test_middleware_sets_request_id():
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')
    response = run(middleware(request, hello))
    assert response.status == 200
    assert request[REQUEST_ID_KEY]
    # the request id is stored also under the plain string key
    # for backward compatibility
    assert request['request_id'] == request[REQUEST_ID_KEY]
    # the contextvar is reset after the middleware finishes
    assert request_id.get(None) is None


def test_middleware_raises_when_request_id_key_already_set():
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        request[REQUEST_ID_KEY] = 'alreadyset'
    with raises(RequestIdKeyAlreadySetError, match="request id 'alreadyset'") as excinfo:
        run(middleware(request, hello))
    assert excinfo.value.existing_request_id == 'alreadyset'


def test_middleware_raises_when_legacy_string_key_already_set():
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        request['request_id'] = 'alreadyset'
    with raises(RequestIdKeyAlreadySetError):
        run(middleware(request, hello))
