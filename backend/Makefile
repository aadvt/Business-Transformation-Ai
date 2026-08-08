.PHONY: dev test openapi install

install:
	python -m venv .venv
	.venv/Scripts/python -m pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q

openapi:
	python scripts/export_openapi.py
