import aiohttp_request_id_logging


def test_imported_api():
    assert callable(aiohttp_request_id_logging.setup_logging_request_id_prefix)
    assert aiohttp_request_id_logging.request_id_middleware
    assert aiohttp_request_id_logging.RequestIdAccessLogger
    # backward compatibility alias
    assert aiohttp_request_id_logging.RequestIdContextAccessLogger is aiohttp_request_id_logging.RequestIdAccessLogger
    assert aiohttp_request_id_logging.RequestIdKeyAlreadySetError
    # every name declared in __all__ exists
    # (cannot check "is not None" - FALLBACK_REQUEST_ID_KEY is None on aiohttp without web.RequestKey)
    for name in aiohttp_request_id_logging.__all__:
        assert hasattr(aiohttp_request_id_logging, name)
