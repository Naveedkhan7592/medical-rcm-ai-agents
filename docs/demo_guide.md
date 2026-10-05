# Demo Guide

A 5–10 minute walkthrough using synthetic records. Have two terminals open at the project root and activate the project virtual environment in both.

## Before the call

Install dependencies with `python -m pip install -r requirements.txt`. The demo does not need an OpenAI API key, Docker, PostgreSQL, or an n8n runtime.

## Walkthrough

1. **Start FastAPI:** run `python scripts/seed_data.py`, then `python -m uvicorn app.main:app --reload` in the API terminal. The command seeds only the repository's synthetic data into local SQLite.
2. **Open Swagger:** visit `http://127.0.0.1:8000/docs`.
3. **Show health/readiness:** call `GET /health` and `GET /ready`. Explain that `/ready` is application-level; `/db/health` is separate.
4. **Start Streamlit:** in the second terminal run `python -m streamlit run dashboard/streamlit_app.py` and open the local URL printed by Streamlit.
5. **Show Executive Overview:** point out that its totals are from synthetic demo data.
6. **Show Denials and A/R:** use the sidebar to inspect denial records and the A/R view. Call out that the small references and thresholds are illustrative, not payer guidance.
7. **Show Demo Scenarios:** select an eligibility or coding case and show routed specialists, findings, next action, and the human-review requirement.
8. **Show Agent Evaluation:** show expected-vs-observed status/routing, safety, review rate, and timing. Explain that latency is informational and the scenarios are not clinical validation.
9. **Explain the review boundary:** appeal drafts are never submitted; no external payer or financial action is run. Python owns deterministic decisions; n8n exports only orchestrate.
10. **Show quality gates:** run `python scripts/evaluate_demo_scenarios.py`, `python scripts/validate_n8n_workflows.py`, and `python -m pytest -q`.

## Optional follow-up

Show `workflows/n8n/README.md` and the inactive workflow exports to explain how a local n8n instance could call the API. Do not imply the checked-in exports were runtime-tested in an n8n deployment.
