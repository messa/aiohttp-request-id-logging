import aiohttp_request_id_logging


def test_imported_api():
    assert callable(aiohttp_request_id_logging.setup_logging_request_id_prefix)
    assert aiohttp_request_id_logging.request_id_middleware
    assert aiohttp_request_id_logging.RequestIdContextAccessLogger


def test_generate_request_id():
    assert aiohttp_request_id_logging.request_id_default_length == 7
    assert len(aiohttp_request_id_logging.generate_request_id()) == 7
    aiohttp_request_id_logging.request_id_default_length = 9
    assert len(aiohttp_request_id_logging.generate_request_id()) == 9
