.PHONY: up down logs ps lint test compose-config

up:
	cd infra && docker compose up -d --build

down:
	cd infra && docker compose down

logs:
	cd infra && docker compose logs -f --tail=200

ps:
	cd infra && docker compose ps

compose-config:
	cd infra && docker compose config >/dev/null && echo "compose ok"

test:
	pytest -q

lint:
	python -m compileall pipelines services tests
