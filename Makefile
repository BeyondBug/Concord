# Concord Developer Makefile
.PHONY: setup dev test lint clean demo build

setup:
	pip install -r requirements/dev.txt
	cp -n .env.example .env 2>/dev/null || copy .env.example .env

dev:
	docker compose up -d postgres redis
	uvicorn api.main:app --reload --port 8000

test:
	pytest tests/unit -v --tb=short

test-all:
	pytest tests/ -v --tb=short

lint:
	ruff check .

build:
	docker build -t ghcr.io/beyondbug/concord:latest .

demo:
	bash scripts/demo.sh

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
