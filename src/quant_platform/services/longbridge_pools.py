"""Build real stock pools from read-only Longbridge positions and watchlists."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_platform.clients import LongbridgeCLIClient
from quant_platform.config import Settings
from quant_platform.core.product_models import StockPoolMember, StockPoolSnapshot
from quant_platform.services.bootstrap import bootstrap_local_state
from quant_platform.services.operation_log import OperationLogger, operation_log_root
from quant_platform.time_utils import iso_beijing

OPTION_SYMBOL_RE = re.compile(r"\d{6}[CP]\d{5,}", re.IGNORECASE)


@dataclass(slots=True)
class LongbridgeTradable:
    symbol: str
    provider_symbol: str
    name: str | None = None
    market: str = "US"
    quantity: float | None = None
    cost_price: float | None = None
    available_quantity: float | None = None
    currency: str | None = None
    watchlist_groups: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "provider_symbol": self.provider_symbol,
            "name": self.name,
            "market": self.market,
            "quantity": self.quantity,
            "available_quantity": self.available_quantity,
            "cost_price": self.cost_price,
            "currency": self.currency,
            "watchlist_groups": self.watchlist_groups,
            "sources": self.sources,
            "tags": self.tags,
        }


@dataclass(slots=True)
class LongbridgePoolSyncResult:
    generated_at_beijing: str
    pool_paths: dict[str, Path]
    metadata_path: Path
    position_count: int
    watchlist_count: int
    combined_count: int
    excluded_count: int


class LongbridgeStockPoolService:
    """Create local pool artifacts from Longbridge read-only account data."""

    def __init__(self, settings: Settings, client: LongbridgeCLIClient | None = None) -> None:
        self.settings = settings
        self.artifacts = bootstrap_local_state(settings)
        self.client = client or LongbridgeCLIClient.from_data_config(settings.data)
        self.logger = OperationLogger(operation_log_root(settings), "longbridge_pools")

    def sync(self) -> LongbridgePoolSyncResult:
        self.logger.info("longbridge_pools.sync.start", provider=self.client.provider_name)
        positions_payload = self.client.fetch_positions()
        watchlists_payload = self.client.fetch_watchlists()
        positions, watchlist, excluded = normalize_longbridge_pool_inputs(
            positions_payload=positions_payload,
            watchlists_payload=watchlists_payload,
        )
        combined = _merge_tradables(positions, watchlist)

        generated_at = _utcnow()
        metadata = {
            "generated_at_beijing": iso_beijing(),
            "provider": self.client.provider_name,
            "positions": {item.symbol: item.to_metadata() for item in positions},
            "watchlist": {item.symbol: item.to_metadata() for item in watchlist},
            "combined": {item.symbol: item.to_metadata() for item in combined},
            "excluded": excluded,
            "note": "Local sensitive artifact. Do not commit real account/watchlist data.",
        }

        pools = {
            "longbridge_positions": _build_pool(
                pool_id="longbridge_positions",
                name="Longbridge Positions",
                candidates=positions,
                source="longbridge_cli_positions",
                updated_at=generated_at,
            ),
            "longbridge_watchlist": _build_pool(
                pool_id="longbridge_watchlist",
                name="Longbridge Watchlist",
                candidates=watchlist,
                source="longbridge_cli_watchlist",
                updated_at=generated_at,
            ),
            "longbridge_core": _build_pool(
                pool_id="longbridge_core",
                name="Longbridge Core",
                candidates=combined,
                source="longbridge_cli_positions_watchlist",
                updated_at=generated_at,
                notes="Union of real Longbridge stock positions and watchlist symbols. Indexes and options are excluded.",
            ),
        }

        pool_paths = {pool_id: self._write_pool(pool, metadata["combined"]) for pool_id, pool in pools.items()}
        metadata_path = self._write_metadata(metadata)
        self.logger.info(
            "longbridge_pools.sync.success",
            positions=len(positions),
            watchlist=len(watchlist),
            combined=len(combined),
            excluded=len(excluded),
            metadata_path=str(metadata_path),
        )
        return LongbridgePoolSyncResult(
            generated_at_beijing=str(metadata["generated_at_beijing"]),
            pool_paths=pool_paths,
            metadata_path=metadata_path,
            position_count=len(positions),
            watchlist_count=len(watchlist),
            combined_count=len(combined),
            excluded_count=len(excluded),
        )

    def _write_pool(self, pool: StockPoolSnapshot, metadata_by_symbol: object) -> Path:
        path = self.artifacts.layout.stock_pool_path("longbridge", pool.pool_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _serialize_pool(pool)
        if isinstance(metadata_by_symbol, dict):
            payload["metadata"] = {
                symbol: metadata_by_symbol.get(symbol)
                for symbol in pool.symbols
                if metadata_by_symbol.get(symbol) is not None
            }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _write_metadata(self, payload: dict[str, object]) -> Path:
        path = self.settings.storage.reference_dir / "system" / "longbridge" / "real_stock_pool_metadata.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def normalize_longbridge_pool_inputs(
    *,
    positions_payload: list[dict[str, Any]],
    watchlists_payload: list[dict[str, Any]],
) -> tuple[list[LongbridgeTradable], list[LongbridgeTradable], list[dict[str, object]]]:
    excluded: list[dict[str, object]] = []
    positions: list[LongbridgeTradable] = []
    for item in positions_payload:
        tradable, reason = _tradable_from_position(item)
        if tradable:
            positions.append(tradable)
        elif reason:
            excluded.append(reason)

    watchlist_by_symbol: dict[str, LongbridgeTradable] = {}
    for group in watchlists_payload:
        group_name = _watchlist_group_name(group)
        for security in _watchlist_securities(group):
            tradable, reason = _tradable_from_watchlist(security, group_name=group_name)
            if tradable:
                existing = watchlist_by_symbol.get(tradable.symbol)
                if existing:
                    existing.watchlist_groups = _ordered_unique([*existing.watchlist_groups, *tradable.watchlist_groups])
                    existing.tags = _ordered_unique([*existing.tags, *tradable.tags])
                    existing.sources = _ordered_unique([*existing.sources, *tradable.sources])
                    continue
                watchlist_by_symbol[tradable.symbol] = tradable
            elif reason:
                excluded.append(reason)

    return _dedupe_tradables(positions), list(watchlist_by_symbol.values()), excluded


def _tradable_from_position(item: dict[str, Any]) -> tuple[LongbridgeTradable | None, dict[str, object] | None]:
    provider_symbol = _provider_symbol(item)
    normalized, reason = _normalize_tradable_symbol(provider_symbol, item)
    if not normalized:
        return None, reason
    quantity = _optional_float(_first_value(item, "quantity", "qty", "stock_quantity"))
    if quantity is not None and quantity <= 0:
        return None, _excluded(provider_symbol, "zero_position")
    return LongbridgeTradable(
        symbol=normalized,
        provider_symbol=provider_symbol,
        name=_optional_str(_first_value(item, "name", "stock_name", "display_name")),
        market="US",
        quantity=quantity,
        available_quantity=_optional_float(_first_value(item, "available", "available_quantity")),
        cost_price=_optional_float(_first_value(item, "cost_price", "average_cost", "avg_cost", "cost")),
        currency=_optional_str(_first_value(item, "currency")),
        sources=["longbridge_positions"],
        tags=["holding"],
    ), None


def _tradable_from_watchlist(item: dict[str, Any], *, group_name: str) -> tuple[LongbridgeTradable | None, dict[str, object] | None]:
    provider_symbol = _provider_symbol(item)
    normalized, reason = _normalize_tradable_symbol(provider_symbol, item)
    if not normalized:
        return None, reason
    return LongbridgeTradable(
        symbol=normalized,
        provider_symbol=provider_symbol,
        name=_optional_str(_first_value(item, "name", "stock_name", "display_name")),
        market="US",
        watchlist_groups=[group_name] if group_name else [],
        sources=["longbridge_watchlist"],
        tags=["watchlist"],
    ), None


def _normalize_tradable_symbol(provider_symbol: str, payload: dict[str, Any]) -> tuple[str | None, dict[str, object] | None]:
    symbol = provider_symbol.strip().upper()
    if not symbol:
        return None, _excluded(provider_symbol, "missing_symbol")
    security_type = str(_first_value(payload, "security_type", "type", "sec_type", "asset_type") or "").lower()
    if any(token in security_type for token in ("option", "warrant")):
        return None, _excluded(provider_symbol, "derivative")
    if "index" in security_type:
        return None, _excluded(provider_symbol, "index")

    if "." not in symbol:
        symbol = f"{symbol}.US"
    code, market = symbol.rsplit(".", 1)
    if market != "US":
        return None, _excluded(provider_symbol, f"unsupported_market:{market}")
    if code.startswith("."):
        return None, _excluded(provider_symbol, "index")
    if OPTION_SYMBOL_RE.search(code):
        return None, _excluded(provider_symbol, "option")
    if not re.match(r"^[A-Z][A-Z0-9.-]{0,12}$", code):
        return None, _excluded(provider_symbol, "unsupported_symbol_shape")
    return code.replace("-", "."), None


def _merge_tradables(positions: list[LongbridgeTradable], watchlist: list[LongbridgeTradable]) -> list[LongbridgeTradable]:
    merged: dict[str, LongbridgeTradable] = {item.symbol: item for item in positions}
    for item in watchlist:
        existing = merged.get(item.symbol)
        if existing is None:
            merged[item.symbol] = item
            continue
        existing.name = existing.name or item.name
        existing.watchlist_groups = _ordered_unique([*existing.watchlist_groups, *item.watchlist_groups])
        existing.sources = _ordered_unique([*existing.sources, *item.sources])
        existing.tags = _ordered_unique([*existing.tags, *item.tags])
    return list(merged.values())


def _build_pool(
    *,
    pool_id: str,
    name: str,
    candidates: list[LongbridgeTradable],
    source: str,
    updated_at: datetime,
    notes: str | None = None,
) -> StockPoolSnapshot:
    members = [
        StockPoolMember(
            symbol=item.symbol,
            sources=item.sources,
            themes=item.watchlist_groups,
            tags=item.tags,
            status="candidate",
            reasons=_member_reasons(item),
        )
        for item in candidates
    ]
    return StockPoolSnapshot(
        pool_id=pool_id,
        name=name,
        pool_type="longbridge",
        source=source,
        market="us_equities",
        symbols=[member.symbol for member in members],
        members=members,
        updated_at=updated_at,
        notes=notes,
    )


def _member_reasons(item: LongbridgeTradable) -> list[str]:
    reasons: list[str] = []
    if "holding" in item.tags:
        if item.quantity is not None:
            reasons.append(f"position_quantity={item.quantity:g}")
        if item.cost_price is not None:
            reasons.append(f"position_cost_price={item.cost_price:g}")
    for group in item.watchlist_groups:
        reasons.append(f"watchlist_group={group}")
    return reasons


def _serialize_pool(pool: StockPoolSnapshot) -> dict[str, object]:
    payload = asdict(pool)
    payload["updated_at"] = pool.updated_at.isoformat()
    payload["generated_from"] = "longbridge_cli_read_only"
    payload["sensitivity"] = "contains_real_account_or_watchlist_symbols"
    return payload


def _watchlist_group_name(group: dict[str, Any]) -> str:
    return str(_first_value(group, "name", "group_name", "watchlist_name", "title") or "未分组")


def _watchlist_securities(group: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = _first_value(group, "securities", "stocks", "items", "symbols", "list") or []
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    result: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, str):
            result.append({"symbol": item})
        elif isinstance(item, dict):
            nested = item.get("security") if isinstance(item.get("security"), dict) else None
            result.append({**item, **(nested or {})})
    return result


def _provider_symbol(item: dict[str, Any]) -> str:
    value = _first_value(item, "symbol", "ticker", "code", "security_symbol")
    if isinstance(value, dict):
        value = _first_value(value, "symbol", "ticker", "code")
    return str(value or "").upper()


def _first_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _excluded(provider_symbol: str, reason: str) -> dict[str, object]:
    return {"provider_symbol": provider_symbol, "reason": reason}


def _dedupe_tradables(items: list[LongbridgeTradable]) -> list[LongbridgeTradable]:
    return list({item.symbol: item for item in items}.values())


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)
