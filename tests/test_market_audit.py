"""Synthetic sqlite fixture; no real sports data or API calls."""
from datetime import datetime, timezone, timedelta
import sqlite3
from sports_betting_ai.goat_odds import DDL
from sports_betting_ai.market_audit import audit_file


def fixture(tmp_path, contradictory=False):
    path = tmp_path / "fake.sqlite"
    c = sqlite3.connect(path)
    c.executescript(DDL)
    c.execute("INSERT INTO goat_games VALUES(?,?,?,?,?,?,?,?)",
              (101, "2026-11-12", "2026-11-13T00:00:00Z", "Home", "Away",
               "scheduled", "2026-11-12T18:00:00Z", "fixture"))
    for vendor, line in [("a",24.5),("b",24.5),("c",24.5),("d",5.5)]:
        for side, price in [("over",1.91),("under",1.91)]:
            q="2026-11-13T01:00:00Z" if contradictory and vendor=="a" else "2026-11-12T17:59:00Z"
            c.execute("""INSERT INTO goat_odds_quotes
              (kind,scope,game_id,player_id,vendor,market,market_type,side,line,american,
               decimal_odds,implied_probability,quote_at,observed_at,pregame,source,endpoint)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("live","player",101,1,vendor,"points","over_under",side,line,
                 -110,price,1/price,q,"2026-11-12T18:00:00Z",1,"fixture","/test"))
    c.commit();c.close()
    return path


def test_flags_far_off_peer_lines_without_ever_recommending_bets(tmp_path):
    r = audit_file(str(fixture(tmp_path)))
    assert r["error_count"] == 0
    assert r["nonstandard_line_quote_count"] == 1
    assert r["nonstandard_line_samples"][0]["quoted_line"] == 5.5
    assert r["paired_player_markets"] == 4
    assert r["status"] == "NO BET"


def test_rejects_post_tipoff_quotes(tmp_path):
    r = audit_file(str(fixture(tmp_path,contradictory=True)))
    assert r["error_count"] >= 2
