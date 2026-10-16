"""Prepare offline; capture exactly one approved catalog page; finish entirely locally.

Run as `python -m scripts.v5_live_acceptance --help`. Never loads unrelated credentials.
An approval digest records scope; the operator must obtain human approval before capture.
"""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from src.database.database import ProductRepository
from src.discovery.comparison import ComparisonGroup, comparison_workspace, save_group
from src.discovery.models import CatalogItem, DiscoveryResult, DiscoverySearch
from src.discovery.repository import DiscoveryRepository
from src.discovery.service import DiscoveryService, save_candidate
from src.supply.cj_provider import CJDropShippingProvider
from src.supply.cj_transport import CJResearchTransport
from src.supply.models import Destination


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, ensure_ascii=False)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def prepare(database: Path, evidence_folder: Path):
    database, evidence_folder = Path(database).resolve(), Path(evidence_folder).resolve()
    if database.exists() or evidence_folder.exists():
        raise FileExistsError("Acceptance paths must be new; existing data is preserved.")
    evidence_folder.mkdir(parents=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    database.touch(exist_ok=False)
    repo = ProductRepository(database)
    DiscoveryRepository(repo).enable()
    scope = {
        "database": str(database),
        "search": {"keyWord": "laptop stand", "page": 1, "size": 10},
        "max_http_requests": 2,
        "max_catalog_requests": 1,
        "max_seconds": 30,
        "automatic_retries": 0,
        "documented_points": 50,
        "cash_cost": (
            "No per-call cash fee stated in CJ points documentation; not verified by billing."
        ),
        "auth": "At most one POST /api2.0/v1/authentication/getAccessToken; zero listed points",
        "catalog": "One GET /api2.0/v1/product/listV2; 50 points",
        "destination": Destination(country="SE").model_dump(mode="json"),
        "docs": [
            "https://developers.cjdropshipping.com/en/api/api2/api/product.html",
            "https://developers.cjdropshipping.com/en/api/api2/api/auth.html",
            "https://developers.cjdropshipping.com/en/api/api2/standard/points.html",
        ],
    }
    scope["approval_id"] = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[
        :20
    ]
    _write(evidence_folder / "scope.json", scope)
    return scope


def _scope(database, folder):
    scope = _read(folder / "scope.json")
    original = dict(scope)
    approval = original.pop("approval_id")
    expected = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()[:20]
    if approval != expected or scope["database"] != str(Path(database).resolve()):
        raise ValueError("Acceptance scope/database changed; prepare a new scope for approval.")
    return scope


def capture(database, evidence_folder, *, approval, provider=None, evidence_class="NEW_V5_LIVE"):
    folder = Path(evidence_folder)
    scope = _scope(database, folder)
    if approval != scope["approval_id"]:
        raise ValueError("Explicit matching approval is required before provider construction.")
    if (folder / "capture.json").exists():
        provenance = _read(folder / "capture-provenance.json")
        if provenance["evidence_class"] != evidence_class:
            raise ValueError("A fixture cannot be relabeled as live evidence.")
        return DiscoveryResult.model_validate(_read(folder / "capture.json"))
    if (folder / "attempt-started.json").exists():
        raise RuntimeError("Previous request outcome is uncertain; never automatically resubmit.")
    repo = ProductRepository(database)
    with repo._connection() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            # Migration metadata is allowed; all application record tables must be empty.
            if table in {"workspace_meta_v5", "supply_v4_meta"}:
                continue
            if conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]:
                raise ValueError("Live capture requires an empty acceptance database.")
    _write(
        folder / "attempt-started.json",
        {
            "approval_id": approval,
            "started_at": datetime.now(UTC).isoformat(),
            "evidence_class": evidence_class,
        },
    )
    provider = provider or CJDropShippingProvider(transport=CJResearchTransport(retry_limit=0))
    result = DiscoveryService(repo, provider=provider).search(
        DiscoverySearch(query="laptop stand"), max_requests=2
    )
    # Sanitized adapter output only; no raw auth, tokens or account response dumps.
    _write(
        folder / "capture-provenance.json",
        {
            "approval_id": approval,
            "evidence_class": evidence_class,
            "scope": scope,
            "requests": result.telemetry.requests,
            "retries": result.telemetry.retries,
            "searched_at": result.searched_at.isoformat(),
            "quota": "50 documented points if catalog request dispatched; balance not queried",
        },
    )
    _write(folder / "capture.json", result.model_dump(mode="json"))
    return result


