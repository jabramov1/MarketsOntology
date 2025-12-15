from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Iterator, List, Optional, Sequence, TypeVar

import numpy as np
import pandas as pd

T = TypeVar("T")


def chunked(seq: Sequence[T], size: int) -> Iterator[List[T]]:
    """Yield list chunks from a sequence."""
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])


def find_col(df: pd.DataFrame, *names: str) -> Optional[str]:
    """Find first matching column name in dataframe."""
    for n in names:
        if n in df.columns:
            return n
    return None


def first_of(d: dict, *keys, default=None) -> Any:
    """Return first non-None value from dict for given keys."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def is_valid(val: Any) -> bool:
    """Check if value is not None/NaN."""
    if val is None:
        return False
    if isinstance(val, float) and np.isnan(val):
        return False
    return True


def safe_int(val: Any) -> Optional[int]:
    """Convert to int, handling NaN/None."""
    if not is_valid(val):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def safe_float(val: Any) -> Optional[float]:
    """Convert to float, handling NaN/None."""
    if not is_valid(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_str(val: Any) -> Optional[str]:
    """Convert to stripped string, handling NaN/None."""
    if not is_valid(val):
        return None
    s = str(val).strip()
    return s if s else None


def dt_parse(x: Any) -> Optional[str]:
    """Parse datetime to ISO string."""
    if not is_valid(x):
        return None
    try:
        return pd.to_datetime(x, utc=True).to_pydatetime().isoformat()
    except Exception:
        return None


def time_to_seconds(mmss: Any) -> Optional[int]:
    """Convert MM:SS string to total seconds."""
    if not isinstance(mmss, str) or ":" not in mmss:
        return None
    try:
        m, s = mmss.split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return None


def approx_play_timestamp(game_start_iso: str, qtr: Any, clock_mmss: Any) -> Optional[str]:
    """
    Approximate play timestamp from quarter + time remaining.
    Example: Q2 with 8:30 left = 15m (Q1) + 6.5m (elapsed Q2) = 21.5m from kickoff.
    """
    if game_start_iso is None:
        return None
    try:
        start = datetime.fromisoformat(game_start_iso.replace("Z", "+00:00"))
    except Exception:
        return None
    sec_rem = time_to_seconds(clock_mmss)
    if sec_rem is None:
        return None
    q = safe_int(qtr)
    if q is None:
        return None
    q_len = 15 * 60  # 15 min quarters
    elapsed = (max(q, 1) - 1) * q_len + (q_len - sec_rem)
    ts = start + timedelta(seconds=int(elapsed))
    return ts.replace(tzinfo=timezone.utc).isoformat()


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def now_utc_iso() -> str:
    """Return current UTC timestamp as ISO string for ingestion tracking."""
    return datetime.now(timezone.utc).isoformat()
