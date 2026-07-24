# tests/test_dispatch_agent.py
# Ported test pattern from AgAI-7's test_availability.py -- validates the
# core ranking logic in dispatch_agent.py without requiring a live Supabase
# connection or a real Asterisk instance.

import pytest

from core.models import Technician, TechnicianStatus, ServiceType
from agents.dispatch_agent import _score_technician, _haversine_km, _rank_technicians


def _make_technician(
    tech_id: str,
    queue_depth: int = 0,
    lat: float | None = None,
    lng: float | None = None,
) -> Technician:
    return Technician(
        technician_id=tech_id,
        name=f"Tech {tech_id}",
        phone="+15550000000",
        skills=[ServiceType.HVAC],
        status=TechnicianStatus.AVAILABLE,
        current_lat=lat,
        current_lng=lng,
        current_queue_depth=queue_depth,
    )


def test_haversine_zero_distance():
    """Same point should be zero distance."""
    dist = _haversine_km(33.4484, -112.0740, 33.4484, -112.0740)
    assert dist == pytest.approx(0.0, abs=0.01)


def test_haversine_known_distance():
    """Phoenix to Tucson is roughly 180km -- sanity check the formula, not
    an exact assertion since real-world routing distance differs from
    great-circle distance."""
    dist = _haversine_km(33.4484, -112.0740, 32.2226, -110.9747)
    assert 150 < dist < 210


def test_score_technician_closer_wins_when_queue_equal():
    """With equal queue depth, the closer technician should score higher."""
    near = _score_technician(_make_technician("near", queue_depth=1), distance_km=2.0)
    far = _score_technician(_make_technician("far", queue_depth=1), distance_km=20.0)
    assert near > far


def test_score_technician_lighter_queue_wins_when_distance_equal():
    """With equal distance, the technician with a lighter queue should score higher."""
    light = _score_technician(_make_technician("light", queue_depth=0), distance_km=5.0)
    heavy = _score_technician(_make_technician("heavy", queue_depth=4), distance_km=5.0)
    assert light > heavy


def test_score_technician_unknown_distance_is_neutral_not_zero():
    """A technician with no distance data should not be penalized to zero --
    this is the specific behavior that prevents unfairly excluding
    technicians when geocoding fails (see dispatch_agent.py docstring)."""
    unknown_distance = _score_technician(_make_technician("t1", queue_depth=0), distance_km=None)
    worst_known_distance = _score_technician(_make_technician("t2", queue_depth=0), distance_km=25.0)
    assert unknown_distance > worst_known_distance


@pytest.mark.asyncio
async def test_rank_technicians_returns_sorted_by_score():
    """Ranked output should be sorted best-first."""
    technicians = [
        _make_technician("far", queue_depth=0, lat=33.0, lng=-112.5),
        _make_technician("near", queue_depth=0, lat=33.45, lng=-112.08),
    ]
    customer_coords = (33.4484, -112.0740)

    ranked = await _rank_technicians(technicians, customer_coords)

    assert ranked[0].technician.technician_id == "near"
