"""Tests for simulation generator (P2 regression: no negative depart times)."""
import re

from flowsense.simulation import generator as gen
from flowsense.simulation import sim_config as sc


def _negative_departs():
    src = open(gen.BUILD_DIR + "/routes.rou.xml").read()
    return re.findall(r'depart="(-[0-9.]+)"', src)


def test_build_routes_no_negative_departs_short_duration():
    # Regression guard for the --duration < 120 emergency-vehicle bug.
    sc.SIM_DURATION = 40
    sc.set_traffic_volumes([])
    gen.build_routes("orderly")
    assert _negative_departs() == [], "routes must never have negative depart times"


def test_build_routes_no_negative_departs_normal():
    sc.SIM_DURATION = 3600
    sc.set_traffic_volumes([])
    gen.build_routes("orderly")
    assert _negative_departs() == []
