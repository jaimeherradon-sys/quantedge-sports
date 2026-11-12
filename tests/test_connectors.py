"""HTTP mocked integration tests; only `sbai check` validates actual credentials/network."""
import pytest
from sports_betting_ai.connectors import BallDontLie, DataSourceError
from sports_betting_ai.storage import connect, ingest_bdl, minute_value


class Response:
    def __init__(self, obj): self.obj = obj
    def raise_for_status(self): pass
    def json(self): return self.obj


class Session:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.calls = []
    def get(self, url, params, timeout):
        self.calls.append((url,dict(params)))
        return Response(self.pages.pop(0))


def test_pagination_cursor():
    s = Session([{"data":[{"id":1}],"meta":{"next_cursor":42}},
                 {"data":[{"id":2}],"meta":{}}])
    c = BallDontLie(key="test-only",session=s)
    assert list(c.paged("/v1/games")) == [{"id":1},{"id":2}]
    assert s.calls[1][1]["cursor"] == 42


def test_pagination_repeated_cursor_fails_closed():
    s=Session([{"data":[],"meta":{"next_cursor":1}},
               {"data":[],"meta":{"next_cursor":1}}])
    with pytest.raises(DataSourceError):
        list(BallDontLie(key="test-only",session=s).paged("/v1/games"))


def test_auth_required():
    with pytest.raises(DataSourceError):
        BallDontLie(key="",session=Session([])) if False else _no_key()


def _no_key():
    from sports_betting_ai.connectors import APIClient
    return APIClient("https://example.com", "", "Authorization")


class ProviderFixture:
    def games(self,start,end):
        return [{"id":12,"date":"2025-01-15","datetime":"2025-01-15T23:00:00Z",
                 "status_state":"final", "home_team":{"id":1,"full_name":"Home"},
                 "visitor_team":{"id":2,"full_name":"Away"}}]
    def player_stats(self,start,end):
        return [{"game":{"id":12},"player":{"id":99,"first_name":"Fixture","last_name":"Player"},
                 "team":{"id":1},"min":"22:30","pts":13,"reb":3,"ast":5,"fg3m":2},
                {"game":{"id":12},"player":{"id":10,"first_name":"Fixture","last_name":"DNP"},
                 "team":{"id":1},"min":"0","pts":0,"reb":0,"ast":0,"fg3m":0}]


def test_ingestion_realistic_schema_and_dnp_filter(tmp_path):
    con=connect(str(tmp_path/"unit.db"))
    result=ingest_bdl(ProviderFixture(), con,"2025-01-15","2025-01-15","2025-01-16T00:00:00Z")
    assert result["final_player_game_records"] == 1
    row=con.execute("SELECT * FROM player_games").fetchone()
    assert row["minutes"]==22.5
    assert row["player_id"]==99
    assert minute_value("21:15")==21.25
    con.close()


class OddsFixture:
    def events(self):
        return [{"id":"abc","home_team":"Home","away_team":"Away",
                 "commence_time":"2025-01-20T23:00:00Z"}]
    def event_props(self,event_id,regions="us"):
        assert event_id=="abc"
        return {"bookmakers":[{"key":"paper-book","markets":[{
            "key":"player_points","last_update":"2025-01-20T20:00:00Z",
            "outcomes":[{"name":"Over","description":"Fixture Player","point":19.5,"price":1.95},
                        {"name":"Under","description":"Fixture Player","point":19.5,"price":1.85},
                        {"name":"Over","description":"Fixture Player","point":20,"price":1.9}]
        }]}]}


def test_basketball_odds_exact_join_and_no_integer_push(tmp_path):
    from sports_betting_ai.storage import save_odds_snapshot
    con=connect(str(tmp_path/"odds.db"))
    with con:
        con.execute("INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (12,"2025-01-20","2025-01-20T23:00:00Z",1,2,"Home","Away",
                     "scheduled",None,None,"balldontlie","2025-01-20T18:00:00Z"))
    result=save_odds_snapshot(OddsFixture(),con,"2025-01-20T20:05:00Z")
    assert result["quotes_processed"]==2
    lines=con.execute("SELECT line,quote_at FROM odds").fetchall()
    assert len(lines)==2
    assert all(row["line"]==19.5 for row in lines)
    assert all(row["quote_at"]=="2025-01-20T20:00:00Z" for row in lines)
