"""Red-team regression (code rules only, no model calls): each scenario's documented `code_caught`
must still hold. A fix that catches a documented miss should update the scenario file."""
import importlib.util
from pathlib import Path

import pytest

from good_cop import config

ROOT = Path(__file__).parent.parent / "evals" / "redteam"
spec = importlib.util.spec_from_file_location("redteam", ROOT / "run.py")
redteam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redteam)


@pytest.mark.parametrize("path", redteam.scenarios(), ids=lambda p: p.stem)
def test_scenario_code_outcome(home, path):
    r = redteam.evaluate(path, config.load_rules(redteam.RULES), None)
    assert r["calls"], "scenario has no expected calls"
    assert r["caught"] == r["meta"]["code_caught"], r["calls"]
    if not r["caught"]:
        assert r["meta"].get("limit"), "a documented miss needs a `limit` explaining it"


def test_at_least_ten_scenarios():
    assert len(redteam.scenarios()) >= 10
