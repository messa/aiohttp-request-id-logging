venv_dir=venv
python=python3

default: check lint

check: $(venv_dir)/bin/pytest
	$(venv_dir)/bin/pytest -vs tests $(pytest_args)

lint: $(venv_dir)/bin/flake8
	$(venv_dir)/bin/flake8 . --show-source --statistics

$(venv_dir)/bin/pytest: $(venv_dir)/packages-installed
	$(venv_dir)/bin/python -m pip install pytest

$(venv_dir)/bin/flake8: $(venv_dir)/packages-installed
	$(venv_dir)/bin/python -m pip install flake8

$(venv_dir)/packages-installed:
	test -d $(venv_dir) || $(python) -m venv $(venv_dir)
	$(venv_dir)/bin/python -m pip install -U pip wheel
	$(venv_dir)/bin/python -m pip install -e .
	touch $@

.PHONY: default check lint
