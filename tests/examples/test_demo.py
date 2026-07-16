"""
Run every example in examples/ (aiohttp server with request id logging
implemented) and try to call it.

The examples are run one by one - each test starts the example server
on a free port, calls it and checks the response, the response header
with the request id and the log output.
"""

from aiohttp import ClientSession
from asyncio import run
from collections import namedtuple
from contextlib import contextmanager
from logging import getLogger
from os import environ
from pytest import fixture
import re
from socket import socket
from subprocess import Popen, DEVNULL, PIPE, check_call
from sys import executable as python_executable
from threading import Thread
from time import sleep


logger = getLogger(__name__)


DemoSpec = namedtuple("DemoSpec", "filename response_header_name expected_info_lines")

# For each example: the response header carrying the request id and the
# expected INFO log lines (regexps) produced by one GET / request.
# Each line is expected to be prefixed with "[req:...]" with the same
# request id that is returned in the response header.
demo_specs = [
    DemoSpec(
        filename="demo.py",
        response_header_name="X-Request-Id",
        expected_info_lines=[
            r"Processing GET / \(__main__:hello\)$",
            r"Doing something$",
            r'.*"GET /.* 200 .*$',
        ],
    ),
    DemoSpec(
        filename="demo_legacy.py",
        response_header_name="X-Request-Id",
        expected_info_lines=[
            r"Processing GET / \(__main__:hello\)$",
            r"Doing something$",
            r'.*"GET /.* 200 .*$',
        ],
    ),
    DemoSpec(
        filename="demo_customization_injection.py",
        response_header_name="X-Demo-Request-Id",
        expected_info_lines=[
            r"Started processing GET / from .+$",
            r"Doing something$",
            r'.*"GET /.* 200 .*$',
        ],
    ),
    DemoSpec(
        filename="demo_customization_subclassing.py",
        response_header_name="X-Demo-Request-Id",
        expected_info_lines=[
            r"Started processing GET / \(handler: __main__:hello\)$",
            r"Doing something$",
            r"Done, response status: 200$",
            r'.*"GET /.* 200 .*$',
        ],
    ),
]


@fixture(params=demo_specs, ids=lambda spec: spec.filename)
def demo_spec(request):
    return request.param


@fixture
def demo_path(examples_dir, demo_spec):
    demo_path = examples_dir / demo_spec.filename
    assert demo_path.is_file()
    return demo_path


def test_demo_help(demo_path):
    cmd = [python_executable, str(demo_path), "--help"]
    logger.debug("Running command: %r", cmd)
    assert check_call(cmd) == 0


def get_free_port():
    with socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def tcp_connect_works(host, port):
    with socket() as s:
        s.settimeout(0.1)
        try:
            s.connect((host, port))
            return True
        except ConnectionRefusedError:
            return False


def read_output(stream, lines, label):
    try:
        for line in stream:
            line = line.decode("utf-8").rstrip()
            lines.append(line)
            logger.info("%s: %s", label, line)
    finally:
        stream.close()


RunningDemo = namedtuple("RunningDemo", "process port stdout_lines stderr_lines")


