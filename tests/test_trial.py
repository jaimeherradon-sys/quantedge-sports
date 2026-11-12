"""Offline contract fixtures. These are NOT actual NBA observations."""
from datetime import date, timedelta
import pytest
from sports_betting_ai.trial import TrialClient, windows, audit, probe, backfill
from sports_betting_ai.storage import connect


def test_trial_windows_are_ordered_and_bounded():
    x = list(windows("2026-01-01", "2026-01-30", chunk_days=14))
    assert x == [("2026-01-01", "2026-01-14"), ("2026-01-15", "2026-01-28"),
                 ("2026-01-29", "2026-01-30")]
    with pytest.raises(ValueError):
        list(windows("2025-01-01", "2025-05-01"))
    with pytest.raises(ValueError):
        list(windows("2026-02-01", "2026-01-01"))


class FakeSession:
    def __init__(self, pages):
        self.headers = {}
        self.pages = pages
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        return type("R", (), {"raise_for_status": lambda self: None,
                              "json": lambda self: pages_zero(self)})()


def pages_zero(obj):
    return {"data": []}


def test_trial_rate_limit_spacing():
    calls = []
    clock = [0.0]
    class Session:
        headers = {}
        def get(self, url, params=None, timeout=None):
            calls.append(clock[0])
            class Response:
                def raise_for_status(self): pass
                def json(self): return {"data": []}
            return Response()
    def sleep(d): clock[0] += d
    c = TrialClient(key="test-only", session=Session(), clock=lambda: clock[0], sleeper=sleep)
    c.get("/v1/games")
    c.get("/v1/stats")
    c.get("/v1/games")
    assert calls == [0, 18, 36]
    with pytest.raises(ValueError):
        TrialClient(key="test-only", session=Session(), spacing_seconds=12)


def test_trial_probe_checks_both_access_levels():
    class Client:
        calls = 2
        def check_stats(self): return {"stats_access_verified": True}
        def get(self, path, params=None):
            assert "stats/advanced" in path
            return {"data": [{"id":1}]}
    r = probe(Client())
    assert r["goat_advanced_endpoint"] == "OK"
    assert r["odds_coverage_verified"] is False


def test_audit_empty_is_no_bet(tmp_path):
    con = connect(str(tmp_path / "fixture.sqlite"))
    d = audit(con, "2026-01-01", "2026-01-30")
    assert d["player_game_rows"] == 0
    assert d["betting_status"] == "NO BET"
    con.close()


def test_trial_backfill_with_fake_provider_and_real_sqlite(tmp_path):
    class FixtureClient:
        calls = 2
        def games(self, start, end):
            yield {"id": 901, "date":"2026-01-10", "datetime":"2026-01-10T19:00:00Z",
                   "status_state":"final", "home_team":{"id":1,"full_name":"Fixture A"},
                   "visitor_team":{"id":2,"full_name":"Fixture B"},
                   "home_team_score":105, "visitor_team_score":99}
        def player_stats(self, start, end):
            yield {"game":{"id":901}, "player":{"id":12,"first_name":"Test", "last_name":"Athlete"},
                   "team":{"id":1}, "min":"29:30", "pts":22,"reb":5,"ast":6,"fg3m":3}
    db = tmp_path / "trial.sqlite"
    report = backfill(FixtureClient(), str(db), "2026-01-10", "2026-01-10")
    assert report["audit"]["games"] == 1
    assert report["audit"]["player_game_rows"] == 1
    assert report["audit"]["sqlite_integrity"] == "ok"
