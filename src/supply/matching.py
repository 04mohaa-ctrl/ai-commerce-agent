"""Pure conservative V4 identity and destination compatibility checks."""

import re
import unicodedata
from decimal import Decimal

from src.research.matching import COLORS, match_product, normalized_name
from src.schemas.product import Product
from src.supply.models import (
    Destination,
    SupplierMatch,
    SupplierProductCandidate,
    SupplierVariant,
)

_NUMBER = r"\d+(?:\.\d+)?"
_UNITS = r"ml|liters?|litres?|l|kg|g|cm|mm|inches|inch|in|oz"
_MEASURE = re.compile(rf"\b({_NUMBER})\s*({_UNITS})\b", re.I)
_VOLTAGE = re.compile(rf"\b({_NUMBER})(?:\s*[-–/]\s*({_NUMBER}))?\s*(?:volts?|v)\b", re.I)
_PACK = re.compile(
    r"\b(\d+)\s*[- ]?\s*(?:pack|count|pcs|pieces|ct)\b|\b(?:pack|set)\s+of\s+(\d+)\b", re.I
)
_MODEL = re.compile(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z][a-z0-9]*(?:-[a-z0-9]+)*\b", re.I)
_LABEL = re.compile(r"(?:^|[;\n])\s*([\w ]+)\s*[:=]\s*([^;\n]+)")
_DIMENSION = re.compile(
    rf"\b({_NUMBER})\s*[x×]\s*({_NUMBER})(?:\s*[x×]\s*({_NUMBER}))?\s*(cm|mm|inches|inch|in)\b",
    re.I,
)
_ELECTRICAL = re.compile(
    r"\b(electric|electrical|heated|heating|powered|charger|charging|kettle|appliance)\b", re.I
)
_ALIASES = {
    "pack": "count",
    "pieces": "count",
    "quantity": "count",
    "pack count": "count",
    "size": "dimensions",
    "dimension": "dimensions",
    "input voltage": "voltage",
    "rated voltage": "voltage",
    "plug type": "plug",
    "power plug": "plug",
    "model number": "model",
    "brand name": "brand",
    "volume": "capacity",
}
_FACTORS = {
    "ml": ("capacity", Decimal(1)),
    "l": ("capacity", Decimal(1000)),
    "liter": ("capacity", Decimal(1000)),
    "liters": ("capacity", Decimal(1000)),
    "litre": ("capacity", Decimal(1000)),
    "litres": ("capacity", Decimal(1000)),
    "oz": ("capacity", Decimal("29.5735295625")),
    "g": ("mass", Decimal(1)),
    "kg": ("mass", Decimal(1000)),
    "mm": ("dimensions", Decimal(1)),
    "cm": ("dimensions", Decimal(10)),
    "inch": ("dimensions", Decimal("25.4")),
    "inches": ("dimensions", Decimal("25.4")),
    "in": ("dimensions", Decimal("25.4")),
}
_EXPECTED_ELECTRICAL = {
    "US": ((Decimal(110), Decimal(120)), {"us", "a", "b"}),
    "GB": ((Decimal(220), Decimal(240)), {"uk", "gb", "g"}),
    "SE": ((Decimal(220), Decimal(240)), {"eu", "c", "f"}),
    "DE": ((Decimal(220), Decimal(240)), {"eu", "c", "f"}),
    "FR": ((Decimal(220), Decimal(240)), {"eu", "c", "e", "f"}),
}


def _text(value):
    return unicodedata.normalize("NFKC", value).casefold()


def _plug(value):
    value = normalized_name(value)
    value = re.sub(r"\b(plug|adapter|type|standard)\b", "", value).strip()
    return {
        "usa": "us",
        "united states": "us",
        "european": "eu",
        "europe": "eu",
        "british": "uk",
    }.get(value, value)


