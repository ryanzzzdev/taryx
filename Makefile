.PHONY: install sync web-install up down reset lint format-check typecheck contracts test web-check check

sync:
	uv sync --frozen

web-install:
	cd web && npm ci

install: sync web-install

up:
	docker compose up --build

down:
	docker compose down

reset:
	docker compose down -v

lint:
	uv run ruff check src tests manage.py
	uv run ruff format --check src tests manage.py

typecheck:
	uv run mypy src

contracts:
	./scripts/check-import-boundaries.sh

test:
	uv run pytest -q

web-check:
	cd web && npm run typecheck && npm run build

check: lint typecheck contracts test web-check
