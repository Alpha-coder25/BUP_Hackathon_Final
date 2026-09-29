"""Single entry point for every call to the BUP Fuel Supply Simulator.

Contract: `DOCS/TRD.md` §3, `DOCS/BackendImplementation.md` §2, simulator guide §4–6.

Rules encoded here (nothing else in the codebase may talk to the simulator):
- REST is the source of truth; SSE events are advisory hints only.
- Every write carries an idempotency key `{recommendation_id}:{item_seq}`.
- Retries with exponential backoff (1s/2s/4s), then last-good cache + is_stale.
- `X-Simulator-Stale: true` invalidates the cache for that path.
- Bad payloads raise `SimulatorDataError` (callers turn that into a system alert),
  never a crash.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import httpx

SIM_URL = os.getenv("SIM_URL", "http://localhost:8000")
TIMEOUT_SECONDS = float(os.getenv("SIM_TIMEOUT_SECONDS", "5"))
RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0  # 1s, 2s, 4s

# SSE is advisory; anything else triggers a re-GET of the affected resource.
SSE_EVENTS_TO_PATHS: dict[str, str] = {
    "simulation.tick": "/v1/instance",
    "inventory.updated": "/v1/depots",  # caller may also need /v1/stations
    "allocation.status_changed": "/v1/allocations",
    "simulator.notice": "/v1/events",
}

FUEL_TYPES = ("DIESEL", "PETROL", "OCTANE")


class SimulatorDataError(Exception):
    """Simulator responded with structurally invalid data (bad/negative fields)."""


class SimulatorAllocationError(Exception):
    """Simulator rejected an allocation write; carries the machine-readable code."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code  # e.g. ROUTE_CAPACITY_EXCEEDED, INSUFFICIENT_INVENTORY
        self.message = message


@dataclass
class CacheEntry:
    data: Any
    fetched_at: float


