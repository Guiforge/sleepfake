.PHONY: help lint test test-all test-all-python pre-commit coverage dist \
        check-uv prod-install dev-install upgrade-dep \
        clean clean-build clean-pyc clean-test
.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
UV             := uv run
PYTHON_VERSIONS := 3.10 3.11 3.12 3.13 3.14 3.15

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

BROWSER := python -c "$$BROWSER_PYSCRIPT"

ifeq ($(TERM),)
    YELLOW=
    GREEN=
    BLUE=
    UNDERLINE=
    NOCOLOR=
else
    YELLOW=$$(tput setaf 3)
    GREEN=$$(tput setaf 2)
    BLUE=$$(tput setaf 4)
    UNDERLINE=$$(tput smul)
    NOCOLOR=$$(tput sgr0)
endif

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help: ## show this help message
	@python3 -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
lint: ## run ruff (check + format) and mypy
	$(UV) ruff check --fix .
	$(UV) ruff format .
	$(UV) mypy --version
	$(UV) mypy --python-version '3.10' --pretty --config-file pyproject.toml src
	@echo "${GREEN}✅ Lint checks passed!${NOCOLOR}"

test: ## run tests quickly with the default Python
	@echo "${BLUE}🧪 Running tests...${NOCOLOR}"
	$(UV) pytest --force-sugar -vvv

test-all: lint test ## run lint then tests

test-all-python: ## run tests against all supported Python versions
	@for version in $(PYTHON_VERSIONS); do \
		echo "${GREEN}🧪 Testing Python $$version...${NOCOLOR}"; \
		uv run --python $$version pytest --force-sugar -vvv || exit 1; \
	done
	@echo "${GREEN}✅ All Python versions passed!${NOCOLOR}"

pre-commit: ## run pre-commit hooks on all files
	@echo "${GREEN}🔨 Running pre-commit hooks...${NOCOLOR}"
	$(UV) pre-commit run --all-files

coverage: ## check code coverage quickly with the default Python
	$(UV) coverage run --source src -m pytest -vvv
	$(UV) coverage report -m
	$(UV) coverage html
	$(BROWSER) htmlcov/index.html

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
dist: clean prod-install ## builds source and wheel package
	uvx --from build pyproject-build --installer uv

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
check-uv: ## verify uv is installed
	@uv --version || (echo "Install uv: https://docs.astral.sh/uv/getting-started/installation/"; exit 1)

prod-install: check-uv ## install production dependencies only
	uv sync --no-dev

dev-install: check-uv ## install all dependencies and pre-commit hooks
	uv sync --dev
	$(UV) pre-commit install
	@echo "🧊🚀  ${GREEN}Have a good day of coding ${NOCOLOR}  🚀🧊"

upgrade-dep: check-uv ## upgrade all dependencies and pre-commit hooks
	@echo "${GREEN}🔄 Upgrading dependencies...${NOCOLOR}"
	uv sync -U
	$(UV) pre-commit autoupdate
	@echo "${GREEN}✅ Dependencies upgraded!${NOCOLOR}"

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
clean: clean-build clean-pyc clean-test ## remove all build, test, and compiled artifacts

clean-build: ## remove build artifacts
	rm -rf dist/ build/ .eggs/
	find . -name '*.egg-info' -exec rm -rf {} +
	find . -name '*.egg' -exec rm -f {} +

clean-pyc: ## remove Python compiled files
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

clean-test: ## remove test and coverage artifacts
	rm -rf .pytest_cache/ htmlcov/ .coverage
