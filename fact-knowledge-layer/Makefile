.PHONY: run test lint fmt install

install:
	pip install -e ".[dev]"

run:
	uvicorn fkl.main:app --reload --port 8000

test:
	pytest tests/ -v

lint:
	ruff check src/

fmt:
	black src/ tests/

seed:
	python scripts/seed_demo.py

export:
	python scripts/export_sample_output.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
