"""Deterministic mathematical fixtures. Numbers here are NOT real NBA statistics."""
from datetime import date, timedelta
import numpy as np
import pandas as pd
import pytest
from sports_betting_ai.value import expected_value, no_vig_two_way, decide, fractional_kelly
from sports_betting_ai.features import training_rows, future_row, COLS
from sports_betting_ai.distributions import over_probability, confidence_range
from sports_betting_ai.combinations import empirical_combination
from sports_betting_ai.football import independent_score_matrix


def test_ev_and_no_vig():
    assert expected_value(.7, 1.5) == pytest.approx(.05)
    assert expected_value(.65, 1.5) < 0
    a, b = no_vig_two_way(1.83, 1.91)
    assert a+b == pytest.approx(1)
    assert a < 1/1.83
    assert fractional_kelly(.5, 1.5) == 0


def test_no_bet_uncertainty():
    d = decide(.8, .60, .95, 1.5, market_fresh=True, availability_verified=True, model_validated=True)
    assert d.status == "NO BET"
    good = decide(.8, .76, .84, 1.5, market_fresh=True, availability_verified=True, model_validated=True)
    assert good.status == "CANDIDATE"
    stale = decide(.8, .76, .84, 1.5, market_fresh=False, availability_verified=True, model_validated=True)
    assert stale.status == "NO BET"
    with pytest.raises(ValueError):
        decide(.8, .9, .95, 1.5, market_fresh=True, availability_verified=True, model_validated=True)


def test_features_prior_only():
    rows = []
    for i in range(25):
        d = date(2025,1,1) + timedelta(days=i)
        rows.append({"player_id":1,"game_id":i,"game_date":d.isoformat(),
                     "points": 10 if i != 20 else 999,"rebounds":3,"assists":5,
                     "minutes":25, "home":i%2})
    h = pd.DataFrame(rows)
    f = training_rows(h)
    row20 = f[f.game_id==20].iloc[0]
    assert row20["points_20"] == pytest.approx(10)
    assert row20["points"] == 999
    after = future_row(h, 1, "2025-01-26", 100, True)
    assert after is not None
    assert after["game_id"] == 100
    assert after["points_5"] > 10
    # Missing 20 actual past player games -> never project.
    assert future_row(h.head(19), 1, "2025-01-26", 100, True) is None


def test_distributions_count_and_bootstrap():
    assert 0 < over_probability(15,14.5) < 1
    assert over_probability(15,14.5,.1) != pytest.approx(over_probability(15,14.5))
    lo, hi = confidence_range(15,14.5,.1,[11,12,14,15,16]*4)
    assert 0 <= lo <= hi <= 1
    assert confidence_range(3,3.5,.2,[3]*19) == (0,1)


def test_joint_probability_is_observed_not_multiplied():
    # 80 both wins, 120 both losses, so joint=40%, product of margins=16%.
    samples = np.array([[1,1]]*80 + [[0,0]]*120)
    r = empirical_combination(samples,[1.5,1.6])
    assert r.probability == pytest.approx(.4)
    assert r.odds == pytest.approx(2.4)
    assert r.ev == pytest.approx(-.04)
    with pytest.raises(ValueError, match="NO BET"):
        empirical_combination(samples[:100], [1.5, 1.6])


def test_football_is_non_operational_baseline():
    mat, tail = independent_score_matrix(1.5,1.2)
    assert mat.sum()+tail == pytest.approx(1)
    assert mat[0,0] > 0


def test_football_research_projection_no_bet(tmp_path):
    from sports_betting_ai.storage import connect, FOOTBALL_SCHEMA
    from sports_betting_ai.football import league_projections
    con=connect(str(tmp_path/"football.db"))
    con.executescript(FOOTBALL_SCHEMA)
    with con:
        for i in range(85):
            con.execute("INSERT INTO football_matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (i,"PL",2025,f"2025-01-{(i%28)+1:02d}T12:00:00Z",1+i%2,3+i%2,
                         "A","B","FINISHED",1,2,"test fixture","2025-04-01T00:00:00Z"))
        con.execute("INSERT INTO football_matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (100,"PL",2025,"2025-05-01T12:00:00Z",1,3,"A","B","SCHEDULED",None,None,"test fixture","2025-04-01T00:00:00Z"))
    x=league_projections(con,competition="PL",date="2025-05-01",asof="2025-04-30T00:00:00Z")
    assert len(x)==1
    assert x[0]["status"]=="NO BET"


def test_correlated_mc_bounded_100k():
    from sports_betting_ai.combinations import bootstrap_joint_probability
    observations=np.array([[1,1]]*150+[[0,0]]*150)
    result=bootstrap_joint_probability(observations,[1.6,1.6],simulations=100_000)
    assert result["joint_p"]==.5
    assert result["joint_p_low"] < .5 < result["joint_p_high"]
    assert result["bootstrap_replicates"]<=2_000
