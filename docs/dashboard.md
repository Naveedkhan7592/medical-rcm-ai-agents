# RCM Operations Dashboard

The dashboard is a synthetic demo interface for the existing Medical RCM project. It reads the repository’s demo data from the `data/` folder and presents portfolio-level operational views without changing the underlying Python business logic.

## Purpose

The dashboard provides a human-readable view of:

- overall claim workload
- billed and paid totals
- denial exposure
- A/R balance and age
- payment performance
- human review queue
- audit-friendly operational context

This is not a production healthcare application and does not claim HIPAA compliance.

## Run locally

From the project root:

```bash
python -m streamlit run dashboard/streamlit_app.py
```

## Safety constraints

- Synthetic/demo data only
- No external payer integration
- No claim, appeal, or payment submission logic in the UI
- Human review remains a manual approval workflow
- Metric values are based on the repo data files and not on fabricated business results

## Pages

- Executive Overview
- Claims
- Denials
- Payments
- A/R
- Human Review
- Demo Scenarios
- Agent Evaluation
