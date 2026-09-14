"""FDA/openFDA adapter for auditable regulatory catalyst evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote_plus

from boe.ingestion.http import FetchedPayload, PublicDataClient

OPENFDA_DRUGSFDA = "https://api.fda.gov/drug/drugsfda.json"


@dataclass(frozen=True, slots=True)
class FDAApplicationAction:
    application_number: str
    sponsor_name: str | None
    product_name: str | None
    active_ingredients: tuple[str, ...]
    action_date: date | None
    action_type: str | None
    submission: str | None
    submission_status: str | None


class FDAAdapter:
    def __init__(self, client: PublicDataClient) -> None:
        self._client = client

    @staticmethod
    def application_url(application_number: str, limit: int = 20) -> str:
        value = application_number.strip().upper()
        if not value:
            raise ValueError("application_number is required")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be within 1..100")
        encoded = quote_plus(f'application_number:"{value}"')
        return f"{OPENFDA_DRUGSFDA}?search={encoded}&limit={limit}"

    def fetch_application(
        self, application_number: str
    ) -> tuple[FetchedPayload, tuple[FDAApplicationAction, ...]]:
        payload = self._client.fetch(self.application_url(application_number))
        return payload, self.parse_drugsfda(payload.content)

    @classmethod
    def parse_drugsfda(cls, content: bytes | str) -> tuple[FDAApplicationAction, ...]:
        raw = json.loads(content)
        if not isinstance(raw, dict):
            raise ValueError("openFDA response must be an object")
        results = raw.get("results")
        if not isinstance(results, list):
            return ()
        actions: list[FDAApplicationAction] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            application_number = str(result.get("application_number", "")).strip().upper()
            if not application_number:
                continue
            sponsor = cls._optional_text(result.get("sponsor_name"))
            products = result.get("products")
            product_name: str | None = None
            ingredients: list[str] = []
            if isinstance(products, list) and products:
                first = products[0] if isinstance(products[0], dict) else {}
                product_name = cls._optional_text(first.get("brand_name"))
                active = first.get("active_ingredients")
                if isinstance(active, list):
                    for item in active:
                        if isinstance(item, dict):
                            name = str(item.get("name", "")).strip()
                            if name:
                                ingredients.append(name)
            submissions = result.get("submissions")
            if not isinstance(submissions, list):
                submissions = []
            if not submissions:
                actions.append(
                    FDAApplicationAction(
                        application_number=application_number,
                        sponsor_name=sponsor,
                        product_name=product_name,
                        active_ingredients=tuple(dict.fromkeys(ingredients)),
                        action_date=None,
                        action_type=None,
                        submission=None,
                        submission_status=None,
                    )
                )
                continue
            for submission_raw in submissions:
                if not isinstance(submission_raw, dict):
                    continue
                actions.append(
                    FDAApplicationAction(
                        application_number=application_number,
                        sponsor_name=sponsor,
                        product_name=product_name,
                        active_ingredients=tuple(dict.fromkeys(ingredients)),
                        action_date=cls._parse_fda_date(
                            submission_raw.get("submission_status_date")
                        ),
                        action_type=cls._optional_text(submission_raw.get("submission_type")),
                        submission=cls._optional_text(submission_raw.get("submission_number")),
                        submission_status=cls._optional_text(
                            submission_raw.get("submission_status")
                        ),
                    )
                )
        return tuple(actions)

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _parse_fda_date(value: object) -> date | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if len(text) == 8 and text.isdigit():
            try:
                return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
            except ValueError:
                return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
