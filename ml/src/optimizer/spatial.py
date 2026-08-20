"""KD-tree spatial pruning for insertion candidates - pure DSA, no learning.

Geometrically, the cheapest place to splice a new stop into a route is
essentially always adjacent to one of the route's physically nearest
existing stops. This module finds those nearest neighbors in O(log n) so
hybrid_solver only has to consider insertion positions next to them,
instead of every position in the route.
"""

from __future__ import annotations

from sklearn.neighbors import KDTree


class RouteSpatialIndex:
    """KD-tree over a route's stop coordinates, at the route's CURRENT length.
    Rebuild a new instance whenever the route changes - this class does not
    support incremental updates."""

    def __init__(self, coordinates: list[tuple[float, float]], route: list[int]) -> None:
        self.route = route
        self._route_points = [coordinates[stop] for stop in route]
        self._tree = KDTree(self._route_points) if route else None

    def nearest_positions(self, point: tuple[float, float], k: int) -> list[int]:
        """Returns up to k positions WITHIN `self.route` (indices 0..len(route)-1,
        not stop ids) whose coordinates are nearest to `point`."""
        if self._tree is None:
            return []
        k = min(k, len(self.route))
        _, indices = self._tree.query([point], k=k)
        return [int(i) for i in indices[0]]


def candidate_insertion_positions(index: RouteSpatialIndex, point: tuple[float, float], k_spatial: int) -> list[int]:
    """For each of the k_spatial route positions nearest to `point`, both
    "insert immediately before" and "insert immediately after" are offered as
    candidate insertion positions (original-route index space, 0..len(route)).
    Always includes the very start/end of the route too, so an empty or
    near-empty route still has valid candidates."""
    route_length = len(index.route)
    positions = {0, route_length}

    for pos in index.nearest_positions(point, k_spatial):
        positions.add(pos)      # insert before this route position
        positions.add(pos + 1)  # insert after this route position

    return sorted(p for p in positions if 0 <= p <= route_length)
