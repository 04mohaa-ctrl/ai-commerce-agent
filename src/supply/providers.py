"""Provider-independent read-only supplier contracts."""

from typing import Protocol, runtime_checkable

from src.supply.models import (
    ActionTelemetry,
    Destination,
    ProviderOutcome,
    StockObservation,
    SupplierVariant,
)


@runtime_checkable
class SupplierProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    @property
    def telemetry(self) -> ActionTelemetry: ...

    @property
    def cache_context(self) -> str: ...

    def reset_action(
        self, telemetry: ActionTelemetry, *, max_requests: int = 12, max_seconds: float = 90
    ) -> None: ...

    def search(self, query: str, *, page: int = 1, size: int = 10) -> ProviderOutcome: ...

    def details(self, pid: str) -> ProviderOutcome: ...

    def variants(self, pid: str) -> ProviderOutcome: ...

    def stock(self, vid: str, *, product_id: str | None = None) -> ProviderOutcome: ...

    def shipping(
        self, variant: SupplierVariant, stock: StockObservation, destination: Destination
    ) -> ProviderOutcome: ...


GenericSupplierProvider = SupplierProvider


class UnavailableSupplierProvider:
    """Keyless/demo fallback has no HTTP client and cannot issue any requests."""

    name = "cj"
    configured = False
    cache_context = "unavailable"

    def __init__(self):
        self.telemetry = ActionTelemetry()

    def reset_action(
        self, telemetry: ActionTelemetry, *, max_requests: int = 12, max_seconds: float = 90
    ) -> None:
        self.telemetry = telemetry

    def _unavailable(self) -> ProviderOutcome:
        return ProviderOutcome(status="UNAVAILABLE", notice="Supplier research is unavailable.")

    def search(self, query: str, *, page: int = 1, size: int = 10) -> ProviderOutcome:
        return self._unavailable()

    def details(self, pid: str) -> ProviderOutcome:
        return self._unavailable()

    def variants(self, pid: str) -> ProviderOutcome:
        return self._unavailable()

    def stock(self, vid: str, *, product_id: str | None = None) -> ProviderOutcome:
        return self._unavailable()

    def shipping(
        self, variant: SupplierVariant, stock: StockObservation, destination: Destination
    ) -> ProviderOutcome:
        return self._unavailable()