def _details(text, attributes=None):
    """Collect independent declarations so one field cannot hide a conflicting title."""
    result = {}

    def add(field, value):
        result.setdefault(field, set()).add(value)

    def measurements(value):
        dimension_spans = []
        for found in _DIMENSION.finditer(value):
            factor = _FACTORS[found.group(4).lower()][1]
            sizes = tuple(Decimal(item) * factor for item in found.group(1, 2, 3) if item)
            add("dimensions", sizes)
            dimension_spans.append(found.span())
        for found in _MEASURE.finditer(value):
            if any(start <= found.start() < end for start, end in dimension_spans):
                continue
            field, factor = _FACTORS[found.group(2).lower()]
            add(field, Decimal(found.group(1)) * factor)

    def field_value(field, value):
        field = _ALIASES.get(normalized_name(field), normalized_name(field))
        value = _text(value)
        if field in {"brand", "model", "color"} and value.strip():
            add(field, normalized_name(value))
        elif field == "plug":
            parsed = _plug(value)
            if parsed in {"us", "eu", "uk", "gb", "a", "b", "c", "e", "f", "g"}:
                add(field, parsed)
        elif field == "voltage":
            for low, high in _VOLTAGE.findall(value):
                add("voltage", (Decimal(low), Decimal(high or low)))
        elif field == "count" and re.fullmatch(r"\d+", value.strip()):
            add(field, int(value))
        elif field in {"capacity", "dimensions", "mass"}:
            measurements(value)

    text = _text(text)
    measurements(text)
    for first, second in _PACK.findall(text):
        add("count", int(first or second))
    for low, high in _VOLTAGE.findall(text):
        add("voltage", (Decimal(low), Decimal(high or low)))
    for plug in re.findall(r"\b(us|usa|eu|uk|gb)\s*(?:plug|adapter)\b", text):
        add("plug", _plug(plug))
    for plug in re.findall(r"\btype\s+([abcefg])\s*(?:plug)?\b", text):
        add("plug", plug)
    for color in set(normalized_name(text).split()) & COLORS:
        add("color", color)
    # Restrict free-title model detection to letter-leading model codes with digits.
    text_without_measurements = _MEASURE.sub("", _VOLTAGE.sub("", text))
    for model in _MODEL.findall(text_without_measurements):
        add("model", normalized_name(model))
    for field, value in _LABEL.findall(text):
        field_value(field, value)
    for field, value in (attributes or {}).items():
        if normalized_name(field).replace("_", " ") == "variant key":
            # CJ's documented combination label is observed data, not an inferred attribute.
            for composite_field, values in _details(value).items():
                result.setdefault(composite_field, set()).update(values)
        else:
            field_value(field, value)
    return result


def _identity_name(name):
    name = _text(name)
    name = _DIMENSION.sub("", name)
    name = _MEASURE.sub("", name)
    name = _VOLTAGE.sub("", name)
    name = _PACK.sub("", name)
    name = re.sub(r"\b(?:us|usa|eu|uk|gb)\s*(?:plug|adapter)\b", "", name)
    name = re.sub(r"\btype\s+[abcefg]\s*(?:plug)?\b", "", name)
    name = _MODEL.sub("", name)
    # Variant options are compared above from both titles and explicit attributes.
    # A second name-only discriminator check must not discard description facts.
    return " ".join(word for word in normalized_name(name).split() if word not in COLORS)


def _usb_charging_only(text, found, attributes=None):
    """Recognize an observed charging mode, without inventing voltage or an adapter."""
    text += "\n" + " ".join(f"{key}: {value}" for key, value in (attributes or {}).items())
    explicit = re.search(
        r"\busb[\s-]+(?:rechargeable|charging|powered)\b|"
        r"\b(?:charged|charging|powered)\s+(?:via|by)\s+usb\b",
        text,
        re.I,
    )
    mains = re.search(r"\b(?:mains|ac|adapter|wall|charger|dual[\s-]+power)\b", text, re.I)
    return bool(
        explicit
        and not mains
        and not found.get("plug")
        and all(0 < low <= high <= 48 for low, high in found.get("voltage", set()))
    )


def _electrical_issues(found, destination, electrical):
    contradictions, missing = [], []
    if not electrical:
        return contradictions, missing
    expected = _EXPECTED_ELECTRICAL.get(destination.country)
    for field in ("voltage", "plug"):
        if not found.get(field):
            missing.append(field)
    if expected is None:
        missing.append("destination electrical suitability")
    else:
        voltage_range, plugs = expected
        for low, high in found.get("voltage", set()):
            if low > high or max(low, voltage_range[0]) > min(high, voltage_range[1]):
                contradictions.append("Observed voltage is unsuitable for destination.")
        if any(plug not in plugs for plug in found.get("plug", set())):
            contradictions.append("Observed plug is unsuitable for destination.")
    return contradictions, missing


def destination_issue(
    candidate: SupplierProductCandidate,
    variant: SupplierVariant,
    destination: Destination,
) -> str | None:
    """Recheck a historical selected offer against a newly declared destination."""
    if (candidate.provider, candidate.product_id) != (variant.provider, variant.product_id):
        return "Supplier product identity conflict."
    title = candidate.name + "\n" + variant.name
    found = _details(title, variant.attributes)
    electrical = bool(
        _ELECTRICAL.search(title) or found.get("voltage") or found.get("plug")
    ) and not _usb_charging_only(title, found, variant.attributes)
    contradictions, missing = _electrical_issues(found, destination, electrical)
    if contradictions:
        return " ".join(contradictions)
    if missing:
        return "Missing observed " + ", ".join(missing) + "."
    return None


