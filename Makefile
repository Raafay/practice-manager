# Common commands. See CLAUDE.md.
.PHONY: setup dev test lint format seed css migrate worker

setup:
	uv sync
	uv run python manage.py migrate
	uv run python manage.py tailwind build

dev:
	uv run python manage.py tailwind runserver

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

seed:
	uv run python manage.py seed_demo

css:
	uv run python manage.py tailwind build

migrate:
	uv run python manage.py migrate

worker:
	uv run python manage.py worker
