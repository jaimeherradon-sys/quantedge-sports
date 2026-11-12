"""Synthetic offline tests; do not include real provider prices or player history."""
import sqlite3
from research.audit_opening_odds import analyze


def _dbs(tmp_path):
    history=tmp_path/'history.sqlite'; odds=tmp_path/'odds.sqlite'
    h=sqlite3.connect(history)
    h.executescript('''
      CREATE TABLE games(id INTEGER PRIMARY KEY,game_date TEXT,status TEXT);
      CREATE TABLE player_games(game_id INT,player_id INT,points INT);
      INSERT INTO games VALUES(1,'2026-11-11','final');
      INSERT INTO player_games VALUES(1,10,21);
    ''');h.close()
    o=sqlite3.connect(odds)
    o.executescript('''
      CREATE TABLE goat_games(game_id INT,game_date TEXT,home_name TEXT,away_name TEXT,starts_at TEXT);
      CREATE TABLE goat_odds_quotes(game_id INT,player_id INT,scope TEXT,vendor TEXT,
          market TEXT,market_type TEXT,side TEXT,line REAL,quote_at TEXT,observed_at TEXT,decimal_odds REAL);
      INSERT INTO goat_games VALUES(1,'2026-11-11','Fixture A','Fixture B','2026-11-12T00:00:00+00:00');
      INSERT INTO goat_odds_quotes VALUES(1,10,'player','example1','points','over_under','over',20.5,'2026-11-11T20:00:00+00:00','2026-11-12T12:00:00+00:00',1.91);
      INSERT INTO goat_odds_quotes VALUES(1,10,'player','example1','points','over_under','under',20.5,'2026-11-11T20:00:00+00:00','2026-11-12T12:00:00+00:00',1.91);
      INSERT INTO goat_odds_quotes VALUES(1,11,'player','example2','points','milestone','yes',20,'2026-11-11T19:00:00+00:00','2026-11-12T12:00:00+00:00',2.1);
    ''');o.close()
    return history,odds


def test_market_audit_marks_unmatched_and_archival_quotes(tmp_path):
    h,o=_dbs(tmp_path)
    r=analyze(str(h),str(o))
    assert r['unique_games']==1
    assert r['games_matched_to_history']==1
    assert r['odds_rows']==3
    assert r['player_quote_rows_matched_to_observed_player_games']==2
    assert r['player_quote_rows_unmatched']==1
    assert r['complete_player_over_under_pairs']==1
    assert 0.04 < r['median_two_way_overround'] < .05
    assert r['quote_at_after_tipoff_or_after_observation']==0
    assert r['archival_quotes_observed_after_tipoff']==3
    assert r['research_decision']=='NO BET'


def test_market_audit_separates_bad_timestamp(tmp_path):
    h,o=_dbs(tmp_path)
    c=sqlite3.connect(o)
    c.execute("UPDATE goat_odds_quotes SET quote_at='2026-11-12T01:00:00+00:00' WHERE player_id=11")
    c.commit();c.close()
    assert analyze(str(h),str(o))['quote_at_after_tipoff_or_after_observation']==1