@fixture
def run_demo(demo_path):
    @contextmanager
    def do_run_demo():
        port = get_free_port()
        cmd = [python_executable, str(demo_path), "--port", str(port)]
        cmd_env = {
            **environ,
            "PYTHONDEVMODE": "1",  # Enable printing of warnings, e.g. NotAppKeyWarning
            "SKIP_SLEEP": "1",  # Make the examples run faster by skipping the demostration sleep() calls
        }
        with Popen(cmd, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=cmd_env) as process:
            stdout_lines = []
            stderr_lines = []
            stdout_thread = Thread(target=read_output, args=(process.stdout, stdout_lines, "stdout"), daemon=True)
            stderr_thread = Thread(target=read_output, args=(process.stderr, stderr_lines, "stderr"), daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            try:
                logger.info("Started command %s as pid %d", cmd, process.pid)

                # Wait for the server to start up and accept connections
                for _ in range(100):
                    sleep(0.01)
                    assert process.poll() is None
                    if tcp_connect_works("localhost", port):
                        break
                else:
                    raise RuntimeError("Server did not start")

                yield RunningDemo(process, port, stdout_lines, stderr_lines)
            finally:
                if process.poll() is not None:
                    logger.info("Process %d has already terminated with return code %d", process.pid, process.returncode)
                else:
                    # Shut down the server
                    logger.info("Terminating process %d", process.pid)
                    process.terminate()
                    process.wait()
                    logger.info("Process %d terminated with return code %d", process.pid, process.returncode)
                # Wait for the threads to finish
                stdout_thread.join()
                stderr_thread.join()

    return do_run_demo


def test_demo_hello_world(run_demo, demo_spec):
    async def fetch(port):
        async with ClientSession() as session:
            async with session.get(f"http://localhost:{port}/") as response:
                return await response.text(), response.headers.get(demo_spec.response_header_name)

    with run_demo() as demo:
        text, header_req_id = run(fetch(demo.port))
        assert text == "Hello, world!\n"
        assert header_req_id

    lines = [line for line in demo.stderr_lines if "INFO" in line and " asyncio " not in line]
    assert len(lines) == 1 + len(demo_spec.expected_info_lines)

    # the startup message is logged outside of any request, so it has no request id prefix
    assert re.match(rf".*  INFO: Listening on http://localhost:{demo.port}$", lines[0])

    # all the request-related lines carry the same request id
    # and it matches the one returned in the response header
    for line, expected in zip(lines[1:], demo_spec.expected_info_lines):
        m = re.match(rf".*  INFO: \[req:([a-zA-Z0-9]+)\] {expected}", line)
        assert m, f"Line does not match {expected!r}: {line!r}"
        assert m.group(1) == header_req_id

    # Warnings coming from aiohttp/asyncio internals that we cannot do anything about
    whitelisted_warnings = [
        r"DeprecationWarning: Setting custom Request\._transport_sockname attribute is discouraged",
        # aiohttp web_urldispatcher.py on Python 3.14:
        r"DeprecationWarning: 'asyncio\.iscoroutinefunction' is deprecated",
        # asyncio debug mode (PYTHONDEVMODE=1) slow task/callback warning on a slow machine (CI):
        r"asyncio\s+WARNING: Executing <(Task|Handle).* took [\d.]+ seconds",
    ]

    stderr_is_clean = True
    for line in demo.stderr_lines:
        if any(re.search(w, line) for w in whitelisted_warnings):
            logger.info("Ignoring whitelisted warning in stderr line: %s", line)
        elif "ERROR" in line:
            logger.error("Have error in stderr line: %r", line)
            stderr_is_clean = False
        elif "WARNING" in line or "Warning" in line:
            logger.error("Have warning in stderr line: %s", line)
            stderr_is_clean = False

    assert stderr_is_clean


def test_demo_fail(run_demo, demo_spec):
    """
    The /f handler raises an exception - the middleware converts it
    to a 500 response and logs the exception with the request id prefix.
    """

    async def fetch(port):
        async with ClientSession() as session:
            async with session.get(f"http://localhost:{port}/f") as response:
                return response.status, await response.text(), response.headers.get(demo_spec.response_header_name)

    with run_demo() as demo:
        status, text, header_req_id = run(fetch(demo.port))
        assert status == 500
        assert text == "500 Internal Server Error\n"
        # the request id header is added even to the error response
        assert header_req_id

    # the exception is logged (with traceback) with the request id prefix
    error_lines = [line for line in demo.stderr_lines if " ERROR: " in line]
    assert len(error_lines) == 1
    m = re.match(r".* ERROR: \[req:([a-zA-Z0-9]+)\] Error handling request: Exception\('test exception'\)$", error_lines[0])
    assert m, f"Line does not match: {error_lines[0]!r}"
    assert m.group(1) == header_req_id
    assert any("Traceback (most recent call last):" in line for line in demo.stderr_lines)
    assert any(line == "Exception: test exception" for line in demo.stderr_lines)

    # the access log line has the same request id and status 500
    assert any(re.match(rf'.*  INFO: \[req:{re.escape(header_req_id)}\] .*"GET /f.* 500 .*$', line) for line in demo.stderr_lines)


def test_demo_log_error(run_demo, demo_spec):
    """
    The /e handler logs an error - the error line carries the request id
    prefix; the response is a normal 200.
    """

    async def fetch(port):
        async with ClientSession() as session:
            async with session.get(f"http://localhost:{port}/e") as response:
                return response.status, await response.text(), response.headers.get(demo_spec.response_header_name)

    with run_demo() as demo:
        status, text, header_req_id = run(fetch(demo.port))
        assert status == 200
        assert text == "Hello, world!\n"
        assert header_req_id

    error_lines = [line for line in demo.stderr_lines if " ERROR: " in line]
    assert len(error_lines) == 1
    m = re.match(r".* ERROR: \[req:([a-zA-Z0-9]+)\] test error log$", error_lines[0])
    assert m, f"Line does not match: {error_lines[0]!r}"
    assert m.group(1) == header_req_id
