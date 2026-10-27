import aiohttp_request_id_logging


def test_imported_api():
    assert callable(aiohttp_request_id_logging.setup_logging_request_id_prefix)
    assert callable(aiohttp_request_id_logging.request_id_middleware)
    assert isinstance(aiohttp_request_id_logging.RequestIdAccessLogger, type)
    # backward compatibility alias
    assert aiohttp_request_id_logging.RequestIdContextAccessLogger is aiohttp_request_id_logging.RequestIdAccessLogger
    assert isinstance(aiohttp_request_id_logging.RequestIdKeyAlreadySetError, type)
    # every name declared in __all__ exists
    # (cannot check "is not None" - FALLBACK_REQUEST_ID_KEY is None on aiohttp without web.RequestKey)
    for name in aiohttp_request_id_logging.__all__:
        assert hasattr(aiohttp_request_id_logging, name)
