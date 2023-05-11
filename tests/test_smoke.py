def test_import():
    import aiohttp_request_id_logging
    assert callable(aiohttp_request_id_logging.setup_logging_request_id_prefix)
    assert aiohttp_request_id_logging.request_id_middleware
    assert aiohttp_request_id_logging.RequestIdContextAccessLogger
