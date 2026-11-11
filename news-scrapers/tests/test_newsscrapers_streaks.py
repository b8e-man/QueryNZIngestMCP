"""Ruling 211 (C075): a news source reddens the sweep only after three
consecutive failures of that same source; one transient is a ledger line;
a success resets the streak; state survives a run."""
import json

from newsscrapers import streaks


def test_one_transient_does_not_redden():
    s = {}
    assert streaks.record(s, "ecan.govt.nz", failed=True) == (1, False)
    assert streaks.record(s, "crux.org.nz", failed=True) == (1, False)


def test_third_consecutive_failure_reddens():
    s = {}
    streaks.record(s, "ecan.govt.nz", failed=True)
    streaks.record(s, "ecan.govt.nz", failed=True)
    assert streaks.record(s, "ecan.govt.nz", failed=True) == (3, True)
    # and stays red while it keeps failing
    assert streaks.record(s, "ecan.govt.nz", failed=True) == (4, True)


def test_success_resets_the_streak():
    s = {"ecan.govt.nz": 2}
    assert streaks.record(s, "ecan.govt.nz", failed=False) == (0, False)
    assert "ecan.govt.nz" not in s
    # two failures, a success, two failures: never three in a row
    for f in (True, True, False, True, True):
        _, red = streaks.record(s, "ecan.govt.nz", failed=f)
    assert red is False


def test_state_round_trip_and_ledger(tmp_path):
    p = tmp_path / "streaks.json"
    assert streaks.load(p) == {}                     # absent file = no streaks
    streaks.save({"a": 2, "b": 0, "c": 1}, p)
    assert streaks.load(p) == {"a": 2, "c": 1}        # zeros dropped
    p.write_text("not json")
    assert streaks.load(p) == {}                     # corrupt file = no streaks, never a crash
    led = tmp_path / "t.jsonl"
    streaks.ledger("a", 3, True, "ReadTimeout: x" * 50, path=led)
    row = json.loads(led.read_text().splitlines()[0])
    assert row["source"] == "a" and row["streak"] == 3 and row["reddens"] is True
    assert row["rule"] == "ruling-211-consecutive-failures" and len(row["error"]) <= 300
