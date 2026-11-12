"""Pre-game NBA projections and conservative, auditable market screening.

A projection is NOT a betting signal. No verified availability, stale odds,
insufficient holdout or absent market => NO BET.
"""
from __future__ import annotations
from datetime import timedelta
import json
from pathlib import Path
import pandas as pd
from sports_betting_ai.connectors import utcnow
from sports_betting_ai.features import COLS, TARGETS, from_db, future_row
from sports_betting_ai.model import load_model
from sports_betting_ai.distributions import over_probability, confidence_range
from sports_betting_ai.storage import latest_source_check
from sports_betting_ai.utils import norm_name, parse_utc
from sports_betting_ai.value import decide, no_vig_two_way


def candidate_games(con, date: str, asof: str):
    return [dict(r) for r in con.execute("SELECT * FROM games WHERE game_date=? AND status='scheduled'", (date,))
            if r["starts_at"] and parse_utc(r["starts_at"]) > parse_utc(asof)]


def load_availability(path: str | None) -> dict:
    """Explicit human verified CSV: game_id,player_id,status,projected_minutes,verified_at,source."""
    if not path:
        return {}
    df = pd.read_csv(path)
    mandatory = {"game_id", "player_id", "status", "projected_minutes", "verified_at", "source"}
    if not mandatory.issubset(df.columns):
        raise ValueError(f"Availability CSV missing columns {mandatory - set(df.columns)}")
    result = {}
    for _, row in df.iterrows():
        result[(int(row["game_id"]), int(row["player_id"]))] = row.to_dict()
    return result


def _verified(row, *, game_id, player_id, mean_minutes, asof, injury_fresh, injuries):
    if not injury_fresh or row is None:
        return False
    now = parse_utc(asof)
    try:
        verified_at = parse_utc(str(row["verified_at"]))
        minutes = float(row["projected_minutes"])
    except (ValueError, TypeError, KeyError):
        return False
    if row.get("status") != "confirmed_available" or not row.get("source"):
        return False
    if not (now - timedelta(hours=6) <= verified_at <= now):
        return False
    if pd.isna(row.get("source")) or not str(row.get("source")).strip():
        return False
    if not (0.7 * mean_minutes <= minutes <= 1.3 * mean_minutes):
        return False
    injury = injuries.get(player_id)
    if injury and str(injury["status"]).casefold() not in ("available", "probable", "active"):
        return False
    return True


