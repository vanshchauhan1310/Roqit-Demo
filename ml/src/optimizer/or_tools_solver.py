"""OR-Tools based multi-vehicle pickup-delivery route optimizer.

Unifies:
- Time windows + lateness (our work)
- Multi-objective cost (duration + distance + fuel + load + lateness)
- Multi-vehicle (OR-Tools native)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from src.optimizer import opt


Matrix = list[list[float]]


@dataclass
class Vehicle:
    vehicle_id: str
    capacity_kg: float
    start_location: int
    avg_kmpl_rated: float = 8.5
    fuel_price_per_l: float = 92.5
    duty_start: int | None = None
    duty_end: int | None = None


@dataclass
class CostWeights:
    alpha: float = 0.4   # duration weight
    delta: float = 0.2   # distance weight
    beta: float = 0.3    # fuel weight
    gamma: float = 0.1   # load (ton-km) weight
    lateness_weight: float = 60.0  # lateness penalty per second


@dataclass
class OrToolsSolveResult:
    routes: dict[str, list[int]]  # vehicle_id -> list of stop indices
    total_duration_seconds: float
    total_distance_meters: float
    total_lateness_seconds: float
    total_fuel_cost_rupees: float
    total_load_ton_km: float
    feasible: bool
    solver_used: Literal["or_tools", "fallback"] = "or_tools"
    objective_value: float = 0.0


class OrToolsSolver:
    """Multi-vehicle pickup-delivery solver using OR-Tools."""

    def __init__(
        self,
        jobs: list[opt.Job],
        vehicles: list[Vehicle],
        duration_matrix: Matrix,
        distance_matrix: Matrix,
        coordinates: list[tuple[float, float]],
        start_time: int,
        cost_weights: CostWeights | None = None,
        time_limit_seconds: int = 10,
    ):
        self.jobs = jobs
        self.vehicles = vehicles
        self.duration_matrix = duration_matrix
        self.distance_matrix = distance_matrix
        self.coordinates = coordinates
        self.start_time = start_time
        self.cost_weights = cost_weights or CostWeights()
        self.time_limit_seconds = time_limit_seconds

        self.num_locations = len(duration_matrix)
        self.num_vehicles = len(vehicles)
        self.manager = None
        self.routing = None
        self.solution = None

        self._job_by_pickup: dict[int, opt.Job] = {}
        self._job_by_delivery: dict[int, opt.Job] = {}
        for job in jobs:
            self._job_by_pickup[job.pickup_idx] = job
            self._job_by_delivery[job.delivery_idx] = job

        self._all_stop_indices = set()
        for job in jobs:
            self._all_stop_indices.add(job.pickup_idx)
            self._all_stop_indices.add(job.delivery_idx)

        self._vehicle_starts = [v.start_location for v in vehicles]
        self._vehicle_ends = [v.start_location for v in vehicles]
        self._vehicle_capacities = [int(v.capacity_kg) for v in vehicles]

    def solve(self) -> OrToolsSolveResult:
        """Build and solve the OR-Tools model."""
        self._build_model()
        self._solve()
        return self._extract_result()

    def _build_model(self) -> None:
        """Build the OR-Tools routing model with all constraints and costs."""
        self.manager = pywrapcp.RoutingIndexManager(
            self.num_locations,
            self.num_vehicles,
            self._vehicle_starts,
            self._vehicle_ends,
        )
        self.routing = pywrapcp.RoutingModel(self.manager)

        # Register transit callbacks
        duration_callback_idx = self.routing.RegisterTransitCallback(self._duration_callback)
        distance_callback_idx = self.routing.RegisterTransitCallback(self._distance_callback)

        # Set arc cost (base: duration)
        self.routing.SetArcCostEvaluatorOfAllVehicles(duration_callback_idx)

        # Add capacity dimension (peak-load aware)
        self._add_capacity_dimension()

        # Add time dimension with soft time windows
        time_callback_idx = self.routing.RegisterTransitCallback(self._time_callback)
        self._add_time_dimension(time_callback_idx)

        # Add pickup-delivery constraints
        self._add_pickup_delivery_constraints()

        # Set multi-objective cost function
        self._set_cost_function(duration_callback_idx, distance_callback_idx)

        # Set search parameters
        self._search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        self._search_parameters.time_limit.seconds = self.time_limit_seconds
        self._search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        )
        self._search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        self._search_parameters.log_search = False

    def _duration_callback(self, from_index: int, to_index: int) -> int:
        from_node = self.manager.IndexToNode(from_index)
        to_node = self.manager.IndexToNode(to_index)
        return int(self.duration_matrix[from_node][to_node])

    def _distance_callback(self, from_index: int, to_index: int) -> int:
        from_node = self.manager.IndexToNode(from_index)
        to_node = self.manager.IndexToNode(to_index)
        return int(self.distance_matrix[from_node][to_node])

    def _time_callback(self, from_index: int, to_index: int) -> int:
        from_node = self.manager.IndexToNode(from_index)
        to_node = self.manager.IndexToNode(to_index)
        travel_time = int(self.duration_matrix[from_node][to_node])
        service_time = 0
        if from_node in self._job_by_pickup:
            service_time = self._job_by_pickup[from_node].service_time_sec
        elif from_node in self._job_by_delivery:
            service_time = self._job_by_delivery[from_node].service_time_sec
        return travel_time + service_time

    def _add_capacity_dimension(self) -> None:
        """Add capacity dimension with per-vehicle capacity (peak-load correct)."""
        def demand_callback(from_index: int) -> int:
            node = self.manager.IndexToNode(from_index)
            if node in self._job_by_pickup:
                return int(self._job_by_pickup[node].load_weight_kg)
            if node in self._job_by_delivery:
                return -int(self._job_by_delivery[node].load_weight_kg)
            return 0

        demand_callback_idx = self.routing.RegisterUnaryTransitCallback(demand_callback)
        self.routing.AddDimensionWithVehicleCapacity(
            demand_callback_idx,
            0,  # null capacity slack
            self._vehicle_capacities,  # vehicle capacities array
            True,  # start cumul to zero
            "Capacity",
        )

    def _add_time_dimension(self, time_callback_idx: int) -> None:
        """Add time dimension with soft time windows."""
        # Use a large horizon to accommodate absolute timestamps (e.g., Unix epoch)
        # Max timestamp ~ year 2030 = 1893456000, so 2e9 is safe
        horizon = 2_000_000_000

        self.routing.AddDimension(
            time_callback_idx,
            horizon,  # waiting time slack
            horizon,  # maximum time per vehicle
            False,  # don't force start cumul to zero (use start_time)
            "Time",
        )
        time_dimension = self.routing.GetDimensionOrDie("Time")

        # Set start time for each vehicle
        for v_idx in range(self.num_vehicles):
            start_index = self.routing.Start(v_idx)
            time_dimension.CumulVar(start_index).SetValue(self.start_time)

        # Add soft time windows for pickup/delivery stops
        for job in self.jobs:
            for node_idx, earliest, latest in [
                (job.pickup_idx, job.pickup_earliest, job.pickup_latest),
                (job.delivery_idx, job.delivery_earliest, job.delivery_latest),
            ]:
                if earliest is not None and latest is not None:
                    index = self.manager.NodeToIndex(node_idx)
                    # Soft upper bound with lateness penalty
                    time_dimension.CumulVar(index).SetMax(latest)
                    # Note: OR-Tools soft bounds need SetCumulVarSoftUpperBound
                    # but we use penalty cost in objective instead for more control

    def _add_pickup_delivery_constraints(self) -> None:
        """Add pickup-delivery pairing constraints."""
        for job in self.jobs:
            pickup_index = self.manager.NodeToIndex(job.pickup_idx)
            delivery_index = self.manager.NodeToIndex(job.delivery_idx)
            self.routing.AddPickupAndDelivery(pickup_index, delivery_index)
            # Pickup and delivery must be on same vehicle
            self.routing.solver().Add(
                self.routing.VehicleVar(pickup_index) == self.routing.VehicleVar(delivery_index)
            )
            # Pickup before delivery
            time_dimension = self.routing.GetDimensionOrDie("Time")
            self.routing.solver().Add(
                time_dimension.CumulVar(pickup_index) <= time_dimension.CumulVar(delivery_index)
            )

    def _set_cost_function(
        self,
        duration_callback_idx: int,
        distance_callback_idx: int,
    ) -> None:
        """Set the multi-objective arc cost: alpha*duration + delta*distance + beta*fuel + gamma*load + lateness."""

        def cost_callback(from_index: int, to_index: int) -> int:
            from_node = self.manager.IndexToNode(from_index)
            to_node = self.manager.IndexToNode(to_index)

            duration = self.duration_matrix[from_node][to_node]
            distance = self.distance_matrix[from_node][to_node]

            # Fuel cost approximation (Phase 1: avg-load)
            # fuel_liters = distance_km / (avg_kmpl * load_factor)
            # Using average load factor of 0.5 for approximation
            avg_load_factor = 0.5
            distance_km = distance / 1000.0
            # Average vehicle specs
            avg_kmpl = sum(v.avg_kmpl_rated for v in self.vehicles) / len(self.vehicles)
            avg_fuel_price = sum(v.fuel_price_per_l for v in self.vehicles) / len(self.vehicles)
            fuel_liters = distance_km / (avg_kmpl * avg_load_factor) if avg_kmpl > 0 else 0
            fuel_cost = fuel_liters * avg_fuel_price

            # Load ton-km (using average load approximation)
            avg_load_kg = sum(j.load_weight_kg for j in self.jobs) / len(self.jobs) if self.jobs else 0
            load_ton_km = (avg_load_kg / 1000.0) * distance_km

            cw = self.cost_weights
            cost = (
                cw.alpha * duration
                + cw.delta * distance
                + cw.beta * fuel_cost
                + cw.gamma * load_ton_km * 1000  # scale to match other terms
            )
            return int(cost)

        cost_callback_idx = self.routing.RegisterTransitCallback(cost_callback)
        self.routing.SetArcCostEvaluatorOfAllVehicles(cost_callback_idx)

        # Add lateness penalties via time dimension soft bounds
        time_dimension = self.routing.GetDimensionOrDie("Time")
        for job in self.jobs:
            for node_idx, latest in [
                (job.pickup_idx, job.pickup_latest),
                (job.delivery_idx, job.delivery_latest),
            ]:
                if latest is not None:
                    index = self.manager.NodeToIndex(node_idx)
                    # Penalty per second of lateness
                    time_dimension.SetCumulVarSoftUpperBound(index, latest, int(self.cost_weights.lateness_weight))

    def _solve(self) -> None:
        """Solve the model."""
        self.solution = self.routing.SolveWithParameters(self._search_parameters)

    def _extract_result(self) -> OrToolsSolveResult:
        """Extract solution from OR-Tools."""
        if not self.solution:
            return OrToolsSolveResult(
                routes={},
                total_duration_seconds=0.0,
                total_distance_meters=0.0,
                total_lateness_seconds=0.0,
                total_fuel_cost_rupees=0.0,
                total_load_ton_km=0.0,
                feasible=False,
                solver_used="or_tools",
            )

        routes = {}
        total_duration = 0.0
        total_distance = 0.0
        total_lateness = 0.0
        total_fuel_cost = 0.0
        total_load_ton_km = 0.0

        time_dimension = self.routing.GetDimensionOrDie("Time")

        # Depot nodes are the start/end locations for each vehicle
        depot_nodes = set(self._vehicle_starts)

        for v_idx, vehicle in enumerate(self.vehicles):
            route_stops = []
            index = self.routing.Start(v_idx)
            prev_node = None

            while not self.routing.IsEnd(index):
                node = self.manager.IndexToNode(index)
                # Skip depot nodes in the returned route
                if node not in depot_nodes:
                    route_stops.append(node)
                if prev_node is not None:
                    total_duration += self.duration_matrix[prev_node][node]
                    total_distance += self.distance_matrix[prev_node][node]

                    # Fuel and load-ton-km calculation
                    distance_km = self.distance_matrix[prev_node][node] / 1000.0
                    avg_load_kg = sum(j.load_weight_kg for j in self.jobs) / len(self.jobs) if self.jobs else 0
                    total_load_ton_km += (avg_load_kg / 1000.0) * distance_km
                    fuel_liters = distance_km / (vehicle.avg_kmpl_rated * 0.5) if vehicle.avg_kmpl_rated > 0 else 0
                    total_fuel_cost += fuel_liters * vehicle.fuel_price_per_l

                prev_node = node
                index = self.solution.Value(self.routing.NextVar(index))

            # Add return to depot
            end_node = self.manager.IndexToNode(index)
            if prev_node is not None:
                total_duration += self.duration_matrix[prev_node][end_node]
                total_distance += self.distance_matrix[prev_node][end_node]

            routes[vehicle.vehicle_id] = route_stops

            # Calculate lateness for this vehicle's route
            lateness = self._calculate_route_lateness(route_stops)
            total_lateness += lateness

        return OrToolsSolveResult(
            routes=routes,
            total_duration_seconds=total_duration,
            total_distance_meters=total_distance,
            total_lateness_seconds=total_lateness,
            total_fuel_cost_rupees=total_fuel_cost,
            total_load_ton_km=total_load_ton_km,
            feasible=True,
            solver_used="or_tools",
            objective_value=self.solution.ObjectiveValue(),
        )

    def _calculate_route_lateness(self, route: list[int]) -> float:
        """Calculate total lateness for a route (excluding depot nodes)."""
        if not route:
            return 0.0
        
        # Start from depot
        current_time = self.start_time
        total_lateness = 0.0
        depot_node = self._vehicle_starts[0]  # All vehicles share same depot in our case
        
        # Travel from depot to first stop
        current_time += self.duration_matrix[depot_node][route[0]]

        for i, stop_idx in enumerate(route):
            job = self._job_by_pickup.get(stop_idx) or self._job_by_delivery.get(stop_idx)
            if job is None:
                continue

            is_pickup = stop_idx == job.pickup_idx
            earliest = job.pickup_earliest if is_pickup else job.delivery_earliest
            latest = job.pickup_latest if is_pickup else job.delivery_latest

            if earliest is not None and latest is not None:
                if current_time < earliest:
                    current_time = earliest
                elif current_time > latest:
                    total_lateness += current_time - latest

            current_time += job.service_time_sec
            if i + 1 < len(route):
                current_time += self.duration_matrix[stop_idx][route[i + 1]]

        return total_lateness


def solve_with_or_tools(
    jobs: list[opt.Job],
    vehicles: list[Vehicle],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    coordinates: list[tuple[float, float]],
    start_time: int,
    cost_weights: CostWeights | None = None,
    time_limit_seconds: int = 10,
) -> OrToolsSolveResult:
    """High-level function to solve with OR-Tools."""
    solver = OrToolsSolver(
        jobs=jobs,
        vehicles=vehicles,
        duration_matrix=duration_matrix,
        distance_matrix=distance_matrix,
        coordinates=coordinates,
        start_time=start_time,
        cost_weights=cost_weights,
        time_limit_seconds=time_limit_seconds,
    )
    return solver.solve()


def solve_with_fallback(
    jobs: list[opt.Job],
    vehicles: list[Vehicle],
    duration_matrix: Matrix,
    distance_matrix: Matrix,
    coordinates: list[tuple[float, float]],
    start_time: int,
    cost_weights: CostWeights | None = None,
    time_limit_seconds: int = 10,
) -> OrToolsSolveResult:
    """Try OR-Tools first, fall back to hybrid_solver if it fails."""
    from src.optimizer.hybrid_solver import hybrid_solve

    # Try OR-Tools
    result = solve_with_or_tools(
        jobs=jobs,
        vehicles=vehicles,
        duration_matrix=duration_matrix,
        distance_matrix=distance_matrix,
        coordinates=coordinates,
        start_time=start_time,
        cost_weights=cost_weights,
        time_limit_seconds=time_limit_seconds,
    )

    if result.feasible:
        return result

    # Fallback: use hybrid_solver (single vehicle only for now)
    # Pick the vehicle with largest capacity
    if not vehicles:
        return result

    primary_vehicle = max(vehicles, key=lambda v: v.capacity_kg)

    # Convert coordinates to list of tuples for hybrid_solve
    coord_tuples = [tuple(c) for c in coordinates]

    fallback_result = hybrid_solve(
        jobs=jobs,
        duration_matrix=duration_matrix,
        distance_matrix=distance_matrix,
        coordinates=coord_tuples,
        vehicle_capacity_kg=primary_vehicle.capacity_kg,
        start_time=start_time,
    )

    # Convert to OrToolsSolveResult format
    routes = {primary_vehicle.vehicle_id: fallback_result.route}
    return OrToolsSolveResult(
        routes=routes,
        total_duration_seconds=fallback_result.total_duration_seconds,
        total_distance_meters=fallback_result.total_distance_meters,
        total_lateness_seconds=fallback_result.total_lateness_seconds,
        total_fuel_cost_rupees=0.0,  # Not computed in fallback
        total_load_ton_km=0.0,  # Not computed in fallback
        feasible=fallback_result.feasible,
        solver_used="fallback",
        objective_value=0.0,
    )