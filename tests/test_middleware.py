from asyncio import run
from aiohttp import web
from aiohttp.test_utils import make_mocked_request, TestClient, TestServer
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
    return web.Response(text="Hello, world!\n")


def test_middleware_sets_request_id():
    middleware = request_id_middleware()
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert response.status == 200
    assert request[REQUEST_ID_KEY]
    # the request id is stored also under the plain string key
    # for backward compatibility
    assert request["request_id"] == request[REQUEST_ID_KEY]
    # the contextvar is reset after the middleware finishes
    assert request_id.get(None) is None


def test_middleware_no_fallback_request_id_key():
    middleware = RequestIdMiddleware(no_fallback_request_id_key=True)
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert response.status == 200
    assert request[REQUEST_ID_KEY]
    if not isinstance(REQUEST_ID_KEY, str):
        # the plain string fallback key is not set
        # (on older aiohttp without web.RequestKey the string key
        # is the primary key, so there is no fallback to disable)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert "request_id" not in request


def test_middleware_logs_request_start_by_default(caplog):
    middleware = request_id_middleware()
    request = make_mocked_request("GET", "/")
    with caplog.at_level(INFO, logger="aiohttp_request_id_logging"):
        response = run(middleware(request, hello))
    assert response.status == 200
    # the message includes the handler function name by default
    assert f"Processing GET / ({hello.__module__}:hello)" in [r.message for r in caplog.records]


def test_middleware_log_function_name_can_be_disabled(caplog):
    middleware = request_id_middleware(log_function_name=False)
    request = make_mocked_request("GET", "/")
    with caplog.at_level(INFO, logger="aiohttp_request_id_logging"):
        response = run(middleware(request, hello))
    assert response.status == 200
    # exact match - no function name suffix
    assert "Processing GET /" in [r.message for r in caplog.records]


def test_middleware_log_request_start_can_be_disabled(caplog):
    middleware = request_id_middleware(log_request_start=False)
    request = make_mocked_request("GET", "/")
    with caplog.at_level(INFO, logger="aiohttp_request_id_logging"):
        response = run(middleware(request, hello))
    assert response.status == 200
    assert not any(r.message.startswith("Processing") for r in caplog.records)


def test_middleware_converts_handler_exception_to_500_response(caplog):
    middleware = request_id_middleware()
    request = make_mocked_request("GET", "/")

    async def failing_handler(request):
        raise ValueError("test exception")

    with caplog.at_level(INFO, logger="aiohttp_request_id_logging"):
        response = run(middleware(request, failing_handler))
    assert response.status == 500
    assert any("Error handling request" in r.message for r in caplog.records)


def test_middleware_get_response_for_exception_can_be_overridden():
    class JsonErrorMiddleware(RequestIdMiddleware):
        def get_response_for_exception(self, request, exc):
            return web.json_response({"error": str(exc), "path": request.path}, status=500)

    middleware = JsonErrorMiddleware()
    request = make_mocked_request("GET", "/api/thing")

    async def failing_handler(request):
        raise ValueError("test exception")

    response = run(middleware(request, failing_handler))
    assert isinstance(response, web.Response)
    assert response.status == 500
    assert response.content_type == "application/json"
    assert response.text is not None
    assert '"path": "/api/thing"' in response.text


def test_middleware_reraises_http_exception_with_request_id_header():
    middleware = request_id_middleware()
    request = make_mocked_request("GET", "/")

    async def not_found_handler(request):
        raise web.HTTPNotFound()

    with raises(web.HTTPNotFound) as excinfo:
        run(middleware(request, not_found_handler))
    # the exception is also the response aiohttp sends to the client,
    # so it carries the request id header (added by after_request)
    assert excinfo.value.headers["X-Request-Id"] == request[REQUEST_ID_KEY]


def test_middleware_reraised_http_exception_triggers_no_aiohttp_deprecation_warning():
    # The HTTPException must be re-raised, not returned - when the handler
    # chain returns one, aiohttp emits the "returning HTTPException object
    # is deprecated (#2415)" DeprecationWarning. The warning comes from
    # aiohttp web_protocol, which the tests calling the middleware directly
    # do not exercise, so run a real server here.
    async def not_found_handler(request):
        raise web.HTTPNotFound()

    async def scenario():
        app = web.Application(middlewares=[request_id_middleware()])
        app.router.add_get("/", not_found_handler)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            async with TestClient(TestServer(app)) as client:
                response = await client.get("/")
                assert response.status == 404
                assert response.headers["X-Request-Id"]
        assert not [w for w in caught if "HTTPException" in str(w.message)]

    run(scenario())


def test_middleware_raises_when_request_id_key_already_set():
    middleware = request_id_middleware()
    request = make_mocked_request("GET", "/")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        request[REQUEST_ID_KEY] = "alreadyset"
    with raises(RequestIdKeyAlreadySetError, match="request id 'alreadyset'") as excinfo:
        run(middleware(request, hello))
    assert excinfo.value.existing_request_id == "alreadyset"


