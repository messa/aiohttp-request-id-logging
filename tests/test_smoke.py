import aiohttp_request_id_logging


def test_imported_api():
    assert callable(aiohttp_request_id_logging.setup_logging_request_id_prefix)
    assert aiohttp_request_id_logging.request_id_middleware
    assert aiohttp_request_id_logging.RequestIdContextAccessLogger
    assert aiohttp_request_id_logging.RequestIdKeyAlreadySetError


def test_generate_request_id(monkeypatch):
    assert len(aiohttp_request_id_logging.generate_request_id()) == 7
    assert len(aiohttp_request_id_logging.generate_request_id(9)) == 9


def test_setting_default_values():

    class C:

        x = 10

        def __init__(self, x=None):
            self.x = x or self.x

    assert C().x == 10
    assert C(20).x == 20

    class D(C):

        x = 30

    assert D().x == 30
    assert D(20).x == 20
