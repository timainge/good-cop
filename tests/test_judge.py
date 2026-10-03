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


def test_yaml_criteria_keys_are_strings(home):
    from conftest import write_rules
    from good_cop import config
    write_rules(home, "rules:\n  - {id: a, question: 'q?', criteria: {true: it does, false: it does not}}\n")
    r = config.load_rules()["rules"][0]
    assert r["criteria"] == {"true": "it does", "false": "it does not"}
    assert "Yes means: it does" in judge.render({"question": r["question"], "criteria": r["criteria"]})


def test_extract_json_skips_braces_in_prose():
    text = 'The command checks `${ANTHROPIC_API_KEY:+yes}` without printing it.\n{"secret_exposure": 0.05}'
    assert judge.parse(text, ["secret_exposure"]) == {"secret_exposure": 0.05}
