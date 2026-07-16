import aiohttp_request_id_logging


def test_generate_request_id():
    assert len(aiohttp_request_id_logging.generate_request_id()) == 7
    assert len(aiohttp_request_id_logging.generate_request_id(9)) == 9
