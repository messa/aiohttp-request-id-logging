aiohttp-request-id-logging
==========================

When you log from your web application, usually log messages from different requests are intertwined and you cannot surely tell which line was generated by what request. For example:

```
2020-01-15 15:35:37,501  INFO: Processing money transfer id 1234
2020-01-15 15:35:37,976  INFO: Processing money transfer id 5678
2020-01-15 15:35:38,201 ERROR: Oh no, something bad has happened! Cannot finish the transfer.
2020-01-15 15:35:38,504  INFO: 127.0.0.1 [15/Jan/2020:14:35:36 +0000] "GET / HTTP/1.1" 200 165 "-" "curl/7.68.0"
2020-01-15 15:35:38,982  INFO: 127.0.0.1 [15/Jan/2020:14:35:36 +0000] "GET / HTTP/1.1" 500 165 "-" "curl/7.68.0"
```

So, which transfer has failed? The one with id 1234, or the one with id 5678?

When you start to use this library, this is how your log messages will look like:

```
2020-01-15 15:58:47,238  INFO: [req:O5bvIlU] Processing GET / (__main__:hello)
2020-01-15 15:58:47,950  INFO: [req:xtMacpA] Processing GET / (__main__:hello)
2020-01-15 15:58:48,240  INFO: [req:O5bvIlU] Processing money transfer id 1234
2020-01-15 15:58:48,953  INFO: [req:xtMacpA] Processing money transfer id 5678
2020-01-15 15:58:49,182 ERROR: [req:xtMacpA] Oh no, something bad has happened! Cannot finish the transfer.
2020-01-15 15:58:49,242  INFO: [req:O5bvIlU] 127.0.0.1 "GET / HTTP/1.1" 200 165 "-" "curl/7.68.0"
2020-01-15 15:58:49,959  INFO: [req:xtMacpA] 127.0.0.1 "GET / HTTP/1.1" 500 165 "-" "curl/7.68.0"
```


Installation
------------

```shell
$ python3 -m pip install https://github.com/messa/aiohttp-request-id-logging/archive/v0.0.4.zip
```

Or add this line to `requirements.txt`:

```
aiohttp-request-id-logging @ https://github.com/messa/aiohttp-request-id-logging/archive/v0.0.4.zip
```


Usage
-----

```python
from aiohttp import web
from aiohttp.web_log import AccessLogger
from aiohttp_request_id_logging import (
    setup_logging_request_id_prefix,
    request_id_middleware,
    RequestIdContextAccessLogger)

async def hello(request):
    return web.Response(text="Hello, world!\n")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(threadName)s] %(name)-26s %(levelname)5s: %(requestIdPrefix)s%(message)s')

setup_logging_request_id_prefix()

app = web.Application(middlewares=[request_id_middleware()])
app.add_routes([web.get('/', hello)])

web.run_app(app, access_log_class=RequestIdContextAccessLogger)
```

For more complete example see [demo.py](demo.py).


How it works
------------

This library helps you to add request (correlation) id to the log messages in a few steps:

1. **`request_id_middleware()`:** Generate random `request_id` for each aiohttp request and

   - store it in a ContextVar `aiohttp_request_id_logging.request_id`
   - store it also in `request['request_id']`

2. **`setup_logging_request_id_prefix()`:** Modify logging record factory so that the request_id is attached to every logging record created

   - so you should modify your log format, for example `logging.basicConfig(format=... %(levelname)5s: %(requestIdPrefix)s%(message)s')`

3. Because the aiohttp access logging happens out of the middleware scope, the request id ContextVar would be already resetted. So **`RequestIdContextAccessLogger`** is provided that adds the request_id to the access log message.

4. If you use **[Sentry](https://docs.sentry.io/platforms/python/aiohttp/)**, a `request_id` [tag](https://docs.sentry.io/enriching-error-data/context/?platform=python#tagging-events) is added when the request is processed.

Sentry integration will be active only if you have `sentry_sdk` installed.

Motivation: https://stackoverflow.com/a/58801740/196206
