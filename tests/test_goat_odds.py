"""Synthetic provider fixtures; zero actual NBA odds or historical market claims."""
from datetime import datetime, timezone
import json
import sqlite3
import pytest
from sports_betting_ai.goat_odds import (
    american_to_decimal, no_vig_pair, get_list, ingest, parse_utc, player_odds_rows
)
from sports_betting_ai.connectors import DataSourceError

NOW=datetime(2026,11,12,18,0,0,tzinfo=timezone.utc)
FUTURE="2026-11-13T01:00:00Z"
PAST="2026-11-10T01:00:00Z"

class Provider:
    def __init__(self,*,day="2026-11-12",opening=False):
        self.calls=[]
        self.day=day
        self.opening=opening
    def games(self,start,end):
        assert start==end==self.day
        return [{"id":1234,"date":self.day,"datetime": PAST if self.opening else FUTURE,
                 "status_state":"final" if self.opening else "scheduled",
                 "home_team":{"id":1,"full_name":"Team A"},
                 "visitor_team":{"id":2,"full_name":"Team B"}}]
    def get(self,path,params=None):
        self.calls.append((path,params))
        if path.endswith("/player_props") or path.endswith("/player_props/opening"):
            at="2026-11-09T12:00:00Z" if self.opening else "2026-11-12T17:00:00Z"
            stamp="opened_at" if self.opening else "updated_at"
            return {"data":[
                {"id":2,"game_id":1234,"player_id":77,"vendor":"draftkings",
                 "prop_type":"points","line_value":"20.5",
                 "market":{"type":"over_under","over_odds":-110,"under_odds":-120},stamp:at},
                {"id":3,"game_id":1234,"player_id":77,"vendor":"draftkings",
                 "prop_type":"threes","line_value":"3",
                 "market":{"type":"milestone","odds":+225},stamp:at},
                {"id":4,"game_id":1234,"player_id":77,"vendor":"draftkings",
                 "prop_type":"points","line_value":"23.5",
                 "market":{"type":"over_under","over_odds":-110,"under_odds":-120},stamp:"2026-11-13T04:00:00Z"},
            ],"meta":{"per_page":3}}
        at="2026-11-09T12:00:00Z" if self.opening else "2026-11-12T17:00:00Z"
        stamp="opened_at" if self.opening else "updated_at"
        return {"data":[{"id":1,"game_id":1234,"vendor":"bet365",
                         "moneyline_home_odds":-140,"moneyline_away_odds":+125,
                         "total_value":"220.5","total_over_odds":-108,"total_under_odds":-112,
                         "spread_home_value":"-3.5","spread_home_odds":-110,
                         "spread_away_value":"+3.5","spread_away_odds":-110,stamp:at}],
                "meta":{}}


def test_american_to_decimal():
    assert american_to_decimal(-150)==pytest.approx(1.666666667)
    assert american_to_decimal(+225)==3.25
    assert american_to_decimal(-100)==2
    assert american_to_decimal(+100)==2
    for invalid in [0,99,-99,None,"nan",True]:
        with pytest.raises(ValueError):
            american_to_decimal(invalid)
    p,q=no_vig_pair(1.9,1.8)
    assert p+q==pytest.approx(1)


def test_live_odds_import_provenance_and_markets(tmp_path):
    c=Provider()
    path=tmp_path/"odds.sqlite"
    result=ingest(c,day="2026-11-12",kind="live",db_path=str(path),max_games=1,now=NOW)
    assert result["games_selected"]==1
    assert result["sqlite_integrity"]=="ok"
    assert result["quote_rows"]==9 # six game outcomes + two prop + one milestone
    assert result["two_way_pairs"]==1
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT COUNT(*) FROM goat_odds_raw").fetchone()[0]==2
        assert con.execute("SELECT DISTINCT source FROM goat_odds_quotes").fetchone()[0]=="balldontlie"
        assert con.execute("SELECT DISTINCT kind FROM goat_odds_quotes").fetchone()[0]=="live"
        assert con.execute("SELECT COUNT(*) FROM goat_odds_quotes WHERE player_id=77 AND market='points'").fetchone()[0]==2
        assert con.execute("SELECT COUNT(*) FROM goat_odds_quotes WHERE market_type='milestone'").fetchone()[0]==1
        assert con.execute("SELECT COUNT(*) FROM goat_odds_quotes WHERE quote_at >= observed_at").fetchone()[0]==0
        assert con.execute("SELECT COUNT(*) FROM goat_odds_quotes WHERE pregame=0").fetchone()[0]==0


def test_opening_backfill_distinguishes_observation_from_opened_at(tmp_path):
    c=Provider(day="2026-11-10",opening=True)
    result=ingest(c,day="2026-11-10",kind="opening",db_path=str(tmp_path/"opening.sqlite"),now=NOW)
    assert result["quote_rows"]==9
    assert result["two_way_pairs"]==1
    assert result["kind"]=="opening"
    assert all("opening" in x[0] for x in c.calls)
    with sqlite3.connect(tmp_path/"opening.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM goat_odds_quotes WHERE quote_at < observed_at").fetchone()[0]==9


def test_historical_opening_does_not_query_future_dates(tmp_path):
    with pytest.raises(ValueError):
        ingest(Provider(),day="2026-11-12",kind="opening",db_path=str(tmp_path/"x.db"),now=NOW)


def test_live_after_tipoff_is_no_bet(tmp_path):
    now=datetime(2026,11,13,2,0,tzinfo=timezone.utc)
    result=ingest(Provider(),day="2026-11-12",kind="live",db_path=str(tmp_path/"x.sqlite"),now=now)
    assert result["quote_rows"]==0
    assert result["status"]=="NO BET"


def test_unknown_provider_schema_fails_closed():
    class Broken:
        def get(self,path,params=None): return {"garbage": True}
    with pytest.raises(DataSourceError):
        get_list(Broken(),"/v2/odds",{"per_page":100},paged=True)


def test_odds_freshness_guards():
    row={"game_id":1234,"player_id":77,"vendor":"draftkings","prop_type":"points",
         "line_value":"19.5","market":{"type":"over_under","over_odds":-110,"under_odds":-120},
         "updated_at":"2026-11-13T02:00:00Z"}
    assert list(player_odds_rows(row,kind="live",observed_at="2026-11-12T18:00:00Z",starts=parse_utc(FUTURE)))==[]
