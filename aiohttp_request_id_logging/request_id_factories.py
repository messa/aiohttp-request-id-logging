from os import getpid
from secrets import token_urlsafe


def random_request_id_factory(length: int = 7) -> str:
    """
    Generate a random request id - a URL-safe string of the given length.

    This is the default request id factory used in RequestIdMiddleware.
    """
    req_id = token_urlsafe(length)[:length]
    req_id = req_id.replace("_", "x").replace("-", "X")
    return req_id


class SequentialRequestIdFactory:
    """
    Alternative request id factory producing ids like "Wxyz0001", "Wxyz0002"...
    - a random per-process prefix followed by a sequential number.

    Usage: RequestIdMiddleware(request_id_factory=sequential_request_id_factory)

    Caveat: if the request ids are ever exposed to clients (response header,
    error page...), sequential ids reveal how many requests the server
    processes and how many server processes there are. Note that
    RequestIdMiddleware sends the request id to clients in the X-Request-Id
    response header by default - pass add_response_request_id_header=noop
    to disable that. If the exposure is a concern, use the default
    random_request_id_factory instead.
    """

    prefix_length: int = 4

    def __init__(self):
        self._pid: int | None = None
        self._prefix: str | None = None
        self._next_value: int = 0

    def __call__(self) -> str:
        pid = getpid()
        if pid != self._pid:
            self._prefix = self._generate_prefix()
            self._next_value = 0
            self._pid = pid
        value = self._next_value
        self._next_value += 1
        return f"{self._prefix}{value:04}"

    @classmethod
    def _generate_prefix(cls) -> str:
        while True:
            prefix = token_urlsafe(cls.prefix_length)[: cls.prefix_length]
            if "_" in prefix or "-" in prefix:
                continue
            # Let's not have any numbers in the prefix so we keep more focus on the appended request number.
            # This is just aesthetic thing.
            if any(c.isdigit() for c in prefix):
                continue
            if "l" in prefix or "I" in prefix:
                continue
            return prefix


sequential_request_id_factory = SequentialRequestIdFactory()
