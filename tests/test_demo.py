from aiohttp import ClientSession
from asyncio import run
from collections import namedtuple
from contextlib import contextmanager
from logging import getLogger
from pathlib import Path
from pytest import fixture
import re
from socket import socket
from subprocess import Popen, DEVNULL, PIPE
from threading import Thread
from time import sleep


test_port = 8080

logger = getLogger(__name__)


@fixture(scope='session')
def demo_executable():
    project_dir = Path(__file__).resolve().parent.parent
    demo_path = project_dir / 'demo.py'
    assert demo_path.is_file()
    return demo_path


def tcp_connect_works(host, port):
    with socket() as s:
        try:
            s.connect((host, port))
            return True
        except ConnectionRefusedError:
            return False


def read_output(stream, lines, label):
    try:
        for line in stream:
            line = line.decode('utf-8').rstrip()
            lines.append(line)
            logger.info('%s: %s', label, line)
    finally:
        stream.close()


RunningDemo = namedtuple('RunningDemo', 'process stdout_lines stderr_lines')


@fixture
def run_demo(demo_executable):
    @contextmanager
    def do_run_demo():
        cmd = ['python3', str(demo_executable)]
        with Popen(cmd, stdin=DEVNULL, stdout=PIPE, stderr=PIPE) as process:
            stdout_lines = []
            stderr_lines = []
            stdout_thread = Thread(target=read_output, args=(process.stdout, stdout_lines, 'stdout'), daemon=True)
            stderr_thread = Thread(target=read_output, args=(process.stderr, stderr_lines, 'stderr'), daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            try:
                logger.info('Started command %s as pid %d', cmd, process.pid)

                # Wait for the server to start up and accept connections
                for _ in range(100):
                    sleep(0.01)
                    assert process.poll() is None
                    if tcp_connect_works('localhost', test_port):
                        break
                else:
                    raise RuntimeError('Server did not start')

                yield RunningDemo(process, stdout_lines, stderr_lines)
            finally:
                if process.poll() is not None:
                    logger.info(
                        'Process %d has already terminated with return code %d',
                        process.pid, process.returncode)
                else:
                    # Shut down the server
                    logger.info('Terminating process %d', process.pid)
                    process.terminate()
                    process.wait()
                    logger.info(
                        'Process %d terminated with return code %d',
                        process.pid, process.returncode)
                # Wait for the threads to finish
                stdout_thread.join()
                stderr_thread.join()
    return do_run_demo


def test_hello_world(run_demo):
    async def fetch():
        async with ClientSession() as session:
            async with session.get(f'http://localhost:{test_port}/') as response:
                return await response.text()

    with run_demo() as demo:
        text = run(fetch())
        assert text == 'Hello, world!\n'

    lines = [line for line in demo.stderr_lines if 'DEBUG' not in line]
    assert len(lines) == 3
    m0 = re.match(r'.*  INFO: \[req:([a-zA-Z0-9]+)\] Processing GET / \(__main__:hello\)$', lines[0])
    m1 = re.match(r'.*  INFO: \[req:([a-zA-Z0-9]+)\] Doing something$', lines[1])
    m2 = re.match(r'.*  INFO: \[req:([a-zA-Z0-9]+)\] .*GET /.* 200 .*$', lines[2])
    assert m0
    assert m1
    assert m2
    assert m0.groups() == m1.groups()
    assert m0.groups() == m2.groups()
