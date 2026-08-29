"""
Cushion rule for Under markets (everywhere except Goal Lock).

Leave a one-goal gap so the next goal does not immediately lose the bet:
  Under 1.5 → only 0-0
  Under 2.5 → 0-0 or 1-0
  Under 3.5 → 0–2 goals
  Under 0.5 → never (no gap) on live / fusion / acca
"""

from __future__ import annotations


def under_has_cushion(line: float, goals: int) -> bool:
    if line < 1.5:
        return False
    return int(goals) < int(line)


def best_cushion_under_line(goals: int) -> float | None:
    """Tightest Under X.5 that still has a one-goal gap."""
    if goals <= 0:
        return 1.5
    if goals == 1:
        return 2.5
    if goals == 2:
        return 3.5
    if goals == 3:
        return 4.5
    return None
