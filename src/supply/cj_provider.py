"""Sanitized CJ catalog/inventory/freight observations, without commerce actions."""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.supply.cj_transport import CJResearchTransport, CJTransportOutcome
from src.supply.models import (
    ActionTelemetry,
    Destination,
    ProviderOutcome,
    ShippingQuote,
    StockObservation,
    SupplierProductCandidate,
    SupplierVariant,
)


def _link(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return SupplierProductCandidate.safe_link(value)
    except (ValueError, TypeError):
        return None


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip() and len(value) <= 300:
        return value.strip()
    return None


def _warehouse(value: Any) -> str | None:
    if type(value) is int and value >= 0:
        return str(value)
    return _optional_text(value)


def _delivery(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, str):
        return None, None
    parsed = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", value)
    if not parsed:
        return None, None
    minimum = int(parsed[1])
    maximum = int(parsed[2] or parsed[1])
    return (minimum, maximum) if minimum <= maximum else (None, None)


class CJDropShippingProvider:
    name = "cj"

    def __init__(self, *, transport: CJResearchTransport | None = None):
        self._transport = transport or CJResearchTransport()
        self._variant_products: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return self._transport.configured

    @property
    def cache_context(self) -> str:
        return self._transport.cache_context

    @property
    def telemetry(self) -> ActionTelemetry:
        return self._transport.telemetry

    def reset_action(
        self, telemetry: ActionTelemetry, *, max_requests: int = 12, max_seconds: float = 90
    ) -> None:
        self._transport.reset_action(telemetry, max_requests=max_requests, max_seconds=max_seconds)

    def _unsupported(self, notice: str) -> ProviderOutcome:
        return ProviderOutcome(status="UNSUPPORTED", notice=notice)

    def _unavailable(self) -> ProviderOutcome:
        return ProviderOutcome(
            status="UNAVAILABLE", notice="CJ supplier research is not configured."
        )

    def _failure(self, result: CJTransportOutcome) -> ProviderOutcome | None:
        if result.status != "SUCCESS":
            return ProviderOutcome(
                status=result.status,
                notice=result.notice,
                observed_at=result.observed_at,
                limit_source=result.limit_source,
                retry_blocked_by=result.retry_blocked_by,
            )
        return None

    def _parse(
        self,
        rows: Any,
        result: CJTransportOutcome,
        builder: Callable,
        *,
        rejected: int = 0,
        identity: Callable | None = None,
    ) -> ProviderOutcome:
        if not isinstance(rows, list):
            rows, rejected = [], rejected + 1
        records, seen = [], {}
        for row in rows:
            try:
                if not isinstance(row, dict):
                    raise ValueError("Malformed record")
                record = builder(row).model_dump(mode="json")
                key = identity(record) if identity else record["id"]
                if key in seen:
                    if record != seen[key]:
                        rejected += 1
                    continue
                seen[key] = record
                records.append(record)
            except (ValueError, TypeError, KeyError, AttributeError):
                rejected += 1
        if records:
            status = "SUCCESS"
        elif rejected:
            status = "FAILED"
        else:
            status = "SUCCESS_EMPTY"
        return ProviderOutcome(
            status=status,
            records=records,
            partial=bool(records and rejected),
            rejected=rejected,
            observed_at=result.observed_at,
            notice="Some CJ records could not be validated." if rejected else "",
        )

    def search(self, query: str, *, page: int = 1, size: int = 10) -> ProviderOutcome:
        result = self._transport.request("search", {"keyWord": query, "page": page, "size": size})
        failure = self._failure(result)
        if failure is not None:
            return failure
        rows, rejected = [], 0
        groups = result.data.get("content") if isinstance(result.data, dict) else None
        if not isinstance(groups, list):
            rejected += 1
        else:
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("productList"), list):
                    rejected += 1
                else:
                    rows.extend(group["productList"])
        return self._parse(
            rows,
            result,
            lambda row: self._candidate(row, result.observed_at),
            rejected=rejected,
            identity=lambda row: row["product_id"],
        )

    def discover(self, search) -> ProviderOutcome:
        from src.discovery.models import CatalogItem, DiscoverySearch, catalog_price

        search = DiscoverySearch.model_validate(search.model_dump())
        result = self._transport.request("search", search.parameters())
        failure = self._failure(result)
        if failure is not None:
            return failure
        groups = result.data.get("content") if isinstance(result.data, dict) else None
        rows, rejected = [], 0
        for group in groups if isinstance(groups, list) else [None]:
            if not isinstance(group, dict) or not isinstance(group.get("productList"), list):
                rejected += 1
            else:
                rows.extend(group["productList"])

        def build(row):
            price = catalog_price(row.get("sellPrice"))
            return CatalogItem(
                candidate=self._candidate(row, result.observed_at),
                catalog_price=price,
                currency="USD" if price is not None else None,
            )

        return self._parse(
            rows,
            result,
            build,
            rejected=rejected,
            identity=lambda row: row["candidate"]["product_id"],
        )

    def _candidate(self, row: dict, observed_at: datetime, *, detail: bool = False):
        return SupplierProductCandidate(
            provider=self.name,
            product_id=row["pid" if detail else "id"],
            name=row["productNameEn" if detail else "nameEn"],
            category=_optional_text(row.get("categoryName" if detail else "threeCategoryName")),
            image_url=_link(row.get("productImage" if detail else "bigImage")),
            observed_at=observed_at,
        )

    def details(self, pid: str) -> ProviderOutcome:
        result = self._transport.request("details", {"pid": pid})
        failure = self._failure(result)
        if failure is not None:
            return failure

        def build(row):
            if row.get("pid") != pid:
                raise ValueError("Wrong product identity")
            return self._candidate(row, result.observed_at, detail=True)

        return self._parse([result.data], result, build)

    def variants(self, pid: str) -> ProviderOutcome:
        result = self._transport.request("variants", {"pid": pid})
        failure = self._failure(result)
        if failure is not None:
            return failure

        def build(row):
            if row.get("pid") != pid:
                raise ValueError("Wrong product identity")
            raw_dimensions = [
                row.get(key) for key in ("variantLength", "variantWidth", "variantHeight")
            ]
            dimensions = (
                tuple(raw_dimensions) if all(v is not None for v in raw_dimensions) else None
            )
            variant_key = _optional_text(row.get("variantKey"))
            return SupplierVariant(
                provider=self.name,
                product_id=pid,
                variant_id=row["vid"],
                name=(row.get("variantNameEn") or row.get("variantName") or variant_key),
                sku=_optional_text(row.get("variantSku")),
                attributes={"variant_key": variant_key} if variant_key else {},
                unit_price=row.get("variantSellPrice"),
                currency="USD",
                weight_g=row.get("variantWeight"),
                dimensions_mm=dimensions,
                observed_at=result.observed_at,
            )

        outcome = self._parse(result.data, result, build, identity=lambda row: row["variant_id"])
        for record in outcome.records:
            self._variant_products[record["variant_id"]] = record["product_id"]
        return outcome

    def stock(self, vid: str, *, product_id: str | None = None) -> ProviderOutcome:
        if not self.configured:
            return self._unavailable()
        pid = product_id or self._variant_products.get(vid)
        if not pid:
            return self._unsupported("Variant product identity is required for stock research.")
        if vid in self._variant_products and self._variant_products[vid] != pid:
            return self._unsupported("Variant and product identities disagree.")
        result = self._transport.request("stock", {"vid": vid})
        failure = self._failure(result)
        if failure is not None:
            return failure
        rows, rejected = [], 0
        if not isinstance(result.data, list):
            rejected += 1
        else:
            for row in result.data:
                if (
                    not isinstance(row, dict)
                    or row.get("vid", vid) != vid
                    or row.get("pid", pid) != pid
                ):
                    rejected += 1
                    continue
                substock = row.get("stock")
                if substock is not None and not isinstance(substock, list):
                    rejected += 1
                    continue
                if substock:
                    for sub in substock:
                        if not isinstance(sub, dict) or not _optional_text(sub.get("stockId")):
                            rejected += 1
                            continue
                        cj, factory = sub.get("inventory"), sub.get("factoryInventory")
                        quantity = (
                            cj + factory if type(cj) is int and type(factory) is int else None
                        )
                        rows.append(
                            {
                                "warehouse": row.get("areaId"),
                                "storage": sub["stockId"],
                                "country": row.get("countryCode"),
                                "quantity": quantity,
                                "cj": cj,
                                "factory": factory,
                            }
                        )
                else:
                    rows.append(
                        {
                            "warehouse": row.get("areaId"),
                            "storage": None,
                            "country": row.get("countryCode"),
                            "quantity": row.get("totalInventoryNum"),
                            "cj": row.get("cjInventoryNum"),
                            "factory": row.get("factoryInventoryNum"),
                        }
                    )

        return self._parse(
            rows,
            result,
            lambda row: StockObservation(
                provider=self.name,
                product_id=pid,
                variant_id=vid,
                warehouse_id=_warehouse(row["warehouse"]),
                storage_id=row["storage"],
                country=row["country"],
                quantity=row["quantity"],
                cj_quantity=row["cj"],
                factory_quantity=row["factory"],
                observed_at=result.observed_at,
            ),
            rejected=rejected,
            identity=lambda row: (row["warehouse_id"], row["storage_id"], row["country"]),
        )

    def shipping(
        self, variant: SupplierVariant, stock: StockObservation, destination: Destination
    ) -> ProviderOutcome:
        if not self.configured:
            return self._unavailable()
        if (
            variant.provider != self.name
            or stock.provider != self.name
            or variant.product_id != stock.product_id
            or variant.variant_id != stock.variant_id
            or not stock.storage_id
            or not stock.country
        ):
            return self._unsupported(
                "Applicable freight requires the exact variant and subwarehouse."
            )
        if destination.postal_code or destination.region:
            return self._unsupported("This freight capability supports country destinations only.")
        result = self._transport.request(
            "shipping",
            {
                "startCountryCode": stock.country,
                "endCountryCode": destination.country,
                "products": [{"quantity": destination.quantity, "vid": variant.variant_id}],
                "storageIdList": [stock.storage_id],
            },
        )
        failure = self._failure(result)
        if failure is not None:
            return failure

        def build(row):
            minimum, maximum = _delivery(row.get("logisticAging"))
            return ShippingQuote(
                provider=self.name,
                product_id=variant.product_id,
                variant_id=variant.variant_id,
                variant_snapshot=variant.id,
                warehouse_id=stock.warehouse_id,
                storage_id=stock.storage_id,
                origin=stock.country,
                destination=destination,
                quantity=destination.quantity,
                method=row["logisticName"],
                total_cost=row.get("logisticPrice"),
                currency="USD",
                taxes_fee=row.get("taxesFee"),
                clearance_operation_fee=row.get("clearanceOperationFee"),
                total_postage_fee=row.get("totalPostageFee"),
                delivery_min_days=minimum,
                delivery_max_days=maximum,
                tracking=None,
                observed_at=result.observed_at,
            )

        return self._parse(result.data, result, build, identity=lambda row: row["method"])