def candidate_viable(product: Product, candidate: SupplierProductCandidate) -> bool:
    """Reject unrelated catalog names locally before spending enrichment requests."""
    identity = product.model_copy(update={"name": _identity_name(product.name), "description": ""})
    return match_product(identity, _identity_name(candidate.name)).outcome != "NO_MATCH"


def match_supplier(
    product: Product,
    candidate: SupplierProductCandidate,
    variant: SupplierVariant,
    destination: Destination,
) -> SupplierMatch:
    """Compare names through V3, then require compatible observed variant facts."""
    if (candidate.provider, candidate.product_id) != (variant.provider, variant.product_id):
        return SupplierMatch(
            outcome="NO_MATCH",
            contradictions=["Supplier product identity conflict."],
            reasons=["Different product observations."],
        )
    wanted = _details(product.name + "\n" + product.description)
    found = _details(candidate.name + "\n" + variant.name, variant.attributes)
    usb_charging = _usb_charging_only(
        candidate.name + "\n" + variant.name, found, variant.attributes
    )
    if candidate.brand:
        found.setdefault("brand", set()).add(normalized_name(candidate.brand))
    contradictions = []
    missing = []
    for field in set(wanted) | set(found):
        expected, actual = wanted.get(field, set()), found.get(field, set())
        if field == "voltage":
            if (
                expected
                and actual
                and any(not any(max(a, c) <= min(b, d) for c, d in expected) for a, b in actual)
            ):
                contradictions.append("Conflicting voltage declarations.")
        elif expected and actual and expected != actual:
            contradictions.append(f"Conflicting {field} declarations.")
        if field not in {"voltage", "plug"} and bool(expected) != bool(actual):
            missing.append(field)
        if field in {"voltage", "plug"} and expected and not actual:
            missing.append(field)
        if len(actual) > 1 and field in {"brand", "model", "count", "capacity", "dimensions"}:
            contradictions.append(f"Conflicting supplier {field} declarations.")

    electrical = bool(_ELECTRICAL.search(product.name + " " + product.description)) or bool(
        wanted.get("voltage") or wanted.get("plug")
    )
    electrical_contradictions, electrical_missing = _electrical_issues(
        found, destination, electrical and not usb_charging
    )
    contradictions.extend(electrical_contradictions)
    missing.extend(electrical_missing)
    if contradictions:
        return SupplierMatch(
            outcome="NO_MATCH",
            reasons=["Explicit variant contradiction prevents selection."],
            contradictions=sorted(set(contradictions)),
            missing_attributes=sorted(set(missing)),
        )

    # Reusing V3 overlap logic on normalized identity words avoids unit-text mismatches.
    identity_product = product.model_copy(
        update={"name": _identity_name(product.name), "description": ""}
    )
    candidate_match = match_product(identity_product, _identity_name(candidate.name))
    variant_identity = _identity_name(variant.name)
    option_words = COLORS | {
        "us",
        "eu",
        "uk",
        "gb",
        "s",
        "m",
        "l",
        "xl",
        "xxl",
        "small",
        "medium",
        "large",
        "standard",
    }
    if not variant_identity or set(variant_identity.split()).issubset(option_words):
        # Catalog variant names may contain only option labels, not the product title.
        variant_match = candidate_match
    else:
        variant_match = match_product(identity_product, variant_identity)
    if "NO_MATCH" in {candidate_match.outcome, variant_match.outcome}:
        return SupplierMatch(
            outcome="NO_MATCH",
            reasons=["Insufficient candidate or variant product identity overlap."],
            missing_attributes=sorted(set(missing)),
        )
    if missing or "AMBIGUOUS" in {candidate_match.outcome, variant_match.outcome}:
        return SupplierMatch(
            outcome="AMBIGUOUS",
            reasons=["Missing comparable decisive attributes require further evidence."],
            missing_attributes=sorted(set(missing)),
        )
    if candidate_match.outcome == variant_match.outcome == "MATCH":
        return SupplierMatch(
            outcome="MATCH",
            reasons=["Exact normalized identity and compatible observed variant attributes."]
            + (
                ["Observed USB charging; included mains adapter compatibility is unverified."]
                if usb_charging
                else []
            ),
        )
    return SupplierMatch(
        outcome="LIKELY_MATCH",
        reasons=["Related identity words; explicit attribute confirmation required."]
        + (
            ["Observed USB charging; included mains adapter compatibility is unverified."]
            if usb_charging
            else []
        ),
    )