@dataclass
class SimulatorClient:
    """Thread-safe client. One instance per process; inject `base_url` in tests."""

    base_url: str = SIM_URL
    transport: httpx.BaseTransport | None = None  # inject MockTransport in tests
    _cache: dict[str, CacheEntry] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------------------------------------------------------------- reads

    def fetch(self, path: str, retries: int = RETRIES) -> tuple[Any, bool]:
        """GET a /v1/* path. Returns `(data, is_stale)`.

        On success: cache updated, `is_stale=False`.
        On exhaustion: last-good cache with `is_stale=True` (data may be None).
        """
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                return self._fetch_once(path)
            except (httpx.HTTPError, SimulatorDataError) as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))
        entry = self._cache.get(path)
        if entry is not None:
            return entry.data, True
        raise last_error  # type: ignore[misc] — nothing cached and all retries failed

    def _fetch_once(self, path: str) -> tuple[Any, bool]:
        with httpx.Client(base_url=self.base_url, timeout=TIMEOUT_SECONDS, transport=self.transport) as client:
            response = client.get(path)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{response.status_code} on {path}", request=response.request, response=response
            )
        stale_header = response.headers.get("X-Simulator-Stale")
        data = response.json()
        self._validate(path, data)
        if stale_header == "true":
            # Stale-data fault is active: serve this response once but mark stale
            # and do not poison the last-good cache with it.
            return data, True
        with self._lock:
            self._cache[path] = CacheEntry(data=data, fetched_at=time.monotonic())
        return data, False

    # Typed accessors (all route through `fetch`; none hold business logic)
    def health(self) -> tuple[dict, bool]:
        return self.fetch("/v1/health")  # bypasses faults — liveness probe

    def instance(self) -> tuple[dict, bool]:
        return self.fetch("/v1/instance")

    def regions(self) -> tuple[list, bool]:
        return self.fetch("/v1/regions")

    def depots(self) -> tuple[list, bool]:
        return self.fetch("/v1/depots")

    def stations(self) -> tuple[list, bool]:
        return self.fetch("/v1/stations")

    def routes(self) -> tuple[list, bool]:
        return self.fetch("/v1/routes")

    def supply_arrivals(self) -> tuple[list, bool]:
        return self.fetch("/v1/supply-arrivals")

    def events(self) -> tuple[list, bool]:
        return self.fetch("/v1/events")

    def allocations(self) -> tuple[list, bool]:
        return self.fetch("/v1/allocations")

    def metrics(self) -> tuple[dict, bool]:
        return self.fetch("/v1/metrics")

    def demand_history(self, station_id: str, limit: int = 200) -> tuple[list, bool]:
        if not 1 <= limit <= 2000:
            raise ValueError("limit must be within [1, 2000]")
        return self.fetch(f"/v1/demand-history?station_id={station_id}&limit={limit}")

    # --------------------------------------------------------------- writes

    def make_idempotency_key(self, recommendation_id: str, item_seq: int) -> str:
        """Unique per logical request; never reused across different requests."""
        return f"{recommendation_id}:{item_seq}"

    def create_allocation(
        self,
        *,
        idempotency_key: str,
        source_depot_id: str,
        destination_station_id: str,
        route_id: str,
        fuel_type: str,
        quantity: float,
    ) -> dict:
        """POST /v1/allocations. 201 new, 200 replay.

        Raises `SimulatorAllocationError` on 404/409 with the simulator's `code`,
        `httpx.HTTPError` on 503/faults (caller retries with backoff).
        """
        self._validate_allocation_payload(
            source_depot_id, destination_station_id, route_id, fuel_type, quantity
        )
        body = {
            "idempotency_key": idempotency_key,
            "source_depot_id": source_depot_id,
            "destination_station_id": destination_station_id,
            "route_id": route_id,
            "fuel_type": fuel_type,
            "quantity": quantity,
        }
        with httpx.Client(base_url=self.base_url, timeout=TIMEOUT_SECONDS, transport=self.transport) as client:
            response = client.post("/v1/allocations", json=body)
        if response.status_code in (200, 201):
            return response.json()
        detail = response.json().get("detail", {})
        code = detail.get("code", "UNKNOWN") if isinstance(detail, dict) else "VALIDATION"
        message = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
        raise SimulatorAllocationError(response.status_code, code, message)

    def cancel_allocation(self, allocation_id: int) -> dict:
        """Cancel a PENDING allocation (refunds depot inventory). 409 otherwise."""
        with httpx.Client(base_url=self.base_url, timeout=TIMEOUT_SECONDS, transport=self.transport) as client:
            response = client.post(f"/v1/allocations/{allocation_id}/cancel")
        if response.status_code == 200:
            return response.json()
        detail = response.json().get("detail", {})
        code = detail.get("code", "UNKNOWN") if isinstance(detail, dict) else "UNKNOWN"
        raise SimulatorAllocationError(response.status_code, code, str(detail))

    # ------------------------------------------------------------------ SSE

    def stream(self, on_event: Callable[[str, dict], None]) -> Iterator[None]:
        """Subscribe to /v1/stream. Advisory only: emits (event, payload) to
        `on_event`; callers re-GET the affected REST resource.

        - No Last-Event-ID replay: after every (re)connect the caller must
          re-fetch full state — we invoke on_event("__reconnected__", {}).
        - Reconnects with backoff on errors (503 stream_disconnect fault, drops).
        """
        backoff = BACKOFF_BASE_SECONDS
        while True:
            try:
                with httpx.Client(
                    base_url=self.base_url, timeout=httpx.Timeout(30.0), transport=self.transport
                ) as client:
                    with client.stream("GET", "/v1/stream") as response:
                        response.raise_for_status()
                        event_name: str | None = None
                        for line in response.iter_lines():
                            if line.startswith(":"):  # connected / keepalive comment
                                continue
                            if line.startswith("event:"):
                                event_name = line.split(":", 1)[1].strip()
                            elif line.startswith("data:") and event_name:
                                import json

                                payload = json.loads(line.split(":", 1)[1].strip())
                                on_event(event_name, payload)
                                event_name = None
                backoff = BACKOFF_BASE_SECONDS
            except httpx.HTTPError:
                on_event("__reconnected__", {})  # signal: re-GET everything
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            yield None

    # ------------------------------------------------------------ validation

    def _validate(self, path: str, data: Any) -> None:
        """Reject structurally bad data (missing fields, negative numbers).
        SimulatorDataError is converted to a system alert by the collector."""
        checks: dict[str, list[tuple[str, type]]] = {
            "/v1/instance": [("tick", int), ("status", str)],
            "/v1/depots": [("id", str), ("status", str), ("inventory", dict)],
            "/v1/stations": [("id", str), ("status", str), ("inventory", dict)],
            "/v1/routes": [("id", str), ("status", str), ("max_shipment", (int, float))],
            "/v1/allocations": [("idempotency_key", str), ("status", str)],
        }
        for prefix, required in checks.items():
            if path.startswith(prefix):
                rows = data if isinstance(data, list) else [data]
                for row in rows:
                    for key, expected in required:
                        if key not in row:
                            raise SimulatorDataError(f"{path}: missing field {key!r} in {row!r}")
                        if not isinstance(row[key], expected):
                            raise SimulatorDataError(
                                f"{path}: field {key!r} has wrong type {type(row[key]).__name__}"
                            )
                self._validate_no_negative_inventory(data, prefix)
                return

    @staticmethod
    def _validate_no_negative_inventory(data: Any, prefix: str) -> None:
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            inventory = row.get("inventory") if isinstance(row, dict) else None
            if isinstance(inventory, dict):
                for fuel, level in inventory.items():
                    if isinstance(level, (int, float)) and level < 0:
                        raise SimulatorDataError(
                            f"{prefix}: negative inventory {fuel}={level} for {row.get('id')}"
                        )

    @staticmethod
    def _validate_allocation_payload(
        source_depot_id: str,
        destination_station_id: str,
        route_id: str,
        fuel_type: str,
        quantity: float,
    ) -> None:
        if not source_depot_id or not destination_station_id or not route_id:
            raise ValueError("depot/station/route ids are required")
        if fuel_type not in FUEL_TYPES:
            raise ValueError(f"fuel_type must be one of {FUEL_TYPES}")
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            raise ValueError("quantity must be > 0")


def fetch(path: str) -> tuple[Any, bool]:
    """Convenience module-level client for Phase 1 scripts and tests."""
    return get_client().fetch(path)


_client: SimulatorClient | None = None


def get_client() -> SimulatorClient:
    global _client
    if _client is None:
        _client = SimulatorClient()
    return _client
