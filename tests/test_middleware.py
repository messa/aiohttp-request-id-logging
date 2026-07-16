from asyncio import run
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from logging import INFO
from pytest import raises
import warnings

from aiohttp_request_id_logging import (
    request_id_middleware,
    request_id,
    RequestIdKeyAlreadySetError,
    RequestIdMiddleware,
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


def test_middleware_no_fallback_request_id_key():
    middleware = RequestIdMiddleware(no_fallback_request_id_key=True)
    request = make_mocked_request('GET', '/')
    response = run(middleware(request, hello))
    assert response.status == 200
    assert request[REQUEST_ID_KEY]
    if not isinstance(REQUEST_ID_KEY, str):
        # the plain string fallback key is not set
        # (on older aiohttp without web.RequestKey the string key
        # is the primary key, so there is no fallback to disable)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            assert 'request_id' not in request


def test_middleware_logs_request_start_by_default(caplog):
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')
    with caplog.at_level(INFO, logger='aiohttp_request_id_logging'):
        response = run(middleware(request, hello))
    assert response.status == 200
    # the message includes the handler function name by default
    assert f'Processing GET / ({hello.__module__}:hello)' in [r.message for r in caplog.records]


def test_middleware_log_function_name_can_be_disabled(caplog):
    middleware = request_id_middleware(log_function_name=False)
    request = make_mocked_request('GET', '/')
    with caplog.at_level(INFO, logger='aiohttp_request_id_logging'):
        response = run(middleware(request, hello))
    assert response.status == 200
    # exact match - no function name suffix
    assert 'Processing GET /' in [r.message for r in caplog.records]


def test_middleware_log_request_start_can_be_disabled(caplog):
    middleware = request_id_middleware(log_request_start=False)
    request = make_mocked_request('GET', '/')
    with caplog.at_level(INFO, logger='aiohttp_request_id_logging'):
        response = run(middleware(request, hello))
    assert response.status == 200
    assert not any(r.message.startswith('Processing') for r in caplog.records)


def test_middleware_converts_handler_exception_to_500_response(caplog):
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')

    async def failing_handler(request):
        raise ValueError('test exception')

    with caplog.at_level(INFO, logger='aiohttp_request_id_logging'):
        response = run(middleware(request, failing_handler))
    assert response.status == 500
    assert any('Error handling request' in r.message for r in caplog.records)


def test_middleware_returns_http_exception_as_response():
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')

    async def not_found_handler(request):
        raise web.HTTPNotFound()

    response = run(middleware(request, not_found_handler))
    assert response.status == 404


def test_middleware_raises_when_request_id_key_already_set():
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        request[REQUEST_ID_KEY] = 'alreadyset'
    with raises(RequestIdKeyAlreadySetError, match="request id 'alreadyset'") as excinfo:
        run(middleware(request, hello))
    assert excinfo.value.existing_request_id == 'alreadyset'


def test_middleware_adds_response_request_id_header():
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')
    response = run(middleware(request, hello))
    assert response.headers['X-Request-Id'] == request[REQUEST_ID_KEY]


def test_middleware_does_not_overwrite_request_id_header_set_by_handler():
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')

    async def handler_with_own_header(request):
        return web.Response(text='ok', headers={'X-Request-Id': 'from-handler'})

    response = run(middleware(request, handler_with_own_header))
    assert response.headers['X-Request-Id'] == 'from-handler'


def test_middleware_get_request_id_can_adopt_incoming_header():
    class AdoptingRequestIdMiddleware(RequestIdMiddleware):

        def get_request_id(self, request):
            incoming = request.headers.get(self.request_id_header_name)
            if incoming and len(incoming) <= 64 and incoming.isascii() and incoming.isprintable():
                return incoming
            return self.request_id_factory()

    middleware = AdoptingRequestIdMiddleware()
    request = make_mocked_request('GET', '/', headers={'X-Request-Id': 'from-proxy'})
    response = run(middleware(request, hello))
    assert request[REQUEST_ID_KEY] == 'from-proxy'
    assert response.headers['X-Request-Id'] == 'from-proxy'


def test_add_response_request_id_header_skips_prepared_response():
    # A prepared response (streaming/WebSocket) already sent its headers
    # to the client, so the middleware must not pretend to add the header.
    middleware = RequestIdMiddleware()

    class PreparedResponse:
        prepared = True
        headers = {}

    response = PreparedResponse()
    middleware.add_response_request_id_header(response, 'abc1234')
    assert response.headers == {}


def test_middleware_raises_when_legacy_string_key_already_set():
    middleware = request_id_middleware()
    request = make_mocked_request('GET', '/')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        request['request_id'] = 'alreadyset'
    with raises(RequestIdKeyAlreadySetError):
        run(middleware(request, hello))
