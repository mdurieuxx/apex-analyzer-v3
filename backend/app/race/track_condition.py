"""
Track condition monitor based on per-team best laps in current stints.

Optimal conditions = when teams are achieving their best lap times.
Reference = median of each team's best lap (ms) in their current stint.

When a team pits and starts a new stint, their previous best is removed
from the reference so the reference always reflects active racing pace.
"""
import statistics


class TrackConditionMonitor:
    def __init__(self, min_teams: int = 4):
        self._team_bests: dict[str, int] = {}  # team_id -> best ms in current stint
        self._MIN_LAP_MS = 30_000
        self._MAX_LAP_MS = 300_000
        self._MIN_TEAMS = min_teams

    def update_team_best(self, team_id: str, best_ms: int) -> None:
        """Update the best lap for a team in its current stint."""
        if self._MIN_LAP_MS < best_ms < self._MAX_LAP_MS:
            self._team_bests[team_id] = best_ms

    def reset_team(self, team_id: str) -> None:
        """Remove a team's contribution at pit exit (new stint = blank slate)."""
        self._team_bests.pop(team_id, None)

    def reference_ms(self) -> float | None:
        """Median of per-team best laps — represents optimal current conditions."""
        bests = list(self._team_bests.values())
        if len(bests) < self._MIN_TEAMS:
            return None
        return statistics.median(bests)

    def normalize(self, ms: int) -> float | None:
        """
        Ratio of lap time to current reference.
        1.00 = matching optimal current pace, >1.00 = slower.
        Returns None during bootstrap (fewer than min_teams have valid bests).
        """
        ref = self.reference_ms()
        if ref is None or ref == 0:
            return None
        if not (self._MIN_LAP_MS < ms < self._MAX_LAP_MS):
            return None
        return ms / ref

    def has_reference(self) -> bool:
        return len(self._team_bests) >= self._MIN_TEAMS

    def add_lap(self, ms: int) -> None:
        """Legacy stub — superseded by update_team_best."""
        pass