def finish(database, evidence_folder, product_ids):
    """Explicitly chosen response IDs only. No provider construction or network calls."""
    folder = Path(evidence_folder)
    scope = _scope(database, folder)
    target = folder / "comparison.json"
    if target.exists():
        original = _read(target)
        if original["acceptance"]["supplier_ids"] != product_ids:
            raise ValueError(
                "Existing acceptance export uses other IDs; preserve the original evidence."
            )
        return original  # No mutation, including operator-edited decisions or notes.
    result = DiscoveryResult.model_validate(_read(folder / "capture.json"))
    provenance = _read(folder / "capture-provenance.json")
    items = [CatalogItem.model_validate(row) for row in result.outcome.records]
    lookup = {item.candidate.product_id: item for item in items}
    if len(product_ids) != 3 or len(set(product_ids)) != 3 or not set(product_ids) <= lookup.keys():
        raise ValueError("Choose exactly three distinct suitable IDs from this captured page.")
    if any(lookup[pid].evidence_kind != "provider_observation" for pid in product_ids):
        raise ValueError("Synthetic examples are not live acceptance candidates.")
    repo = ProductRepository(database)
    rows = [
        save_candidate(repo, lookup[pid], Destination.model_validate(scope["destination"]))
        for pid in product_ids
    ]
    for row, pid in zip(rows, product_ids, strict=True):
        assert row.product.supplier_identity.product_id == pid
        assert (
            save_candidate(repo, lookup[pid], Destination(country="SE")).product.id
            == row.product.id
        )
    # Reopen from disk, as the UI/process restart will. No in-memory results are reused.
    reopened = ProductRepository(database)
    by_id = {row.product.id: row for row in reopened.list_saved()}
    rows = [by_id[row.product.id] for row in rows]
    group = ComparisonGroup(
        name="V5 catalog acceptance",
        product_ids=[row.product.id for row in rows],
        notes=("Catalog observations only. Variants, stock, freight and demand not fetched."),
    )
    save_group(reopened, group)
    document = comparison_workspace(rows, reopened, group=group)
    document["acceptance"] = {
        "evidence_class": provenance["evidence_class"],
        "scope": scope,
        "requests": provenance.get("requests", {}),
        "supplier_ids": product_ids,
        "local_baseline_analysis": (
            "Saved V4 heuristic/demo analysis is not measured demand evidence."
        ),
        "restart": (
            "Repository reopened; actual app restart requires separate browser verification."
        ),
    }
    assert all(
        item["demand"] is None and item["selection"] is None for item in document["products"]
    )
    assert all(
        item["financial"]["calculation"]["economics"]["estimated_net_profit"] is None
        for item in document["products"]
    )
    _write(target, document)
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "capture", "finish"])
    parser.add_argument("database", type=Path)
    parser.add_argument("evidence_folder", type=Path)
    parser.add_argument("--approve-scope")
    parser.add_argument("--cj-env-file", type=Path)
    parser.add_argument("--product-ids", nargs=3)
    args = parser.parse_args()
    if args.action == "prepare":
        print(json.dumps(prepare(args.database, args.evidence_folder), indent=2))
    elif args.action == "capture":
        scope = _scope(args.database, args.evidence_folder)
        if args.approve_scope != scope["approval_id"]:
            parser.error("Matching --approve-scope is required after human approval.")
        if args.cj_env_file and "CJ_API_KEY" not in os.environ:
            from dotenv import dotenv_values

            value = dotenv_values(args.cj_env_file).get("CJ_API_KEY")
            if value:
                os.environ["CJ_API_KEY"] = value
        result = capture(args.database, args.evidence_folder, approval=args.approve_scope)
        print(
            json.dumps(
                {
                    "status": result.outcome.status,
                    "candidates": [
                        {"id": r["candidate"]["product_id"], "name": r["candidate"]["name"]}
                        for r in result.outcome.records
                    ],
                },
                indent=2,
            )
        )
    else:
        if not args.product_ids:
            parser.error("Select three suitable captured IDs explicitly with --product-ids.")
        document = finish(args.database, args.evidence_folder, args.product_ids)
        print(
            f"Local comparison exported: {len(document['products'])} candidates. "
            "No provider requests."
        )


if __name__ == "__main__":
    main()
