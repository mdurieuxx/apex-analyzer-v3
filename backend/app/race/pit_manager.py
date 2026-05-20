"""
Pit lane queue logic for rental karting endurance.

Model:
  - N lanes (configurable), each lane holds up to M karts
  - When a team pits:
      1. Their current physical kart is added to the lane queue (FIFO)
      2. An active PitStop is recorded
  - After min_pit_duration_s elapses, the team is eligible to exit with
    the oldest kart waiting in the reserve (across all lanes)
  - The team's bib number is then assigned to that physical kart
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from race.state import RaceState, PitQueueKart, LivePitStop
from apex.grid_parser import LiveDriver

logger = logging.getLogger(__name__)


class PitManager:
    def __init__(self, state: RaceState, config):
        self.state = state
        self.config = config

    def _ensure_lanes(self):
        for lane in range(1, self.config.num_lanes + 1):
            if lane not in self.state.pit_lanes:
                self.state.pit_lanes[lane] = []

    def on_pit_stop_detected(self, driver: LiveDriver) -> LivePitStop:
        """Called when a team's pit count increases (detected from grid update).

        Two things happen immediately at pit entry:
          1. The team's inbound kart is added to the least-loaded lane (measured by
             team-dropped karts only — initial reserve karts don't count).
          2. The oldest kart in the pool is pre-assigned to this team so they know
             which kart they will receive when they exit.
        """
        self._ensure_lanes()

        current_kart = self.state.kart_assignments.get(driver.driver_id, "?")

        # Pre-assign the oldest available kart immediately at pit entry
        assigned_kart = self._reserve_oldest_kart(driver.kart)

        # driver.laps comes from the tlp column which shows elapsed minutes on some
        # circuits (e.g. Mariembourg Course mode) — prefer the reliable counter instead
        lap_count = self.state.driver_lap_counts.get(driver.driver_id) or driver.laps

        pit_stop = LivePitStop(
            driver_id=driver.driver_id,
            kart_label=current_kart,
            team=driver.team,
            bib=driver.kart,
            position=driver.position,
            lap=lap_count,
            pit_number=driver.pits,
            kart_out_label=assigned_kart,
        )

        # Add the inbound kart to the lane with fewest team-dropped karts.
        # Even if kart label is unknown, add a placeholder so the queue shows the team arriving.
        lane = self._least_loaded_lane()
        is_placeholder = not current_kart or current_kart == "?"
        kart_id = 0 if is_placeholder else self._kart_id_for_label(current_kart)
        queue_entry = PitQueueKart(
            kart_label=current_kart if not is_placeholder else "?",
            physical_kart_id=kart_id,
            lane=lane,
            from_team=True,
            from_bib=driver.kart,
            is_placeholder=is_placeholder,
        )
        self.state.pit_lanes[lane].append(queue_entry)
        logger.info("PIT IN: bib=%s kart=%s → lane %d (assigned out: %s)",
                    driver.kart, current_kart, lane, assigned_kart or "none")

        self.state.active_pit_stops[driver.driver_id] = pit_stop
        logger.info("PIT STOP detected: team=%s pos=%d pit#=%d", driver.team, driver.position, driver.pits)
        return pit_stop

    def on_team_exited_pits(self, driver_id: str) -> Optional[str]:
        """Called when a team is detected back on track.

        The kart was pre-assigned at pit entry (reserved in queue); remove it now
        and also remove the placeholder the team deposited when entering.
        Returns the label of the kart the team left with.
        """
        pit_stop = self.state.active_pit_stops.pop(driver_id, None)
        if not pit_stop:
            return None

        assigned = pit_stop.kart_out_label
        pit_stop.exited_at = datetime.now(timezone.utc)
        # Use event-time timestamps (proxy replay) when available — wall-clock is wrong
        # during accelerated replay and on reconnect (buffered messages arrive in bulk).
        if pit_stop.event_ts_entered is not None and pit_stop.event_ts_exited is not None:
            duration_s = int(pit_stop.event_ts_exited - pit_stop.event_ts_entered)
        else:
            duration_s = int((pit_stop.exited_at - pit_stop.timestamp).total_seconds())

        # Filter false positives: on reconnect, buffered Apex messages arrive in quick
        # succession so pit entry and exit are detected seconds apart.
        # Any stop shorter than half the configured minimum is discarded.
        min_realistic_s = max(30, self.config.min_pit_duration_s // 2)
        if duration_s < min_realistic_s:
            logger.info("Ignoring false-positive pit stop for team=%s (duration=%ds < %ds)",
                        pit_stop.team, duration_s, min_realistic_s)
            if assigned:
                self.state.kart_assignments[driver_id] = assigned
            return assigned

        self.state.pit_history.append(pit_stop)

        # Remove only the reserved kart — the kart the team deposited stays in reserve
        for lane_list in self.state.pit_lanes.values():
            for entry in list(lane_list):
                if entry.reserved_for_bib == pit_stop.bib:
                    lane_list.remove(entry)
                    break

        if assigned:
            self.state.kart_assignments[driver_id] = assigned
            logger.info("PIT OUT: team=%s new_kart=%s duration=%ds",
                        pit_stop.team, assigned, duration_s)
        return assigned

    def set_kart_assignment(self, driver_id: str, kart_label: str, physical_kart_id: int = 0):
        """Manual assignment: operator tells us which physical kart a team is using."""
        self.state.kart_assignments[driver_id] = kart_label
        logger.info("Manual kart assignment: driver=%s kart=%s", driver_id, kart_label)

    def init_reserve(self, karts: list[tuple[str, int]]) -> None:
        """
        Populate the initial reserve pool at race start.
        karts: list of (kart_label, physical_kart_id), distributed round-robin across lanes.
        entered_at is offset by 1 ms per kart so the oldest is always deterministic.
        """
        self._ensure_lanes()
        base = datetime.now(timezone.utc)
        n = len(karts)
        for i, (label, kart_id) in enumerate(karts):
            lane = (i % self.config.num_lanes) + 1
            # Offset by 1 ms per kart so kart 0 is always the oldest (deterministic FIFO)
            entry = PitQueueKart(
                kart_label=label,
                physical_kart_id=kart_id,
                lane=lane,
                entered_at=base - timedelta(milliseconds=(n - i)),
            )
            self.state.pit_lanes[lane].append(entry)
        logger.info("Reserve pool initialised: %d karts across %d lanes",
                    len(karts), self.config.num_lanes)

    def add_kart_to_reserve(self, kart_label: str, lane: int, physical_kart_id: int = 0):
        """Manually add a kart to a specific lane reserve (initial setup)."""
        self._ensure_lanes()
        entry = PitQueueKart(
            kart_label=kart_label,
            physical_kart_id=physical_kart_id,
            lane=lane,
        )
        self.state.pit_lanes[lane].append(entry)

    def remove_kart_from_reserve(self, kart_label: str):
        """Remove a kart from the reserve (e.g. it was used)."""
        for lane_list in self.state.pit_lanes.values():
            for entry in lane_list:
                if entry.kart_label == kart_label and entry.exited_at is None:
                    entry.exited_at = datetime.now(timezone.utc)
                    lane_list.remove(entry)
                    return

    def pit_lanes_snapshot(self) -> list[dict]:
        """Current state of all lanes for the frontend."""
        self._ensure_lanes()
        result = []
        for lane_num in range(1, self.config.num_lanes + 1):
            karts = []
            for entry in self.state.pit_lanes.get(lane_num, []):
                karts.append({
                    "kart_label": entry.kart_label,
                    "physical_kart_id": entry.physical_kart_id,
                    "seconds_in_pit": entry.seconds_in_pit,
                    "is_eligible": True,
                    "from_bib": entry.from_bib,
                    "is_placeholder": entry.is_placeholder,
                    "reserved_for_bib": entry.reserved_for_bib,
                })
            result.append({"lane": lane_num, "karts": karts})
        return result

    def _least_loaded_lane(self) -> int:
        """Lane with fewest team-dropped karts (initial reserve karts are not counted)."""
        min_load = float("inf")
        best_lane = 1
        for lane_num in range(1, self.config.num_lanes + 1):
            load = sum(1 for k in self.state.pit_lanes.get(lane_num, []) if k.from_team)
            if load < min_load:
                min_load = load
                best_lane = lane_num
        return best_lane

    def _reserve_oldest_kart(self, for_bib: str) -> Optional[str]:
        """Mark the oldest available real kart as reserved for for_bib. Does NOT remove it from
        the queue — it stays visible so the UI shows which team it belongs to.
        The kart is physically removed in on_team_exited_pits.
        Eligibility timer is for display only and does not block pre-assignment.
        """
        oldest_entry = None

        for karts in self.state.pit_lanes.values():
            for entry in karts:
                if entry.reserved_for_bib:
                    continue
                if oldest_entry is None or entry.entered_at < oldest_entry.entered_at:
                    oldest_entry = entry

        if oldest_entry:
            oldest_entry.reserved_for_bib = for_bib
            return oldest_entry.kart_label

        return None

    def _kart_id_for_label(self, label: str) -> int:
        # In-memory only; DB persistence handled by api layer
        return 0
