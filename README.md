# Medical RCM AI Agents Demo

A starter structure for a Python/FastAPI multi-agent medical revenue cycle management demo using synthetic data only.

This repository currently contains project scaffolding only. Agent logic, API routes, data generators, and workflows have not been implemented.

## Structure

```text
.
├── src/
│   └── medical_rcm/
│       ├── api/
│       ├── agents/
│       ├── data/
│       ├── models/
│       └── services/
├── tests/
├── .env.example
└── requirements.txt
```

## Setup

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` when runtime configuration is added. Use synthetic records only; do not add real patient or payer data.
