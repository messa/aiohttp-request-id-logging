"""
Constants and context variables shared across the package.
"""

from contextvars import ContextVar
from aiohttp import web


# ContextVar that contains given request tracing id,
# or None outside of a request
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_KEY: "web.RequestKey[str] | str"
FALLBACK_REQUEST_ID_KEY: str | None

try:
    # key for storing the request id in the request; aiohttp recommends
    # web.RequestKey instances instead of plain strings
    REQUEST_ID_KEY = web.RequestKey("request_id", str)
    FALLBACK_REQUEST_ID_KEY = "request_id"
except AttributeError:
    # older aiohttp without web.RequestKey
    REQUEST_ID_KEY = "request_id"
    FALLBACK_REQUEST_ID_KEY = None
