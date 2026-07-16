import aiohttp_request_id_logging


def test_imported_api():
    assert callable(aiohttp_request_id_logging.setup_logging_request_id_prefix)
    assert aiohttp_request_id_logging.request_id_middleware
    assert aiohttp_request_id_logging.RequestIdContextAccessLogger
    assert aiohttp_request_id_logging.RequestIdKeyAlreadySetError
    # every name declared in __all__ exists
    for name in aiohttp_request_id_logging.__all__:
        assert getattr(aiohttp_request_id_logging, name) is not None


def test_generate_request_id(monkeypatch):
    assert len(aiohttp_request_id_logging.generate_request_id()) == 7
    assert len(aiohttp_request_id_logging.generate_request_id(9)) == 9
