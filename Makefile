.PHONY: clean clean-test clean-pyc clean-build docs help test-all-python
.DEFAULT_GOAL := help

define BROWSER_PYSCRIPT
import os, webbrowser, sys

from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

BROWSER := python3.12 -c "$$BROWSER_PYSCRIPT"

ifeq ($(TERM),)
    YELLOW=
    GREEN=
    UNDERLINE=
    NOCOLOR=
else
    YELLOW=$$(tput setaf 3)
    GREEN=$$(tput setaf 2)
    UNDERLINE=$$(tput smul)
    NOCOLOR=$$(tput sgr0)
endif

help:
	@python3.12 -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

lint:
	uv run ruff check --fix .
	uv run ruff format .
	uv run mypy --version
	uv run mypy --python-version '3.10' --pretty --config-file pyproject.toml src
	@echo "${GREEN}✅ Lint checks passed!${NOCOLOR}"

test: ## run tests quickly with the default Python
	@echo "${BLUE}🧪 Running tests...${NOCOLOR}"
	uv run pytest --force-sugar -vvv

test-all: lint test

test-all-python: ## run tests against all supported Python versions
	@for version in 3.10 3.11 3.12 3.13 3.14 3.15; do \
		echo "${GREEN}🧪 Testing Python $$version...${NOCOLOR}"; \
		uv run --python $$version pytest --force-sugar -vvv || exit 1; \
	done
	@echo "${GREEN}✅ All Python versions passed!${NOCOLOR}"

pre-commit:
	@echo "${GREEN}🔨 Running pre-commit hooks...${NOCOLOR}"
	uv run pre-commit run --all-files

coverage: ## check code coverage quickly with the default Python
	uv run coverage run --source src -m pytest -vvv
	uv run coverage report -m
	uv run coverage html
	$(BROWSER) htmlcov/index.html

dist: clean prod-install## builds source and wheel package
	uvx --from build pyproject-build --installer uv

check-uv:
	@uv --version || (echo "Intall uv 'https://docs.astral.sh/uv/getting-started/installation/'"; exit 1)

prod-install: check-uv
	uv sync --no-dev

dev-install: check-uv
	uv sync --dev
	uv run pre-commit install
	@echo "🧊🚀  ${GREEN}Have a good day of coding ${NOCOLOR}  🚀🧊"

upgrade-dep: check-uv
	@echo "${GREEN}🔄 Upgrading dependencies...${NOCOLOR}"
	uv sync -U
	uv run pre-commit autoupdate
	@echo "${GREEN}✅ Dependencies upgraded!${NOCOLOR}"
