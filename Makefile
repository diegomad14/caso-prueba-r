.PHONY: install lint test run clean

install:
	pip install -e '.[dev]'

lint:
	ruff check .

test:
	pytest -q

run:
	python -m src.reconciliation.cli run --config config.yml

clean:
	rm -f outputs/*.csv outputs/*.txt
