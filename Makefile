VENV ?= .venv
PYTHON ?= python3.12
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
VENV_UVICORN := $(VENV)/bin/uvicorn
VENV_ALEMBIC := $(VENV)/bin/alembic

.PHONY: install migrate seed dev clean

install:
	@if [ ! -d "$(VENV)" ]; then $(PYTHON) -m venv $(VENV); fi
	$(VENV_PIP) install -r requirements.txt -r requirements-dev.txt

migrate:
	$(VENV_ALEMBIC) upgrade head

seed:
	PYTHONPATH=. $(VENV_PYTHON) -m scripts.seed_system_init

dev:
	PYTHONPATH=. $(VENV_UVICORN) main:app --host 0.0.0.0 --port 8000 --reload

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".DS_Store" -delete