def test_middleware_adds_response_request_id_header():
    middleware = request_id_middleware()
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert response.headers["X-Request-Id"] == request[REQUEST_ID_KEY]


def test_middleware_does_not_overwrite_request_id_header_set_by_handler():
    middleware = request_id_middleware()
    request = make_mocked_request("GET", "/")

    async def handler_with_own_header(request):
        return web.Response(text="ok", headers={"X-Request-Id": "from-handler"})

    response = run(middleware(request, handler_with_own_header))
    assert response.headers["X-Request-Id"] == "from-handler"


def test_middleware_get_request_id_can_adopt_incoming_header():
    class AdoptingRequestIdMiddleware(RequestIdMiddleware):
        def get_request_id(self, request):
            incoming = request.headers.get(self.request_id_header_name)
            if incoming and len(incoming) <= 64 and incoming.isascii() and incoming.isprintable():
                return incoming
            return None

    middleware = AdoptingRequestIdMiddleware()
    request = make_mocked_request("GET", "/", headers={"X-Request-Id": "from-proxy"})
    response = run(middleware(request, hello))
    assert request[REQUEST_ID_KEY] == "from-proxy"
    assert response.headers["X-Request-Id"] == "from-proxy"

    # without the incoming header, get_request_id returns None
    # and the id is generated with request_id_factory
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert request[REQUEST_ID_KEY]
    assert request[REQUEST_ID_KEY] != "from-proxy"


def test_middleware_request_id_factory_can_be_injected():
    middleware = RequestIdMiddleware(request_id_factory=lambda: "fixed-id")
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert request[REQUEST_ID_KEY] == "fixed-id"
    assert response.headers["X-Request-Id"] == "fixed-id"


def test_middleware_get_request_id_can_be_injected():
    middleware = RequestIdMiddleware(get_request_id=lambda request: f"id-for-{request.path.strip('/')}")
    request = make_mocked_request("GET", "/hello")
    response = run(middleware(request, hello))
    assert request[REQUEST_ID_KEY] == "id-for-hello"
    assert response.headers["X-Request-Id"] == "id-for-hello"


def test_middleware_injected_get_request_id_returning_none_falls_back_to_factory():
    middleware = RequestIdMiddleware(get_request_id=lambda request: None, request_id_factory=lambda: "from-factory")
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert request[REQUEST_ID_KEY] == "from-factory"
    assert response.headers["X-Request-Id"] == "from-factory"


def test_middleware_log_request_start_can_be_injected(caplog):
    calls = []
    middleware = RequestIdMiddleware(log_request_start=lambda request, handler: calls.append((request, handler)))
    request = make_mocked_request("GET", "/")
    with caplog.at_level(INFO, logger="aiohttp_request_id_logging"):
        response = run(middleware(request, hello))
    assert response.status == 200
    assert calls == [(request, hello)]
    # the default message is replaced by the injected callable
    assert not any(r.message.startswith("Processing") for r in caplog.records)


def test_middleware_log_request_start_can_read_request_id_key():
    seen = []
    middleware = RequestIdMiddleware(log_request_start=lambda request, handler: seen.append(request[REQUEST_ID_KEY]))
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert response.status == 200
    assert seen == [request[REQUEST_ID_KEY]]


def test_middleware_add_response_request_id_header_can_be_injected():
    middleware = RequestIdMiddleware(add_response_request_id_header=lambda response, req_id: response.headers.update({"X-Custom-Id": req_id}))
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert response.headers["X-Custom-Id"] == request[REQUEST_ID_KEY]
    assert "X-Request-Id" not in response.headers


def test_middleware_injected_callable_takes_precedence_over_subclass_method():
    method_calls = []

    class LoggingMiddleware(RequestIdMiddleware):
        def log_request_start(self, request, handler):
            method_calls.append(request)

    injected_calls = []
    middleware = LoggingMiddleware(log_request_start=lambda request, handler: injected_calls.append(request))
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert response.status == 200
    assert injected_calls == [request]
    assert method_calls == []


def test_add_response_request_id_header_skips_prepared_response():
    # A prepared response (streaming/WebSocket) already sent its headers
    # to the client, so the middleware must not pretend to add the header.
    middleware = RequestIdMiddleware()

    class PreparedResponse:
        prepared = True
        headers = {}

    response = PreparedResponse()
    middleware.add_response_request_id_header(response, "abc1234")  # ty: ignore[invalid-argument-type]
    assert response.headers == {}


def test_middleware_raises_when_legacy_string_key_already_set():
    middleware = request_id_middleware()
    request = make_mocked_request("GET", "/")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        request["request_id"] = "alreadyset"
    with raises(RequestIdKeyAlreadySetError):
        run(middleware(request, hello))