def generate(con, models_dir: str, date: str, *, asof: str | None = None,
             availability_csv: str | None = None, report_dir="reports") -> dict:
    now = asof or utcnow()
    history = from_db(con)
    availability = load_availability(availability_csv)
    check = latest_source_check(con, "balldontlie", "injuries")
    injury_fresh = bool(check and timedelta(0) <= parse_utc(now) - parse_utc(check) <= timedelta(hours=6))
    injuries = {}
    if check:
        for r in con.execute("SELECT * FROM injuries WHERE snapshot_at=?", (check,)):
            injuries[r["player_id"]] = r
    games = candidate_games(con, date, now)
    report = {"date": date, "generated_at": now, "games": len(games),
              "projections": [], "signals": [], "status": "NO BET",
              "note": "Historical model validation cannot substitute for historical odds backtesting"}
    valid_quotes = []
    for game in games:
        # Roster inferred from last recorded game; not official projected lineup.
        sorted_hist = history[history["game_date"] < game["game_date"]].sort_values(["game_date", "game_id"])
        latest = sorted_hist.drop_duplicates("player_id", keep="last")
        latest = latest[latest["team_id"].isin((game["home_id"], game["away_id"]))]
        for _, p in latest.iterrows():
            player_id = int(p["player_id"])
            f = future_row(history, player_id, date, game["id"], p["team_id"] == game["home_id"])
            if f is None:
                continue
            mean_minutes = f["minutes_5"]
            confirmed = _verified(availability.get((game["id"], player_id)), game_id=game["id"],
                                  player_id=player_id, mean_minutes=mean_minutes, asof=now,
                                  injury_fresh=injury_fresh, injuries=injuries)
            for market, stat in TARGETS.items():
                bundle = load_model(models_dir, market)
                if bundle is None:
                    continue
                meta = bundle["metadata"]
                if meta["asof_game_date"] >= date:
                    # Never use a fitted model built with future same-day or later results.
                    continue
                mu = max(0.01, float(bundle["model"].predict(pd.DataFrame([f])[COLS].to_numpy())[0]))
                report["projections"].append({"game_id": game["id"], "player": p["player_name"],
                                              "market": market, "expected": round(mu, 2),
                                              "estimated_minutes_last5": round(mean_minutes, 1),
                                              "model": meta["selected"], "model_asof": meta["asof_game_date"],
                                              "availability_verified": confirmed})
                with con:
                    con.execute("INSERT OR IGNORE INTO projections VALUES(?,?,?,?,?,?,?,?,?)",
                                (game["id"], player_id, market, p["player_name"], mu, now,
                                 meta["selected"], meta["asof_game_date"], "balldontlie"))
                quotes = [dict(r) for r in con.execute("""SELECT * FROM odds WHERE game_id=? AND market=?
                  AND side IN ('over','under') AND quote_at<=? ORDER BY quote_at DESC""", (game["id"], market, now))
                          if norm_name(r["player_name"]) == norm_name(str(p["player_name"]))]
                recent = sorted_hist[sorted_hist["player_id"] == player_id][stat].tail(20).to_numpy()
                seen_quotes = set()
                for q in quotes:
                    key = (q["bookmaker"], q["market"], q["side"], q["line"])
                    if key in seen_quotes:
                        continue
                    seen_quotes.add(key)
                    p_over = over_probability(mu, q["line"], bundle["alpha"])
                    lo, hi = confidence_range(mu, q["line"], bundle["alpha"], recent)
                    lo, hi = min(lo, p_over), max(hi, p_over)
                    if q["side"] == "over":
                        prob, low, high = p_over, lo, hi
                    else:
                        prob, low, high = 1 - p_over, 1 - hi, 1 - lo
                    fresh = (timedelta(0) <= parse_utc(now) - parse_utc(q["quote_at"]) <= timedelta(minutes=90)
                             and parse_utc(q["commence_time"]) > parse_utc(now))
                    decision = decide(prob, low, high, q["price"], market_fresh=fresh,
                                      availability_verified=confirmed,
                                      model_validated=meta["out_of_sample_adequate"])
                    opposite = next((x for x in quotes if x["bookmaker"] == q["bookmaker"]
                                     and x["market"] == q["market"] and x["line"] == q["line"]
                                     and x["quote_at"] == q["quote_at"] and x["side"] != q["side"]), None)
                    novig = None
                    if opposite:
                        o, u = (q["price"], opposite["price"]) if q["side"] == "over" else (opposite["price"], q["price"])
                        n = no_vig_two_way(o, u)
                        novig = n[0] if q["side"] == "over" else n[1]
                    info = {"game_id": game["id"], "player": p["player_name"], "market": market,
                            "side": q["side"], "line": q["line"], "bookmaker": q["bookmaker"],
                            "decimal_odds": q["price"], "p": round(decision.probability, 4),
                            "p_low": round(decision.p_low, 4), "p_high": round(decision.p_high, 4),
                            "implied": round(decision.implied, 4),
                            "no_vig": round(novig, 4) if novig is not None else None,
                            "ev": round(decision.ev, 4), "ev_lower": round(decision.ev_lower, 4),
                            "status": decision.status, "reason": decision.reason,
                            "quote_at": q["quote_at"], "source": q["source"]}
                    report["signals"].append(info)
                    if decision.status == "CANDIDATE":
                        valid_quotes.append(info)
    # Keep at most one signal per game to reduce correlated exposure; maximum three daily.
    chosen = []
    for v in sorted(valid_quotes, key=lambda x: x["ev_lower"], reverse=True):
        if len(chosen) >= 3:
            break
        if v["game_id"] not in {x["game_id"] for x in chosen}:
            chosen.append(v)
    kept = {(s["game_id"],s["player"],s["market"],s["side"],s["line"],s["bookmaker"]) for s in chosen}
    for s in report["signals"]:
        key = (s["game_id"],s["player"],s["market"],s["side"],s["line"],s["bookmaker"])
        if s["status"] == "CANDIDATE" and key not in kept:
            s["status"] = "NO BET"
            s["reason"] = "daily / per-game exposure cap"
        with con:
            con.execute("""INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (s["game_id"],s["player"],s["market"],s["side"],s["line"],s["bookmaker"],
                         s["decimal_odds"],s["p"],s["p_low"],s["p_high"],s["implied"],s["ev"],
                         s["ev_lower"],s["status"],s["reason"],now))
    report["selected"] = chosen
    if chosen:
        report["status"] = "CANDIDATES FOR MANUAL REVIEW"
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    (Path(report_dir) / f"nba_{date}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
