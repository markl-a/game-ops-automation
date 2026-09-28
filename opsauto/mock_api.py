"""A small stand-in for the game's wallet API, so the contract tests in tests/api/ have something to run against.
Point the same tests at a real environment with API_BASE_URL=https://staging.example (see tests/api/conftest.py).
"""
from __future__ import annotations

from threading import Lock

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="wallet-api (mock)")
_wallets: dict[str, int] = {"u000123": 500}
_topups: dict[str, dict] = {}
_lock = Lock()
CATALOG = {"pts_100": 100, "pts_350": 350, "pts_1200": 1200}


class TopupIn(BaseModel):
    user_id: str = Field(pattern=r"^u\d{6}$")
    sku: str
    order_id: str = Field(min_length=8, max_length=40)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/users/{user_id}/wallet")
def wallet(user_id: str):
    if user_id not in _wallets:
        raise HTTPException(404, "user not found")
    return {"user_id": user_id, "points": _wallets[user_id]}


@app.post("/v1/topups", status_code=201)
def topup(body: TopupIn, idempotency_key: str = Header(min_length=8)):
    with _lock:
        if idempotency_key in _topups:
            prev = _topups[idempotency_key]
            if prev["order_id"] != body.order_id:
                raise HTTPException(409, "idempotency key reused with a different order")
            return prev
        if body.sku not in CATALOG:
            raise HTTPException(422, f"unknown sku {body.sku}")
        if any(t["order_id"] == body.order_id for t in _topups.values()):
            raise HTTPException(409, "order already granted")
        _wallets[body.user_id] = _wallets.get(body.user_id, 0) + CATALOG[body.sku]
        rec = {"order_id": body.order_id, "user_id": body.user_id, "points": CATALOG[body.sku], "balance": _wallets[body.user_id]}
        _topups[idempotency_key] = rec
        return rec
