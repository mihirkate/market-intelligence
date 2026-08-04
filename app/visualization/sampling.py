"""Low-memory sampling helpers for dashboard visualizations."""

from __future__ import annotations

import pandas as pd


def downsample_frame(frame: pd.DataFrame, *, max_points: int) -> pd.DataFrame:
    """Evenly downsample a frame while preserving the latest rows."""
    if frame.empty or len(frame) <= max_points:
        return frame.copy()

    step = max(1, len(frame) // max_points)
    sampled = frame.iloc[::step].tail(max_points).copy()
    return sampled.reset_index(drop=True)
