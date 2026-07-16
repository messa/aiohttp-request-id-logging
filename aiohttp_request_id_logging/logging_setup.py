import logging

from aiohttp import web
from aiohttp.web_log import AccessLogger as _AccessLogger

from .context import request_id, REQUEST_ID_KEY


def setup_logging_request_id_prefix(prefix_format: str = "[req:{request_id}] ") -> None:
    """
    Wrap logging record factory so that every log record gets two extra attributes:

    - record.requestIdPrefix - "[req:...] ", or an empty string outside of a request
    - record.request_id - the raw request id, or None

    You can then use them in log format as "%(requestIdPrefix)s" or "%(request_id)s".

    The prefix can be customized with the prefix_format parameter.

    Safe to call multiple times - the setup is done only once.
    """
    # make sure we are doing this only once
    if getattr(logging, "request_id_log_record_factory_set_up", False):
        return
    logging.request_id_log_record_factory_set_up = True  # ty: ignore[unresolved-attribute]

    old_factory = logging.getLogRecordFactory()

    def new_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        req_id = request_id.get(None)
        record.request_id = req_id
        record.requestIdPrefix = prefix_format.format(request_id=req_id) if req_id else ""
        return record

    logging.setLogRecordFactory(new_factory)


class RequestIdContextAccessLogger(_AccessLogger):
    """
    Subclass of aiohttp.web_log.AccessLogger that sets the request_id
    ContextVar while writing the access log line.

    Needed because aiohttp writes the access log outside of the middleware
    scope, where the ContextVar is already reset.

    Usage: run_app(app, access_log_class=RequestIdContextAccessLogger)
    """

    def log(self, request: web.BaseRequest, response: web.StreamResponse, time: float) -> None:
        try:
            request_id_value = request[REQUEST_ID_KEY]
        except KeyError:
            # If there is no request[REQUEST_ID_KEY], for example when an error
            # occurs in a middleware, fall back to just logging without setting
            # the request_id context variable.
            super().log(request, response, time)
            return

        token = request_id.set(request_id_value)
        try:
            super().log(request, response, time)
        finally:
            request_id.reset(token)
