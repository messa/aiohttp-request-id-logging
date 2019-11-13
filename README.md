aiohttp-request-id-logging
==========================

WIP

See https://stackoverflow.com/a/58801740/196206


Example
-------

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
