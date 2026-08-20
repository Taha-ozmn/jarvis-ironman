"""Complexity + token/$ estimates — placeholders, never invoices.

Rates come from config.yaml ``cost.rates`` (USD per 1M tokens). Fill them
yourself; zeros mean "unpriced". FastBrain stays $0 (no Cursor).
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Optional

from brain.task_router import classify_complexity

logger = logging.getLogger(__name__)

# Relative cost units (not real $) — for routing / budgets later
COST_UNITS = {
    "fast": 0,
    "simple": 1,
    "complex": 5,
    "deep": 12,
}

# Heuristic output tokens when the SDK does not return usage.
_OUTPUT_TOKENS = {
    "fast": 0,
    "simple": 80,
    "complex": 400,
    "deep": 1200,
}
_INPUT_MULT = {
    "fast": 0.0,
    "simple": 2.0,
    "complex": 4.0,
    "deep": 8.0,
}

DEFAULT_CHARS_PER_TOKEN = 4
USD_PER_MILLION = 1_000_000.0


def estimate_complexity(command: str, *, brain_path: str = "deep") -> str:
    """Return simple | complex | deep | fast."""
    path = (brain_path or "").lower()
    if path in ("fast", "meta", "tool", "legacy"):
        return "fast"
    return classify_complexity(command or "")


def estimate_cost_units(complexity: str) -> int:
    return int(COST_UNITS.get((complexity or "simple").lower(), 1))


def estimate_tokens(
    command: str,
    *,
    complexity: str = "simple",
    chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
) -> tuple[int, int]:
    """Rough token guess from command length. Not vendor usage."""
    key = (complexity or "simple").lower()
    if key == "fast":
        return 0, 0
    cpt = max(1, int(chars_per_token or DEFAULT_CHARS_PER_TOKEN))
    base = max(1, math.ceil(len(command or "") / cpt))
    tokens_in = int(base * _INPUT_MULT.get(key, 2.0))
    tokens_out = int(_OUTPUT_TOKENS.get(key, 80))
    return tokens_in, tokens_out


def _rate_pair(rates: dict[str, Any], model: str) -> tuple[float, float]:
    models = rates if isinstance(rates, dict) else {}
    block = models.get(model) or models.get("default") or {}
    if not isinstance(block, dict):
        block = {}
    try:
        inp = float(block.get("input_per_million") or 0.0)
    except (TypeError, ValueError):
        inp = 0.0
    try:
        out = float(block.get("output_per_million") or 0.0)
    except (TypeError, ValueError):
        out = 0.0
    return max(0.0, inp), max(0.0, out)


def estimate_usd(
    tokens_in: int,
    tokens_out: int,
    *,
    input_per_million: float,
    output_per_million: float,
) -> float:
    usd = (
        tokens_in * float(input_per_million)
        + tokens_out * float(output_per_million)
    ) / USD_PER_MILLION
    return round(max(0.0, usd), 6)


class CostMeter:
    """Append-only JSON log of complexity + estimated USD (data/cost_meter.json)."""

    def __init__(
        self,
        path: Path | str,
        *,
        max_records: int = 400,
        rates: Optional[dict[str, Any]] = None,
        chars_per_token: int = DEFAULT_CHARS_PER_TOKEN,
        currency: str = "USD",
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_records = max(50, int(max_records))
        cfg = dict(rates or {})
        nested = cfg.get("rates") if isinstance(cfg.get("rates"), dict) else None
        self.rates = dict(nested if nested is not None else cfg)
        self.chars_per_token = max(
            1,
            int(cfg.get("chars_per_token") or chars_per_token or DEFAULT_CHARS_PER_TOKEN),
        )
        self.currency = str(cfg.get("currency") or currency or "USD")
        self.enabled = bool(cfg.get("enabled", True)) if "enabled" in cfg else True
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"records": [], "totals": {}, "invoice": False}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"records": [], "totals": {}, "invoice": False}
        if not isinstance(raw, dict):
            return {"records": [], "totals": {}, "invoice": False}
        raw.setdefault("records", [])
        raw.setdefault("totals", {})
        raw["invoice"] = False
        return raw

    def _save_unlocked(self) -> None:
        records = self._data.get("records") or []
        if len(records) > self.max_records:
            self._data["records"] = records[-self.max_records :]
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def record(
        self,
        command: str,
        *,
        brain_path: str = "deep",
        request_id: Optional[str] = None,
        model: Optional[str] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
    ) -> dict[str, Any]:
        complexity = estimate_complexity(command, brain_path=brain_path)
        units = estimate_cost_units(complexity)
        model_name = (model or "").strip() or "default"
        est_in, est_out = estimate_tokens(
            command,
            complexity=complexity,
            chars_per_token=self.chars_per_token,
        )
        t_in = int(tokens_in) if tokens_in is not None else est_in
        t_out = int(tokens_out) if tokens_out is not None else est_out
        inp_rate, out_rate = _rate_pair(self.rates, model_name)
        usd = estimate_usd(
            t_in,
            t_out,
            input_per_million=inp_rate,
            output_per_million=out_rate,
        )
        priced = inp_rate > 0 or out_rate > 0
        entry = {
            "complexity": complexity,
            "units": units,
            "brain_path": brain_path,
            "intent": (command or "")[:64],
            "model": model_name if model_name != "default" else (model or ""),
            "request_id": (request_id or "")[:32],
            "tokens_in": t_in,
            "tokens_out": t_out,
            "estimated_usd": usd,
            "currency": self.currency,
            "invoice": False,
            "priced": priced,
            "note": (
                "estimate from config.cost.rates — not an invoice"
                if priced
                else "unpriced — fill config.cost.rates (USD per 1M tokens)"
            ),
            "ts": time.time(),
        }
        if not self.enabled:
            logger.info(
                "cost_meter skipped enabled=false rid=%s",
                request_id or "-",
            )
            return entry
        with self._lock:
            self._data.setdefault("records", []).append(entry)
            totals = self._data.setdefault("totals", {})
            totals[complexity] = int(totals.get(complexity) or 0) + 1
            totals["units"] = int(totals.get("units") or 0) + units
            totals["estimated_usd"] = round(
                float(totals.get("estimated_usd") or 0.0) + usd, 6
            )
            totals["tokens_in"] = int(totals.get("tokens_in") or 0) + t_in
            totals["tokens_out"] = int(totals.get("tokens_out") or 0) + t_out
            self._data["invoice"] = False
            self._save_unlocked()
        logger.info(
            "cost_meter rid=%s path=%s complexity=%s tokens=%s/%s usd=%s priced=%s",
            request_id or "-",
            brain_path,
            complexity,
            t_in,
            t_out,
            usd,
            priced,
        )
        return entry

    def totals(self) -> dict[str, Any]:
        with self._lock:
            out = dict(self._data.get("totals") or {})
            out["invoice"] = False
            return out
