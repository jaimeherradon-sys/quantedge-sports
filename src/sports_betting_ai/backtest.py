"""Prospective paper backtest on recorded pre-game signals, never look-ahead.

IMPORTANT: this is *not* a retrospective simulation of unavailable historical
injury/price feeds. Only actual stored pre-event CANDIDATE signals qualify.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import pandas as pd
from sports_betting_ai.utils import parse_utc, norm_name


def run(con, starting_bankroll=100.0, stake=1.0, execution_cost=0.005, output_path=None):
    if starting_bankroll <= 0 or stake <= 0 or not 0 <= execution_cost < 1:
        raise ValueError("Invalid paper backtest configuration")
    rows = con.execute("""SELECT s.*,g.starts_at,g.game_date, g.status AS game_status FROM signals s
      JOIN games g ON g.id=s.game_id WHERE s.status='CANDIDATE' ORDER BY s.created_at""").fetchall()
    ordered = {}
    for r in rows:
        if r["game_status"] != "final" or not r["starts_at"]:
            continue
        if parse_utc(r["created_at"]) >= parse_utc(r["starts_at"]):
            continue
        # Only the earliest recorded signal for a particular selection.
        k = (r["game_id"], norm_name(r["player_name"]), r["market"], r["side"], r["line"])
        ordered.setdefault(k, r)
    eligible = []
    for r in ordered.values():
        gr = con.execute("SELECT * FROM player_games WHERE game_id=?", (r["game_id"],)).fetchall()
        matched = [p for p in gr if norm_name(p["player_name"]) == norm_name(r["player_name"])]
        if len(matched) != 1:
            continue
        stat = {"player_points":"points", "player_rebounds":"rebounds", "player_assists":"assists"}.get(r["market"])
        if not stat:
            continue
        actual = matched[0][stat]
        # Line on an integer is a push in two-way markets; grade as void.
        push = actual == r["line"]
        won = actual > r["line"] if r["side"] == "over" else actual < r["line"]
        latest = con.execute("""SELECT price,quote_at FROM odds
          WHERE game_id=? AND bookmaker=? AND player_name=? AND market=? AND side=? AND line=?
          AND quote_at>? AND quote_at<? ORDER BY quote_at DESC LIMIT 1""",
          (r["game_id"],r["bookmaker"],r["player_name"],r["market"],r["side"],r["line"],r["created_at"],r["starts_at"])).fetchone()
        clv = (r["price"] / latest["price"] - 1) if latest and latest["price"] > 1 else None
        eligible.append({"date": r["game_date"], "at": r["created_at"], "game_id": r["game_id"],
                         "player": r["player_name"], "market": r["market"], "odds": r["price"],
                         "win": int(won), "push": bool(push), "clv": clv, "p":r["probability"],
                         "profit": 0.0 if push else (stake * (r["price"] - 1) - stake*execution_cost if won
                                                       else -stake - stake*execution_cost)})
    # Store starting capital and reinvest nothing; flat paper stakes, no actual wager.
    eligible.sort(key=lambda r: (r["date"], r["at"],r["game_id"]))
    bankroll = starting_bankroll
    peak = bankroll
    drawdown = 0.0
    curve = [{"index":0,"bankroll":bankroll}]
    for i, r in enumerate(eligible, 1):
        bankroll += r["profit"]
        peak = max(peak, bankroll)
        drawdown = max(drawdown, (peak-bankroll)/peak)
        curve.append({"index": i, "bankroll": round(bankroll, 4)})
    n = len(eligible)
    settled = [r for r in eligible if not r["push"]]
    # Calibration is calculated ONLY on honestly stored pre-event paper probabilities.
    brier = sum((r["p"]-r["win"])**2 for r in settled)/len(settled) if settled else None
    logloss = (sum(-(r["win"]*math.log(max(1e-8,min(1-1e-8,r["p"])))
                      +(1-r["win"])*math.log(max(1e-8,min(1-1e-8,1-r["p"]))))
                   for r in settled)/len(settled)) if settled else None
    by_market = {}
    for market in sorted({x["market"] for x in eligible}):
        x = [r for r in eligible if r["market"] == market]
        by_market[market] = {"bets": len(x), "roi": sum(r["profit"] for r in x)/(len(x)*stake)}
    by_price = {}
    for band, func in (("1.01-1.50", lambda r:r["odds"]<=1.5),
                       ("1.50-2.00", lambda r:1.5<r["odds"]<=2),
                       ("above-2.00", lambda r:r["odds"]>2)):
        x = [r for r in eligible if func(r)]
        by_price[band] = {"bets":len(x),
                          "roi":sum(r["profit"] for r in x)/(len(x)*stake) if x else None}
    valid_clv = [r["clv"] for r in eligible if r["clv"] is not None]
    result = {"bets": n, "wins": sum(r["win"] for r in eligible),
              "hit_rate": sum(r["win"] for r in settled)/len(settled) if settled else None,
              "pushes":sum(r["push"] for r in eligible), "brier":brier, "logloss":logloss,
              "roi": sum(r["profit"] for r in eligible)/(n*stake) if n else None,
              "yield": sum(r["profit"] for r in eligible)/(n*stake) if n else None,
              "net_profit": sum(r["profit"] for r in eligible), "max_drawdown": drawdown if n else None,
              "starting_bankroll": starting_bankroll, "final_bankroll": bankroll,
              "clv_mean": sum(valid_clv)/len(valid_clv) if valid_clv else None,
              "clv_samples": len(valid_clv), "by_market": by_market,
              "by_odds_band":by_price,"by_sport":{"NBA":{"bets":n}}, "bankroll_curve": curve,
              "note": "Prospective paper-only signals. No retrospective backfill or future information."}
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
