"""Akamai Case Management tools.

Designed for the diagnose→file workflow: an LLM client uses the Edge
Diagnostics tools (translate_error_string, run_curl, etc.) to identify a
problem, then opens a support case with the findings via the tools here.

All paths are passed in fully-qualified form (``/case-management/v3/...``)
so the underlying client routes them to the right Akamai API surface
without prepending the Edge Diagnostics prefix.

PATCH and PUT semantics: Akamai's case-management API uses PATCH for
partial updates. The client doesn't have a top-level ``patch()`` helper
yet, so we use ``request("PATCH", ...)`` directly.
"""

from __future__ import annotations

from typing import Any

from ..client import AkamaiEdgeDiagnosticsClient
from ..models import (
    AddCaseCommentInput,
    CreateCaseInput,
    GetCaseCategoryInput,
    GetCaseInput,
    ListAccountCategoriesInput,
    ListCaseCommentsInput,
    ListCasesInput,
    RequestCaseClosureInput,
    UpdateCaseInput,
)

_PREFIX = "/case-management/v3"


def _to_camel(name: str) -> str:
    """snake_case → camelCase, used to convert Pydantic field names to
    the JSON keys Akamai expects in request bodies."""
    head, *tail = name.split("_")
    return head + "".join(part.title() for part in tail)


def _serialize(model_dump: dict[str, Any]) -> dict[str, Any]:
    """Drop None values and camelCase the keys."""
    return {_to_camel(k): v for k, v in model_dump.items() if v is not None}


# ---------- discovery ----------


async def list_account_categories(
    client: AkamaiEdgeDiagnosticsClient, params: ListAccountCategoriesInput
) -> dict[str, Any]:
    """List accounts you can open cases for, with the categories each supports.

    Call this FIRST when starting a new case-creation flow — it gives you
    the valid ``account_id`` and ``category_id`` values to pass to
    ``create_case``.
    """
    return await client.get(f"{_PREFIX}/accounts-with-categories")


async def get_case_category(
    client: AkamaiEdgeDiagnosticsClient, params: GetCaseCategoryInput
) -> dict[str, Any]:
    """Get the schema for a specific case category.

    Returns the valid severity values plus which of productName /
    serviceName / problemName / areaName / policyDomainName / etc. are
    required and what values they accept for this category. Call this
    BEFORE ``create_case`` for any non-trivial case.
    """
    return await client.get(f"{_PREFIX}/categories/{params.category_id}")


# ---------- list / read ----------


async def list_cases(
    client: AkamaiEdgeDiagnosticsClient, params: ListCasesInput
) -> dict[str, Any]:
    """List cases on the account.

    ``type`` is required — pick from MY_ACTIVE_CASES, MY_CLOSED_CASES,
    ALL_ACTIVE_CASES, ALL_CLOSED_CASES. Use cursor for pagination.
    """
    query: dict[str, Any] = {"type": params.type}
    if params.duration is not None:
        query["duration"] = params.duration
    if params.account_ids:
        query["accountIds"] = params.account_ids
    if params.limit is not None:
        query["limit"] = params.limit
    if params.cursor:
        query["cursor"] = params.cursor
    return await client.get(f"{_PREFIX}/cases", params=query)


async def get_case(
    client: AkamaiEdgeDiagnosticsClient, params: GetCaseInput
) -> dict[str, Any]:
    """Fetch a single case by ID, including its current status and metadata."""
    return await client.get(f"{_PREFIX}/cases/{params.case_id}")


# ---------- create / update / close ----------


async def create_case(
    client: AkamaiEdgeDiagnosticsClient, params: CreateCaseInput
) -> dict[str, Any]:
    """Open a new Akamai support case.

    Required: ``subject``, ``description``, ``account_id``, ``category_id``.
    Many additional fields (severity, productName, serviceName, ...) are
    REQUIRED depending on the chosen category — call ``get_case_category``
    first to discover which apply, then pass them here. Akamai will
    return an HTTP 400 with field-level detail if anything is missing or
    invalid.
    """
    body = params.model_dump(exclude_none=True)
    # Hoist alternate_contact into a nested object with camelCase keys.
    if body.get("alternate_contact"):
        body["alternate_contact"] = _serialize(body["alternate_contact"])
    body = _serialize(body)
    return await client.post(f"{_PREFIX}/cases", json=body)


async def update_case(
    client: AkamaiEdgeDiagnosticsClient, params: UpdateCaseInput
) -> dict[str, Any]:
    """Update a case's contact details.

    Akamai's PATCH currently only supports ``alsoNotify`` and
    ``alternateContact``; subject / description / category are immutable
    after creation. Use ``add_case_comment`` to add new info.
    """
    body: dict[str, Any] = {}
    if params.also_notify is not None:
        body["alsoNotify"] = params.also_notify
    if params.alternate_contact is not None:
        body["alternateContact"] = _serialize(
            params.alternate_contact.model_dump(exclude_none=True)
        )
    if not body:
        raise ValueError(
            "update_case requires at least one of also_notify or alternate_contact."
        )
    return await client.request(
        "PATCH", f"{_PREFIX}/cases/{params.case_id}", json=body
    )


async def request_case_closure(
    client: AkamaiEdgeDiagnosticsClient, params: RequestCaseClosureInput
) -> dict[str, Any]:
    """Request closure of an open case.

    Akamai may auto-close immediately or route the request to a CSM for
    review depending on case type and history. Optional ``comment`` adds
    a closure note (resolution summary, root cause, etc.).
    """
    body: dict[str, Any] = {}
    if params.comment:
        body["comment"] = params.comment
    return await client.post(
        f"{_PREFIX}/cases/{params.case_id}/request-case-closure", json=body
    )


# ---------- comments ----------


async def list_case_comments(
    client: AkamaiEdgeDiagnosticsClient, params: ListCaseCommentsInput
) -> dict[str, Any]:
    """List all comments on a case in chronological order."""
    return await client.get(f"{_PREFIX}/cases/{params.case_id}/comments")


async def add_case_comment(
    client: AkamaiEdgeDiagnosticsClient, params: AddCaseCommentInput
) -> dict[str, Any]:
    """Add a comment to an existing case.

    Useful for attaching follow-up diagnostic findings without opening a
    new case (e.g. results of a translate_error_string after the original
    submission).
    """
    return await client.post(
        f"{_PREFIX}/cases/{params.case_id}/comments",
        json={"comment": params.comment},
    )
