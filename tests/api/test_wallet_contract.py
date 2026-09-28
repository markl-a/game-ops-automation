"""Contract tests for the wallet API. Every case here maps to a real failure mode from the reconciliation report:
double grants (idempotency), wrong points (catalog), and grants for bad input."""
import pytest

USER = "u000123"


def balance(api):
    r = api.get(f"/v1/users/{USER}/wallet")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"user_id", "points"} and isinstance(body["points"], int)
    return body["points"]


def test_health(api):
    assert api.get("/health").json() == {"status": "ok"}


def test_topup_grants_catalog_points(api, key, order):
    before = balance(api)
    r = api.post("/v1/topups", json={"user_id": USER, "sku": "pts_350", "order_id": order}, headers={"Idempotency-Key": key})
    assert r.status_code == 201 and r.json()["points"] == 350
    assert balance(api) == before + 350


def test_retry_with_same_key_does_not_double_grant(api, key, order):
    body = {"user_id": USER, "sku": "pts_100", "order_id": order}
    first = api.post("/v1/topups", json=body, headers={"Idempotency-Key": key})
    after_first = balance(api)
    again = api.post("/v1/topups", json=body, headers={"Idempotency-Key": key})
    assert again.json() == first.json()
    assert balance(api) == after_first


def test_same_order_with_new_key_is_rejected(api, key, order):
    body = {"user_id": USER, "sku": "pts_100", "order_id": order}
    api.post("/v1/topups", json=body, headers={"Idempotency-Key": key})
    r = api.post("/v1/topups", json=body, headers={"Idempotency-Key": key + "-other"})
    assert r.status_code == 409


def test_key_reused_for_different_order_is_rejected(api, key, order):
    api.post("/v1/topups", json={"user_id": USER, "sku": "pts_100", "order_id": order}, headers={"Idempotency-Key": key})
    r = api.post("/v1/topups", json={"user_id": USER, "sku": "pts_100", "order_id": order + "x"}, headers={"Idempotency-Key": key})
    assert r.status_code == 409


@pytest.mark.parametrize("body,headers,status", [
    ({"user_id": USER, "sku": "pts_999", "order_id": "TEST-unknown-sku"}, {"Idempotency-Key": "k-unknown-sku"}, 422),
    ({"user_id": "bob", "sku": "pts_100", "order_id": "TEST-bad-user"}, {"Idempotency-Key": "k-bad-user-1"}, 422),
    ({"user_id": USER, "sku": "pts_100", "order_id": "TEST-no-key"}, {}, 422),
])
def test_bad_input_grants_nothing(api, body, headers, status):
    before = balance(api)
    assert api.post("/v1/topups", json=body, headers=headers).status_code == status
    assert balance(api) == before


def test_unknown_user_is_404(api):
    assert api.get("/v1/users/u999999/wallet").status_code == 404
