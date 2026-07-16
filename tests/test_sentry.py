from asyncio import run
from contextlib import contextmanager
from types import SimpleNamespace
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from pytest import warns

import aiohttp_request_id_logging
from aiohttp_request_id_logging import RequestIdMiddleware, REQUEST_ID_KEY


async def hello(request):
    return web.Response(text="Hello, world!\n")


class FakeScope:
    def __init__(self):
        self.tags = {}
        self.active = False

    def set_tag(self, key, value):
        assert self.active, "set_tag() called outside of the scope context"
        self.tags[key] = value


def make_fake_scope_cm(created_scopes):
    @contextmanager
    def make_scope():
        scope = FakeScope()
        scope.active = True
        created_scopes.append(scope)
        try:
            yield scope
        finally:
            scope.active = False

    return make_scope


def test_middleware_works_without_sentry_sdk(monkeypatch):
    monkeypatch.setattr(aiohttp_request_id_logging, "sentry_sdk", None)
    middleware = RequestIdMiddleware()
    assert middleware.sentry_make_scope is None
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert response.status == 200


def test_sentry_scope_is_created_with_request_id_tag(monkeypatch):
    # fake sentry_sdk 2.x provides isolation_scope
    created_scopes = []
    fake_sentry = SimpleNamespace(isolation_scope=make_fake_scope_cm(created_scopes))
    monkeypatch.setattr(aiohttp_request_id_logging, "sentry_sdk", fake_sentry)
    middleware = RequestIdMiddleware()
    assert middleware.sentry_make_scope is fake_sentry.isolation_scope

    async def handler(request):
        # the sentry scope should be active while the handler runs
        assert created_scopes and created_scopes[-1].active
        return await hello(request)

    request = make_mocked_request("GET", "/")
    response = run(middleware(request, handler))
    assert response.status == 200
    (scope,) = created_scopes
    assert scope.tags == {"request_id": request[REQUEST_ID_KEY]}
    # the scope was exited when the request finished
    assert not scope.active


def test_sentry_push_scope_is_used_as_fallback(monkeypatch):
    # fake sentry_sdk 1.x provides only push_scope
    created_scopes = []
    fake_sentry = SimpleNamespace(push_scope=make_fake_scope_cm(created_scopes))
    monkeypatch.setattr(aiohttp_request_id_logging, "sentry_sdk", fake_sentry)
    middleware = RequestIdMiddleware()
    assert middleware.sentry_make_scope is fake_sentry.push_scope
    request = make_mocked_request("GET", "/")
    response = run(middleware(request, hello))
    assert response.status == 200
    assert len(created_scopes) == 1


def test_sentry_sdk_without_scope_functions_warns(monkeypatch):
    monkeypatch.setattr(aiohttp_request_id_logging, "sentry_sdk", SimpleNamespace())
    with warns(UserWarning, match="isolation_scope or push_scope"):
        middleware = RequestIdMiddleware()
    assert middleware.sentry_make_scope is None
