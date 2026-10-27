.PHONY: install test run docker-up docker-test clean

install:
	pip install -r requirements-dev.txt

test:
	python -m pytest -q

run:
	python -m iris_spv ingest --source fixture
	python -m iris_spv crosscheck --reference fixtures/reference_sample.jsonl
	python -m iris_spv report

docker-up:
	cp -n .env.example .env || true
	docker compose up --build --abort-on-container-exit

docker-test:
	cp -n .env.example .env || true
	docker compose run --rm app python -m pytest -q

clean:
	rm -f iris_local.db
