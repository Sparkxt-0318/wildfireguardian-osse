"""Mission semantics: the three the placeholder adapter actually implements."""

from __future__ import annotations

import numpy as np
import pytest

from wildfireguardian_osse.landscape.grid import Grid
from wildfireguardian_osse.missions import (
    DispatchAdapter,
    FailureReason,
    MissionKind,
    PlaceholderDispatchAdapter,
    build_geometry,
    build_road_network,
)
from wildfireguardian_osse.missions.network import Edge, Route
from wildfireguardian_osse.rng import SeedRegistry

GRID = Grid(nx=160, ny=160, cell_size_m=30.0)


def _geometry(wind_dir_deg: float = 0.0):
    return build_geometry(
        GRID, wind_dir_deg=wind_dir_deg,
        rng=SeedRegistry.build(11, 0).generator("nature_seed", "geometry"),
    )


def _eastward_front(reach_x_m: float, speed_m_per_min: float, t0: float = 0.0):
    """Arrival field of a straight front moving east."""
    X, _ = GRID.cell_centres()
    arrival = t0 + (X - reach_x_m) / speed_m_per_min
    return np.maximum(arrival, 0.0)


def test_the_placeholder_satisfies_the_adapter_contract():
    assert isinstance(PlaceholderDispatchAdapter(), DispatchAdapter)


def test_an_edge_is_blocked_when_fire_crosses_it_mid_traversal():
    """The full-traversal-interval rule, which is the point of the adapter.

    The edge is unburned when the vehicle enters, but the fire reaches its far
    end before the vehicle gets there.  A naive "is the edge clear at entry?"
    check would call this passable.
    """
    adapter = PlaceholderDispatchAdapter(speed_m_per_min=60.0, self_evac_prep_min=0.0)
    edge = Edge("e", 700.0, 1200.0, 1900.0, 1200.0)        # 1200 m east, 20 min
    route = Route("r", (edge,))
    # Front is at x = 600 m at t = 0 and moves east at 20 m/min: it reaches the
    # far end at t = 65, while the vehicle gets there at t = 20.  Passable.
    fast_vehicle = _eastward_front(reach_x_m=600.0, speed_m_per_min=20.0)
    completed, _, _, _ = adapter.traverse(route, 0.0, fast_vehicle, GRID)
    assert completed

    # Same geometry, vehicle four times slower: it now needs 80 min and the
    # fire crosses the edge underneath it.
    slow = PlaceholderDispatchAdapter(speed_m_per_min=15.0, self_evac_prep_min=0.0)
    completed, _, blocked_edge, _ = slow.traverse(route, 0.0, fast_vehicle, GRID)
    assert not completed
    assert blocked_edge == "e"


def test_entry_time_alone_is_not_enough():
    """Explicitly contrast the correct rule with the naive one."""
    adapter = PlaceholderDispatchAdapter(speed_m_per_min=20.0, self_evac_prep_min=0.0)
    edge = Edge("e", 900.0, 900.0, 2400.0, 900.0)
    route = Route("r", (edge,))
    arrival = _eastward_front(reach_x_m=700.0, speed_m_per_min=25.0)
    rows, cols, _ = edge.sample_cells(GRID)
    assert float(arrival[rows, cols].min()) > 0.0, "the edge is clear at entry"
    completed, _, _, _ = adapter.traverse(route, 0.0, arrival, GRID)
    assert not completed, "but the fire overtakes the vehicle part-way along"


def test_feasible_dispatch_windows_can_be_non_monotone():
    """Waiting can *reopen* a window, not only close one.

    The property the experiment depends on: feasibility is not a step function
    of the order time, so 'act as early as possible' is not trivially optimal.
    """
    adapter = PlaceholderDispatchAdapter(
        speed_m_per_min=90.0, self_evac_prep_min=0.0, road_blockage_duration_min=30.0
    )
    edge = Edge("e", 300.0, 2400.0, 2700.0, 2400.0)
    route = Route("r", (edge,))
    # A front sweeping east across the road: each cell is impassable for 30 min
    # after the front reaches it, and passable again afterwards.
    arrival = _eastward_front(reach_x_m=300.0, speed_m_per_min=20.0)

    feasible = [
        adapter.traverse(route, float(t), arrival, GRID)[0] for t in range(0, 240, 5)
    ]
    assert any(feasible) and not all(feasible)
    transitions = sum(1 for a, b in zip(feasible, feasible[1:]) if a != b)
    assert transitions >= 2, (
        f"expected the window to close and reopen, got {feasible}"
    )


