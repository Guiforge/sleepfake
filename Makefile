.PHONY: help lint lint-ci test test-all test-all-python hooks cov coverage dist \
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
lint: ## run ruff (fix + format) and ty
	$(UV) ruff check --fix .
	$(UV) ruff format .
	$(UV) ty check
	@echo "${GREEN}✅ Lint checks passed!${NOCOLOR}"

lint-ci: ## run ruff and ty without modifying files (fails on any issue)
	$(UV) ruff check --no-fix .
	$(UV) ruff format --check .
	$(UV) ty check

test: ## run tests quickly with the default Python
	@echo "${BLUE}🧪 Running tests...${NOCOLOR}"
	$(UV) pytest

test-all: lint test ## run lint then tests

test-all-python: ## run tests against all supported Python versions
	@for version in $(PYTHON_VERSIONS); do \
		echo "${GREEN}🧪 Testing Python $$version...${NOCOLOR}"; \
		uv run --python $$version pytest || exit 1; \
	done
	@echo "${GREEN}✅ All Python versions passed!${NOCOLOR}"

hooks: ## run prek hooks on all files
	$(UV) prek run --all-files

cov: ## run tests under coverage and enforce the 100% floor
	rm -f .coverage .coverage.*
	$(UV) coverage run -m pytest
	$(UV) coverage combine -q
	$(UV) coverage report

coverage: cov ## same as cov, then open the HTML report
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

dev-install: check-uv ## install all dependencies and prek hooks
	uv sync --dev
	$(UV) prek install
	@echo "🧊🚀  ${GREEN}Have a good day of coding ${NOCOLOR}  🚀🧊"

upgrade-dep: check-uv ## upgrade all dependencies and prek hooks
	@echo "${GREEN}🔄 Upgrading dependencies...${NOCOLOR}"
	uv sync -U
	$(UV) prek update
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
