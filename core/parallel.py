"""Run independent callables in parallel (Phase 13 latency budget)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional, TypeVar

T = TypeVar("T")


def run_parallel(
    jobs: list[tuple[str, Callable[[], T]]],
    *,
    max_workers: Optional[int] = None,
    timeout: Optional[float] = None,
) -> dict[str, T | BaseException]:
    """Execute named independent jobs; return name → result or exception.

    Order of completion is not guaranteed; keys preserve job names.
    """
    if not jobs:
        return {}
    workers = max_workers or min(8, max(1, len(jobs)))
    out: dict[str, T | BaseException] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs}
        for fut in as_completed(futures, timeout=timeout):
            name = futures[fut]
            try:
                out[name] = fut.result()
            except BaseException as err:  # noqa: BLE001 — surface to caller
                out[name] = err
    # Preserve declaration order for stable summaries
    return {name: out[name] for name, _ in jobs if name in out}
