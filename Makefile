.PHONY: up test migrate seed
up:
	docker compose up --build

test:
	pytest -q

migrate:
	alembic upgrade head

seed:
	python -m app.seed
