"""Future football module: statistical primitives only, no unsupported picks."""
from __future__ import annotations
import numpy as np
from scipy.stats import poisson


def independent_score_matrix(home_xg: float, away_xg: float, max_goals: int = 12):
    """Naive independent-Poisson baseline; use only with validated xG inputs.

    Mass above the truncation is not renormalized and is returned separately.
    Do not use this alone for odds/picks: Dixon-Coles, correlation, validation,
    injuries, lineup and market prices are not yet implemented.
    """
    if not (0 < home_xg < 10 and 0 < away_xg < 10 and 1 <= max_goals <= 30):
        raise ValueError("Unsupported or missing expected-goals parameters")
    p_home = poisson.pmf(np.arange(max_goals + 1), home_xg)
    p_away = poisson.pmf(np.arange(max_goals + 1), away_xg)
    matrix = np.outer(p_home, p_away)
    return matrix, float(1 - matrix.sum())


def league_projections(con, *, competition: str, date: str, asof: str | None = None):
    """Conservative football research-only forecasts; NO betting calls or picks.

    Features strictly from FINISHED fixtures whose kickoff was before asof.
    Score model is only an uncalibrated baseline; a market edge is NEVER claimed.
    """
    from datetime import timedelta
    from sports_betting_ai.utils import parse_utc
    from sports_betting_ai.connectors import utcnow
    stamp = asof or utcnow()
    con.execute("""CREATE TABLE IF NOT EXISTS football_matches (
      id INTEGER PRIMARY KEY,competition TEXT NOT NULL,season INTEGER NOT NULL,
      starts_at TEXT NOT NULL,home_team_id INTEGER NOT NULL,away_team_id INTEGER NOT NULL,
      home_team TEXT NOT NULL,away_team TEXT NOT NULL,status TEXT NOT NULL,
      home_goals INTEGER,away_goals INTEGER,source TEXT NOT NULL,fetched_at TEXT NOT NULL)""")
    games = [dict(r) for r in con.execute("SELECT * FROM football_matches WHERE competition=? ORDER BY starts_at",
                                          (competition,))]
    history = [m for m in games if m["status"] == "FINISHED" and m["starts_at"] < stamp
               and m["home_goals"] is not None and m["away_goals"] is not None]
    future = [m for m in games if m["status"] in ("SCHEDULED", "TIMED") and
              m["starts_at"][:10] == date and m["starts_at"] > stamp]
    if len(history) < 80:
        return [{"fixture":m["id"],"status":"NO BET","reason":"insufficient completed league games"}
                for m in future]
    league_h = np.mean([m["home_goals"] for m in history])
    league_a = np.mean([m["away_goals"] for m in history])
    if min(league_h,league_a) <= 0:
        return []

    def weighted_rate(values, league_rate):
        if len(values) < 10:
            return None
        samples = np.asarray(values[-20:],float)
        shrink = len(samples)/(len(samples)+10)
        return (1-shrink)+shrink*float(samples.mean()/league_rate)

    output=[]
    for game in future:
        past = [m for m in history if m["starts_at"] < game["starts_at"]]
        hg = [m for m in past if m["home_team_id"] == game["home_team_id"]]
        ag = [m for m in past if m["away_team_id"] == game["away_team_id"]]
        ha = weighted_rate([m["home_goals"] for m in hg],league_h)
        hd = weighted_rate([m["away_goals"] for m in hg],league_a)
        aa = weighted_rate([m["away_goals"] for m in ag],league_a)
        ad = weighted_rate([m["home_goals"] for m in ag],league_h)
        if any(v is None for v in (ha,hd,aa,ad)):
            output.append({"fixture":game["id"],"status":"NO BET",
                           "reason":"less than 10 historical home/away games"})
            continue
        lam_h = float(np.clip(league_h*ha*ad,0.2,4.5))
        lam_a = float(np.clip(league_a*aa*hd,0.2,4.5))
        score, tail = independent_score_matrix(lam_h,lam_a,max_goals=14)
        p_home = float(np.tril(score,k=-1).sum())
        p_draw = float(np.trace(score))
        p_away = float(np.triu(score,k=1).sum())
        p_btts = (1-np.exp(-lam_h))*(1-np.exp(-lam_a))
        output.append({"fixture":game["id"],"home":game["home_team"],
                       "away":game["away_team"],"kickoff":game["starts_at"],
                       "lambda_home":round(lam_h,3),"lambda_away":round(lam_a,3),
                       "p_home":round(p_home,4),"p_draw":round(p_draw,4),
                       "p_away":round(p_away,4),"p_btts":round(float(p_btts),4),
                       "unassigned_score_mass":float(tail),
                       "status":"NO BET", "source":"football-data.org",
                       "attribution":"Football data provided by the Football-Data.org API",
                       "reason":"uncalibrated independent-Poisson baseline; no validated odds"})
    return output
