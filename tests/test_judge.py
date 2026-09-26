import pytest

from good_cop import judge


def test_parse_variants():
    assert judge.parse('{"a": 0.3, "b": 1.5}', ["a", "b"]) == {"a": 0.3, "b": 1.0}
    assert judge.parse('Sure!\n```json\n{"a": "0.9", "b": true}\n```', ["a", "b"]) == {"a": 0.9, "b": 1.0}
    assert judge.parse('{"a": {"p": 0.2}, "zzz": 1}', ["a", "b"]) == {"a": 0.2}


def test_parse_garbage():
    with pytest.raises(ValueError):
        judge.parse("no idea", ["a"])


def test_prompt_lists_ids():
    p = judge.prompt({"call": {}}, {"a": "Is it A?", "b": "Is it B?"})
    assert '"a": Is it A?' in p and '{"a": 0.0, "b": 0.0}' in p
