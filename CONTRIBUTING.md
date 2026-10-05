# Contributing

Contributions should keep the project a synthetic portfolio/demo system and preserve Python as the authority for RCM decisions.

## Setup and checks

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python scripts/check_project.py
python scripts/check_docs.py
python scripts/validate_n8n_workflows.py
python scripts/evaluate_demo_scenarios.py
python -m pytest -q
```

Activate the virtual environment before installing or running checks (`.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` on macOS/Linux).

## Change boundaries

- Use synthetic/demo records only. Never add PHI or real payer/member data.
- Do not commit `.env`, API keys, passwords, tokens, or Streamlit secrets.
- Keep business rules and final RCM decisions in deterministic Python services/agents; n8n and the dashboard orchestrate or display results.
- Do not add autonomous payer, claim, appeal, payment-posting, or patient-financial actions.
- Add or update focused tests when changing agent behavior, routing, contracts, evaluation, or safety boundaries.
- New agent behavior requires deterministic tests and explicit human-review behavior where appropriate.
- Keep scenario expectations observational; do not change outcomes solely to make evaluation pass.

This repository is not production healthcare software and makes no compliance claim.
