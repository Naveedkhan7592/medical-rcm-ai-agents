from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd


def metric_card(title: str, value: Any, *, help_text: str | None = None) -> dict[str, Any]:
    return {
        "title": title,
        "value": value,
        "help_text": help_text,
    }


def claims_table(data: list[dict[str, Any]]) -> pd.DataFrame:
    if not data:
        return pd.DataFrame(columns=["claim_id", "patient_id", "payer", "provider_id", "service_date", "claim_amount", "status"])
    dataframe = pd.DataFrame(data)
    return dataframe[["claim_id", "patient_id", "payer", "provider_id", "service_date", "claim_amount", "status"]]


def denials_table(data: list[dict[str, Any]]) -> pd.DataFrame:
    if not data:
        return pd.DataFrame(columns=["denial_id", "claim_id", "carc_code", "rarc_code", "reason", "denied_amount", "status"])
    dataframe = pd.DataFrame(data)
    return dataframe[["denial_id", "claim_id", "carc_code", "rarc_code", "reason", "denied_amount", "status"]]


def payments_table(data: list[dict[str, Any]]) -> pd.DataFrame:
    if not data:
        return pd.DataFrame(columns=["payment_id", "claim_id", "payer", "allowed_amount", "paid_amount", "adjustment_amount", "patient_responsibility", "payment_date", "status"])
    dataframe = pd.DataFrame(data)
    return dataframe[["payment_id", "claim_id", "payer", "allowed_amount", "paid_amount", "adjustment_amount", "patient_responsibility", "payment_date", "status"]]


def ar_table(data: list[dict[str, Any]]) -> pd.DataFrame:
    if not data:
        return pd.DataFrame(columns=["claim_id", "outstanding_balance", "ar_age_days", "aging_bucket", "ar_status", "recommended_work_type"])
    dataframe = pd.DataFrame(data)
    return dataframe[["claim_id", "outstanding_balance", "ar_age_days", "aging_bucket", "ar_status", "recommended_work_type"]]


def format_currency(value: Decimal | float | int | str | None) -> str:
    if value is None:
        return "N/A"
    return f"${float(value):,.2f}"
