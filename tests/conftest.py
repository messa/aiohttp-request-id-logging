from pathlib import Path
from pytest import fixture


@fixture(scope='session')
def project_dir():
    proj_dir = Path(__file__).resolve().parent.parent
    assert (proj_dir / 'examples').is_dir()
    assert (proj_dir / 'tests').is_dir()
    return proj_dir


@fixture(scope='session')
def examples_dir(project_dir):
    return project_dir / 'examples'
