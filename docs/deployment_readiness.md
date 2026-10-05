# Deployment Readiness

## Scope

This project is a synthetic portfolio/demo system and is not production healthcare infrastructure. It does not claim clinical correctness, payer compliance, HIPAA compliance, or production readiness. Python remains authoritative for RCM decisions. There are no real payer, clearinghouse, or eClinicalWorks integrations and no autonomous external healthcare actions.

## Local architecture

- FastAPI exposes the existing agent and supervisor contracts.
- SQLAlchemy uses a local SQLite default so imports, health checks, and demo work do not require PostgreSQL. Set `DATABASE_URL` explicitly to use a configured database.
- Initialize and seed the local API database with `python scripts/seed_data.py` before using database-backed claim endpoints. The seed source is synthetic data under `data/`.
- `GET /health` reports service health; `GET /ready` reports application-level synthetic-demo readiness only. `GET /db/health` separately executes a database query.
- Streamlit remains at `dashboard/streamlit_app.py` and can run without starting the API server for its local synthetic data views.
- n8n JSON files are exported orchestration examples; a live n8n runtime is not required for tests or validation.

## Configuration

OpenAI is optional. `OPENAI_API_KEY` defaults to blank, and importing the API, running evaluations, and using the dashboard require no key. The configured default database is SQLite. `.env.example` contains placeholders and a local SQLite URL. Compose defines only the separate PostgreSQL service and requires `POSTGRES_PASSWORD` to be supplied from the operator's environment; no password is committed. CORS is not enabled because the current local dashboard and API setup does not require cross-origin browser requests.

Never commit `.env`, `.streamlit/secrets.toml`, credentials, real patient data, or payer data. `.gitignore` excludes local secrets and the default SQLite database.

## CI architecture

GitHub Actions runs on pushes and pull requests using Python 3.12. It installs `requirements.txt`, smoke-imports FastAPI/evaluation/dashboard modules, runs `scripts/check_project.py`, validates exported n8n workflows, runs the synthetic evaluation CLI, and executes the full pytest suite. CI requires no API credentials, PostgreSQL, Docker, or n8n runtime. Package installation is the only network-dependent step.

## Validation gates

The project checker verifies required paths, core imports, the scenario catalog, workflow JSON, dashboard entrypoint syntax, and placeholder configuration safety. `scripts/validate_n8n_workflows.py` validates workflow structure and forbidden secret/external endpoint patterns. `scripts/evaluate_demo_scenarios.py` compares real local synthetic scenario outcomes against declared expectations; latency is observational and never gates pass/fail. The full test suite uses fakes or isolated SQLite fixtures for deterministic coverage.

FastAPI retains its standard technical error responses: request validation errors use HTTP 422, missing resources use HTTP 404, and database health failures use HTTP 503. A supervisor `REVIEW` is a successful business response (HTTP 200), not a technical error. Business `task_id` remains separate and unchanged; no request-correlation middleware has been added.

## Run commands

```bash
python -m pip install -r requirements.txt
python scripts/seed_data.py
python -m uvicorn app.main:app --reload
python -m streamlit run dashboard/streamlit_app.py
python scripts/check_project.py
python scripts/validate_n8n_workflows.py
python scripts/evaluate_demo_scenarios.py
python -m pytest -q
```

## Docker status

There is no FastAPI Dockerfile in this repository. `docker-compose.yml` currently defines only an optional PostgreSQL service, with its password supplied through `POSTGRES_PASSWORD`. Docker is not part of the deterministic test or CI path. No image build or container runtime is claimed by this readiness step.

## Known limitations

The data and identifiers are synthetic; payer policies and coding references are illustrative only. The application has no production authentication, authorization, privacy program, clinical validation, payer integration, external action capability, or production monitoring stack. The Starlette `BlockingPortal` deprecation warning originates upstream and may remain depending on dependency versions.
