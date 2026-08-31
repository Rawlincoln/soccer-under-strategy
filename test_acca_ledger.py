import json
import tempfile
from pathlib import Path

import acca_ledger
from acca_ledger import _grade_leg, ingest_live_matches, settle_pending


def _leg(**kwargs):
    base = {
        "event_id": "12345678",
        "side": "UNDER",
        "line": 1.5,
        "scope": "fh",
        "result": None,
        "final_fh": "",
        "final_ft": "",
        "goals_used": None,
    }
    base.update(kwargs)
    return base


def test_under_busts_before_ht():
    assert _grade_leg(_leg(), {"fh_goals": 2, "ht_or_later": False, "finished": False}) is False


def test_under_wins_at_ht():
    assert _grade_leg(_leg(), {"fh_goals": 1, "ht_or_later": True, "finished": False, "fh_score": "1-0"}) is True


def test_over_wins_as_soon_as_line_breaks():
    leg = _leg(side="OVER", line=1.5, scope="ft")
    assert _grade_leg(leg, {"ft_goals": 2, "finished": False}) is True


def test_over_loses_when_finished_under_line():
    leg = _leg(side="OVER", line=2.5, scope="ft")
    assert _grade_leg(leg, {"ft_goals": 2, "finished": True}) is False


def test_ingest_and_early_loss_settles_whole_slip():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "ledger.json"
        original = acca_ledger.LEDGER_PATH
        acca_ledger.LEDGER_PATH = ledger
        try:
            data = {
                "snapshots": [{
                    "id": "t1",
                    "status": "pending",
                    "combined_odds": 3.0,
                    "stake": 10,
                    "legs": [
                        _leg(event_id="11111111", side="UNDER", line=1.5, scope="fh"),
                        _leg(event_id="22222222", side="UNDER", line=2.5, scope="ft"),
                    ],
                }],
                "score_cache": {},
            }
            ledger.write_text(json.dumps(data), encoding="utf-8")
            ingest_live_matches([{
                "event_id": "11111111",
                "fh_score": "2-0",
                "full_score": "2-0",
                "fh_goals": 2,
                "half": "fh",
                "minute": 28,
                "status": "1H",
            }])
            n = settle_pending()
            assert n == 1
            saved = json.loads(ledger.read_text(encoding="utf-8"))
            snap = saved["snapshots"][0]
            assert snap["status"] == "lost"
            assert snap["legs"][0]["result"] == "lost"
        finally:
            acca_ledger.LEDGER_PATH = original


if __name__ == "__main__":
    test_under_busts_before_ht()
    test_under_wins_at_ht()
    test_over_wins_as_soon_as_line_breaks()
    test_over_loses_when_finished_under_line()
    test_ingest_and_early_loss_settles_whole_slip()
    print("ok")
