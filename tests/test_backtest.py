from sports_betting_ai.storage import connect
from sports_betting_ai.backtest import run


def test_paper_backtest_only_pregame(tmp_path):
    db=connect(str(tmp_path/"b.db"))
    with db:
        db.execute("INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (10,"2025-01-15","2025-01-15T23:00:00Z",1,2,"A","B","final",100,90,"licensed","2025-01-16T01:00:00Z"))
        db.execute("INSERT INTO player_games VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (10,5,"Paper Test",1,"2025-01-15","2025-01-15T23:00:00Z",1,25,25,8,3,2,"licensed","2025-01-16T01:00:00Z"))
        db.execute("INSERT INTO signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (10,"Paper Test","player_points","over",20.5,"Book",1.80,.64,.61,.69,1/1.8,.152,.098,"CANDIDATE","validated","2025-01-15T22:00:00Z"))
    r=run(db,execution_cost=.01)
    assert r["bets"]==1
    assert r["wins"]==1
    assert r["net_profit"]==.79
    # Remove valid signal, replace with look-ahead timestamp (not eligible)
    with db:
        db.execute("UPDATE signals SET created_at='2025-01-15T23:10:00Z'")
    assert run(db)["bets"]==0


def test_daily_returns_no_bet_without_real_source_data(tmp_path):
    from sports_betting_ai.daily import generate
    con=connect(str(tmp_path/"empty.db"))
    result=generate(con,str(tmp_path/"models"),"2025-03-02",asof="2025-03-02T09:00:00Z",report_dir=str(tmp_path/"reports"))
    assert result["status"]=="NO BET"
    assert not result["selected"]
    assert not result["signals"]
