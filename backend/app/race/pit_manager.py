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
from datetime import datetime, timezone
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
        """Called when a team's pit count increases (detected from c13 update)."""
        self._ensure_lanes()

        current_kart = self.state.kart_assignments.get(driver.driver_id, "?")
        pit_stop = LivePitStop(
            driver_id=driver.driver_id,
            kart_label=current_kart,
            team=driver.team,
            bib=driver.kart,
            position=driver.position,
            lap=driver.laps,
            pit_number=driver.pits,
        )

        # Add the inbound kart to the least-loaded lane
        if current_kart and current_kart != "?":
            lane = self._least_loaded_lane()
            kart_id = self._kart_id_for_label(current_kart)
            queue_entry = PitQueueKart(
                kart_label=current_kart,
                physical_kart_id=kart_id,
                lane=lane,
            )
            self.state.pit_lanes[lane].append(queue_entry)
            logger.info("PIT IN: bib=%s kart=%s → lane %d", driver.kart, current_kart, lane)

        self.state.active_pit_stops[driver.driver_id] = pit_stop
        logger.info("PIT STOP detected: team=%s pos=%d pit#=%d", driver.team, driver.position, driver.pits)
        return pit_stop

    def on_team_exited_pits(self, driver_id: str) -> Optional[str]:
        """
        Called when a team is detected back on track.
        Assigns the oldest waiting kart to the team.
        Returns the label of the assigned kart, or None.
        """
        pit_stop = self.state.active_pit_stops.pop(driver_id, None)
        if not pit_stop:
            return None

        assigned = self._assign_oldest_kart(driver_id, self.config.min_pit_duration_s)
        pit_stop.kart_out_label = assigned
        pit_stop.exited_at = datetime.now(timezone.utc)
        self.state.pit_history.append(pit_stop)

        if assigned:
            self.state.kart_assignments[driver_id] = assigned
            logger.info("PIT OUT: team=%s new_kart=%s duration=%ds",
                        pit_stop.team, assigned, pit_stop.duration_s or 0)
        return assigned

    def set_kart_assignment(self, driver_id: str, kart_label: str, physical_kart_id: int = 0):
        """Manual assignment: operator tells us which physical kart a team is using."""
        self.state.kart_assignments[driver_id] = kart_label
        logger.info("Manual kart assignment: driver=%s kart=%s", driver_id, kart_label)

    def init_reserve(self, karts: list[tuple[str, int]]) -> None:
        """
        Populate the initial reserve pool at race start.
        karts: list of (kart_label, physical_kart_id), distributed round-robin across lanes.
        All karts start as UNKNOWN (no performance data yet).
        """
        self._ensure_lanes()
        for i, (label, kart_id) in enumerate(karts):
            lane = (i % self.config.num_lanes) + 1
            entry = PitQueueKart(kart_label=label, physical_kart_id=kart_id, lane=lane)
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
                    "is_eligible": entry.seconds_in_pit >= self.config.min_pit_duration_s,
                })
            result.append({"lane": lane_num, "karts": karts})
        return result

    def _least_loaded_lane(self) -> int:
        min_load = float("inf")
        best_lane = 1
        for lane_num in range(1, self.config.num_lanes + 1):
            load = len(self.state.pit_lanes.get(lane_num, []))
            if load < min_load:
                min_load = load
                best_lane = lane_num
        return best_lane

    def _assign_oldest_kart(self, driver_id: str, min_duration_s: int) -> Optional[str]:
        oldest_entry = None
        oldest_lane = None

        for lane_num, karts in self.state.pit_lanes.items():
            for entry in karts:
                if entry.seconds_in_pit >= min_duration_s:
                    if oldest_entry is None or entry.entered_at < oldest_entry.entered_at:
                        oldest_entry = entry
                        oldest_lane = lane_num

        if oldest_entry and oldest_lane is not None:
            self.state.pit_lanes[oldest_lane].remove(oldest_entry)
            return oldest_entry.kart_label

        return None

    def _kart_id_for_label(self, label: str) -> int:
        # In-memory only; DB persistence handled by api layer
        return 0
