import uuid

import pytest
from pydantic import ValidationError

from app.api.routers.sessions import CreateSessionRequest


def _request(**updates):
    values = {
        "dataset_ids": [uuid.uuid4()],
        "rough_prompt": "Why did net revenue decline?",
        "analysis_objectives": ["root_cause"],
    }
    values.update(updates)
    return CreateSessionRequest(**values)


def test_revenue_policy_normalizes_currency_and_accepts_iana_timezone():
    request = _request(
        revenue_reporting_currency="eur",
        revenue_timezone="Europe/Berlin",
    )

    assert request.revenue_reporting_currency == "EUR"
    assert request.revenue_timezone == "Europe/Berlin"


@pytest.mark.parametrize(
    ("field", "value"),
    (("revenue_reporting_currency", "EURO"), ("revenue_timezone", "Berlin")),
)
def test_invalid_revenue_policy_fails_at_api_boundary(field, value):
    with pytest.raises(ValidationError):
        _request(**{field: value})
