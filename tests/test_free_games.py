"""Synthetic contract fixtures only; tests never pretend to download NBA results."""
import pytest
from sports_betting_ai.storage import connect
from sports_betting_ai.free_games import ingest_free_games


def _game(id, status='final', date='2026-11-11', scores=(112, 108)):
    return {'id':id,'date':date,'datetime':date+'T20:00:00Z',
            'status_state':status,
            'home_team':{'id':1,'full_name':'Fixture Home'},
            'visitor_team':{'id':2,'full_name':'Fixture Away'},
            'home_team_score':scores[0],'visitor_team_score':scores[1]}


class FakeFreeClient:
    def __init__(self, games): self.rows = games
    def games(self, start, end): yield from self.rows
    def player_stats(self, start, end):
        raise AssertionError('Free importer must never access paid player stats')


def test_free_games_persists_only_verified_final_scores(tmp_path):
    con=connect(str(tmp_path/'games.db'))
    data=ingest_free_games(FakeFreeClient([_game(1),_game(2,'scheduled',scores=(0,0))]),
                           con,'2026-11-10','2026-11-12','2026-11-12T12:00:00Z')
    assert data['games_imported']==2
    assert data['final_results']==1
    assert data['player_stats_imported']==0
    upcoming=con.execute('SELECT * FROM games WHERE id=2').fetchone()
    assert upcoming['home_score'] is None
    assert upcoming['source']=='balldontlie'
    assert upcoming['fetched_at']=='2026-11-12T12:00:00Z'
    assert con.execute('SELECT COUNT(*) FROM game_snapshots').fetchone()[0]==2
    assert con.execute('SELECT COUNT(*) FROM player_games').fetchone()[0]==0
    # New completed results get a new snapshot rather than overwriting provenance.
    ingest_free_games(FakeFreeClient([_game(2)]),con,'2026-11-10','2026-11-12',
                      '2026-11-12T23:00:00Z')
    assert con.execute('SELECT COUNT(*) FROM game_snapshots').fetchone()[0]==3
    assert con.execute('SELECT home_score FROM games WHERE id=2').fetchone()[0]==112


def test_free_import_is_atomic_and_rejects_unverified_results(tmp_path):
    con=connect(str(tmp_path/'games.db'))
    with pytest.raises(ValueError, match='final result missing'):
        ingest_free_games(FakeFreeClient([_game(1),_game(2,scores=(None,None))]),
                          con,'2026-11-10','2026-11-12')
    assert con.execute('SELECT COUNT(*) FROM games').fetchone()[0]==0


def test_free_date_range_rejects_out_of_period(tmp_path):
    con=connect(str(tmp_path/'games.db'))
    with pytest.raises(ValueError, match='outside requested period'):
        ingest_free_games(FakeFreeClient([_game(1)]),con,'2026-11-01','2026-11-02')
