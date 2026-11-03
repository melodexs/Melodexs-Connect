# Common tasks. Every target is safe: tests use a scratch database.
PY ?= python
SCRATCH ?= /tmp/melodexs-scratch.db

.PHONY: help test test-file run lint clean

help:
	@echo "make test     run the full suite against a scratch SQLite database"
	@echo "make test-file F=tests/test_api.py   run one file"
	@echo "make run      serve the API locally on SQLite"
	@echo "make lint     syntax-level checks (ruff)"
	@echo "make clean    remove scratch databases"

test:
	cd apps/api-python && PYTHON_TEST_DATABASE_URL=sqlite:///$(SCRATCH) $(PY) -m pytest tests/ -q

test-file:
	cd apps/api-python && PYTHON_TEST_DATABASE_URL=sqlite:///$(SCRATCH) $(PY) -m pytest $(F) -q

run:
	cd apps/api-python && DATABASE_URL=sqlite:///./local.db $(PY) -m uvicorn app.main:app --reload

lint:
	$(PY) -m ruff check app tests || true

clean:
	rm -f $(SCRATCH) apps/api-python/local.db
