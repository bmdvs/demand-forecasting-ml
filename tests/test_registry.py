"""Promotion decisions and tag keys with a stubbed registry, and the selection rule's pick."""
import pytest

from dfm import registry as R
from dfm import tasks


class Stub:
    def __init__(self):
        self.tags, self.alias, self.versions = {}, {}, {}

    def set_tag(self, name, version, key, value):
        self.tags[(version, key)] = value

    def delete_tag(self, name, version, key):
        self.tags.pop((version, key), None)

    def set_alias(self, name, alias, version):
        self.alias[alias] = version

    def alias_version(self, name, alias):
        return self.alias.get(alias)

    def find_version(self, name, run_id):
        return self.versions.get(run_id)

    def register(self, run_id, name):
        self.versions[run_id] = str(len(self.versions) + 1)
        return self.versions[run_id]


def test_tag_keys_reject_reserved_characters():
    for bad in ["gate.selection", "a=b", "x>y", "p%", "q?", "back\\slash"]:
        with pytest.raises(ValueError):
            R.tag_key(bad)
    assert R.tag_key("gate_selection_detail") == "gate_selection_detail"


def test_tag_values_within_length_limit():
    s = Stub()
    long = R.Gate("bias", False, "x" * 400, {"bias_months_scored": "y" * 300})
    R.decide(s, "m", "1", [long], True)
    assert all(len(v) <= R.TAG_VALUE_MAX for v in s.tags.values())
    assert s.tags[("1", "gate_bias_detail")].endswith("...") and R.tag_value("short") == "short"


def test_decide_moves_champion_only_when_all_pass_and_allowed():
    ok = [R.Gate("selection", True, "d"), R.Gate("bias", True, "d", {"bias_month": "2025-06"})]
    s = Stub()
    assert R.decide(s, "m", "1", ok, auto_promote=False) == "for_review" and "champion" not in s.alias
    assert R.decide(s, "m", "1", ok, auto_promote=True) == "promoted" and s.alias["champion"] == "1"
    bad = ok + [R.Gate("parity", False, "d")]
    assert R.decide(s, "m", "2", bad, auto_promote=True) == "rejected" and s.alias["champion"] == "1"
    assert s.tags[("2", "failed_gates")] == "parity" and s.tags[("1", "bias_month")] == "2025-06"


def test_register_or_reuse_on_repair():
    s = Stub()
    assert R.register_or_reuse(s, "run-a", "m") == ("1", False)
    assert R.register_or_reuse(s, "run-a", "m") == ("1", True)


def _rung(n, val, winner):
    c = {k: {"val_wape": v} for k, v in val.items()}
    return {"n_features": n, "winner": winner, "candidates": c}


def test_selection_pick_rules():
    results = {"reference": _rung(20, {"Linear": 0.8, "RandomForest": 0.50, "XGBoost": 0.52}, "RandomForest"),
               "S1": _rung(26, {"Linear": 0.7, "RandomForest": 0.45, "XGBoost": 0.47}, "RandomForest")}
    assert tasks.selection_pick(results) == ("S1", "RandomForest")
    # a rung within 0.3 points of a smaller feature set loses to the smaller set
    results["S1"] = _rung(26, {"Linear": 0.7, "RandomForest": 0.498, "XGBoost": 0.52}, "RandomForest")
    assert tasks.selection_pick(results) == ("reference", "RandomForest")
    # the booster wins a tie within 0.5 points; a logged winner against the rule picks nothing
    results["S1"] = _rung(26, {"Linear": 0.7, "RandomForest": 0.45, "XGBoost": 0.454}, "RandomForest")
    assert tasks.selection_pick(results) == ("", "")
