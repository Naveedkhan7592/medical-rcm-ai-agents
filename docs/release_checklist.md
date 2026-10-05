# Release Checklist

Use this checklist before publishing or sharing a portfolio snapshot:

- [ ] `python scripts/check_project.py` passes.
- [ ] `python scripts/check_docs.py` reports no broken local Markdown links.
- [ ] `python scripts/validate_n8n_workflows.py` validates the exports.
- [ ] `python scripts/evaluate_demo_scenarios.py` passes all declared expectations.
- [ ] `python -m pytest -q` passes.
- [ ] FastAPI starts and `/health`, `/ready`, and `/docs` are reachable.
- [ ] Streamlit starts with `python -m streamlit run dashboard/streamlit_app.py` and required pages load.
- [ ] No `.env`, API keys, database passwords, tokens, or Streamlit secrets are committed.
- [ ] No `.env` or `.streamlit/secrets.toml` is tracked.
- [ ] All fixtures and screenshots are synthetic; no PHI or real payer/member records are present.
- [ ] README commands and local links match the current repository.
- [ ] `.github/workflows/ci.yml` parses and uses standard repository-relative commands.
- [ ] Docker status is stated honestly; do not claim a build/runtime test if Docker was unavailable.
- [ ] The repository owner has selected a LICENSE before public release.
- [ ] No production, clinical correctness, payer compliance, or HIPAA compliance claim has been added.
- [ ] Python remains authoritative and no external healthcare action has been introduced.