def test_pickup_duration_can_lose_the_mission():
    """The dwell at the village is a real exposure, not a free operation."""
    geometry = _geometry()
    grid = geometry.grid
    vi, vj = grid.xy_to_ij(*geometry.village_xy_m)
    arrival = np.full(grid.shape, np.inf)

    quick = PlaceholderDispatchAdapter(pickup_duration_min=1.0, responder_dispatch_min=0.0)
    slow = PlaceholderDispatchAdapter(pickup_duration_min=45.0, responder_dispatch_min=0.0)
    approach_time = geometry.network.approach_route.length_m / quick.speed_m_per_min
    # Fire reaches the village just after the responder arrives.
    arrival[vi, vj] = approach_time + 20.0

    route = geometry.network.route("route_direct")
    ok = quick.evaluate_assisted(
        order_time_min=0.0, approach=geometry.network.approach_route, route=route,
        arrival_time_min=arrival, grid=grid, horizon_min=400.0,
    )
    lost = slow.evaluate_assisted(
        order_time_min=0.0, approach=geometry.network.approach_route, route=route,
        arrival_time_min=arrival, grid=grid, horizon_min=400.0,
    )
    assert ok.feasible
    assert not lost.feasible
    assert lost.failure_reason is FailureReason.VILLAGE_BURNED_BEFORE_PICKUP


def test_responder_exposure_is_counted_only_near_burning_ground():
    geometry = _geometry()
    adapter = PlaceholderDispatchAdapter()
    clear = np.full(geometry.grid.shape, np.inf)
    burning = np.zeros(geometry.grid.shape)

    route = geometry.network.approach_route
    none = adapter.exposure_minutes(route, 0.0, 30.0, clear, geometry.grid)
    lots = adapter.exposure_minutes(route, 0.0, 30.0, burning, geometry.grid)
    assert none == 0.0
    assert lots > 20.0


def test_self_evacuation_reports_no_responder_exposure():
    geometry = _geometry()
    adapter = PlaceholderDispatchAdapter()
    result = adapter.evaluate_self_evacuation(
        order_time_min=0.0, route=geometry.network.route("route_direct"),
        arrival_time_min=np.full(geometry.grid.shape, np.inf),
        grid=geometry.grid, horizon_min=400.0,
    )
    assert result.feasible
    assert result.responder_exposure_min == 0.0
    assert result.kind is MissionKind.SELF_EVACUATION


def test_horizon_exceeded_is_distinguished_from_being_cut_off():
    geometry = _geometry()
    adapter = PlaceholderDispatchAdapter()
    result = adapter.evaluate_self_evacuation(
        order_time_min=0.0, route=geometry.network.route("route_detour"),
        arrival_time_min=np.full(geometry.grid.shape, np.inf),
        grid=geometry.grid, horizon_min=1.0,
    )
    assert not result.feasible
    assert result.failure_reason is FailureReason.HORIZON_EXCEEDED


def test_the_two_routes_differ_in_length_and_exposure():
    geometry = _geometry()
    direct = geometry.network.route("route_direct")
    detour = geometry.network.route("route_detour")
    assert detour.length_m > direct.length_m
    assert direct.route_id != detour.route_id


def test_ignition_is_placed_upwind_of_the_village():
    for wind_dir_deg in (0.0, 90.0, 180.0, 270.0):
        geometry = _geometry(wind_dir_deg)
        vx, vy = geometry.village_xy_m
        ix, iy = geometry.ignition_xy_m
        # Vector from ignition to village should point broadly downwind.
        to_village = np.array([vx - ix, vy - iy])
        wind = np.array([np.cos(np.deg2rad(wind_dir_deg)), np.sin(np.deg2rad(wind_dir_deg))])
        cosine = float(to_village @ wind / np.linalg.norm(to_village))
        assert cosine > 0.5, f"ignition is not upwind for wind {wind_dir_deg}"


def test_network_rejects_missing_nodes():
    with pytest.raises(ValueError, match="missing node"):
        build_road_network({"village": (0.0, 0.0)})
