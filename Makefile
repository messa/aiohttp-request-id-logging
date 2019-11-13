venv_dir=venv
python=python3

check: $(venv_dir)/bin/pytest
	$(venv_dir)/bin/pytest -vs tests

$(venv_dir)/bin/pytest: $(venv_dir)/packages-installed
	$(venv_dir)/bin/python -m pip install pytest

$(venv_dir)/packages-installed:
	test -d $(venv_dir) || $(python) -m venv $(venv_dir)
	$(venv_dir)/bin/python -m pip install -U pip wheel
	$(venv_dir)/bin/python -m pip install -e .
