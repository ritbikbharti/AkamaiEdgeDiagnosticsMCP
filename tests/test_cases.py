from __future__ import annotations

import json

import httpx
import pytest

from akamai_edge_mcp import models as M
from akamai_edge_mcp.tools import cases


async def test_list_cases_uses_case_management_prefix(make_client):
    """Path must hit /case-management/v3/..., NOT /edge-diagnostics/v1/...."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"cases": []})

    client = make_client(handler)
    try:
        await cases.list_cases(
            client, M.ListCasesInput(type="MY_ACTIVE_CASES", limit=50)
        )
    finally:
        await client.aclose()

    assert seen["path"] == "/case-management/v3/cases"
    assert "/edge-diagnostics/" not in seen["path"]
    assert seen["params"]["type"] == "MY_ACTIVE_CASES"
    assert seen["params"]["limit"] == "50"


async def test_get_case_path(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(200, json={"caseId": "00123456"})

    client = make_client(handler)
    try:
        await cases.get_case(client, M.GetCaseInput(case_id="00123456"))
    finally:
        await client.aclose()

    assert seen["method"] == "GET"
    assert seen["path"] == "/case-management/v3/cases/00123456"


async def test_create_case_camel_cases_field_names(make_client):
    """Pydantic snake_case must be converted to Akamai's camelCase JSON keys."""
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        posted["body"] = json.loads(request.content)
        posted["path"] = request.url.path
        return httpx.Response(201, json={"caseId": "00789"})

    client = make_client(handler)
    try:
        await cases.create_case(
            client,
            M.CreateCaseInput(
                subject="Edge returning 502 for /api/foo",
                description="Started 30 minutes ago, all regions",
                account_id="ACC-12345",
                category_id="TECHNICAL",
                severity="2-Significant",
                product_name="Ion",
                problem_name="Origin connectivity",
                also_notify=["sre@example.com"],
                customer_tracking_number="INC-99999",
                alternate_contact=M.AlternateContact(
                    name="Jane Ops", email="jane@example.com"
                ),
            ),
        )
    finally:
        await client.aclose()

    body = posted["body"]
    assert posted["path"] == "/case-management/v3/cases"
    # Required fields, all camelCased
    assert body["subject"] == "Edge returning 502 for /api/foo"
    assert body["accountId"] == "ACC-12345"
    assert body["categoryId"] == "TECHNICAL"
    assert body["productName"] == "Ion"
    assert body["problemName"] == "Origin connectivity"
    assert body["customerTrackingNumber"] == "INC-99999"
    assert body["alsoNotify"] == ["sre@example.com"]
    assert body["alternateContact"] == {"name": "Jane Ops", "email": "jane@example.com"}
    # Snake-case must NOT leak through
    assert "account_id" not in body
    assert "category_id" not in body
    assert "alternate_contact" not in body
    assert "customer_tracking_number" not in body


async def test_create_case_omits_unset_optional_fields(make_client):
    """Unset optional fields must NOT show up in the body as None."""
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        posted["body"] = json.loads(request.content)
        return httpx.Response(201, json={"caseId": "X"})

    client = make_client(handler)
    try:
        await cases.create_case(
            client,
            M.CreateCaseInput(
                subject="Test",
                description="Test",
                account_id="A",
                category_id="TECHNICAL",
            ),
        )
    finally:
        await client.aclose()

    body = posted["body"]
    assert set(body.keys()) == {"subject", "description", "accountId", "categoryId"}


async def test_update_case_uses_patch(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await cases.update_case(
            client,
            M.UpdateCaseInput(
                case_id="00789", also_notify=["new@example.com"]
            ),
        )
    finally:
        await client.aclose()

    assert seen["method"] == "PATCH"
    assert seen["path"] == "/case-management/v3/cases/00789"
    assert seen["body"] == {"alsoNotify": ["new@example.com"]}


async def test_update_case_requires_at_least_one_field(make_client):
    client = make_client(lambda r: httpx.Response(200, json={}))
    try:
        with pytest.raises(ValueError, match="at least one"):
            await cases.update_case(client, M.UpdateCaseInput(case_id="X"))
    finally:
        await client.aclose()


async def test_add_case_comment(make_client):
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        posted["path"] = request.url.path
        posted["body"] = json.loads(request.content)
        return httpx.Response(201, json={"commentId": "c1"})

    client = make_client(handler)
    try:
        await cases.add_case_comment(
            client,
            M.AddCaseCommentInput(case_id="00789", comment="Reproduced again at 14:05 UTC"),
        )
    finally:
        await client.aclose()

    assert posted["path"] == "/case-management/v3/cases/00789/comments"
    assert posted["body"] == {"comment": "Reproduced again at 14:05 UTC"}


async def test_list_case_comments_uses_get(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"comments": []})

    client = make_client(handler)
    try:
        await cases.list_case_comments(
            client, M.ListCaseCommentsInput(case_id="00789")
        )
    finally:
        await client.aclose()

    assert seen["method"] == "GET"
    assert seen["path"] == "/case-management/v3/cases/00789/comments"


async def test_request_case_closure_with_comment(make_client):
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        posted["path"] = request.url.path
        posted["body"] = json.loads(request.content)
        return httpx.Response(202, json={"status": "PENDING"})

    client = make_client(handler)
    try:
        await cases.request_case_closure(
            client,
            M.RequestCaseClosureInput(case_id="00789", comment="Resolved by config rollback"),
        )
    finally:
        await client.aclose()

    assert posted["path"] == "/case-management/v3/cases/00789/request-case-closure"
    assert posted["body"] == {"comment": "Resolved by config rollback"}


async def test_get_case_category_path(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"severities": []})

    client = make_client(handler)
    try:
        await cases.get_case_category(
            client, M.GetCaseCategoryInput(category_id="TECHNICAL")
        )
    finally:
        await client.aclose()

    assert seen["path"] == "/case-management/v3/categories/TECHNICAL"


async def test_list_account_categories_path(make_client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"accounts": []})

    client = make_client(handler)
    try:
        await cases.list_account_categories(
            client, M.ListAccountCategoriesInput()
        )
    finally:
        await client.aclose()

    assert seen["path"] == "/case-management/v3/accounts-with-categories"
