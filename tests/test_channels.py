"""Gauge pairs are defined once, in channels.py."""
from ibl.channels import CHANNELS, LOCATIONS, PAIRS, pair_index


def test_seven_pairs_in_wiring_order():
    assert len(PAIRS) == 7
    assert len(LOCATIONS) == 7
    assert LOCATIONS[0] == "SNICS"


def test_every_pair_is_one_location_ion_then_convectron():
    for location, (ig, cg) in zip(LOCATIONS, PAIRS):
        assert ig.location == cg.location == location
        assert ig.is_ion
        assert not cg.is_ion


def test_pair_index_finds_the_pair_of_every_channel():
    for c in CHANNELS:
        assert c in PAIRS[pair_index(c.ain)]
