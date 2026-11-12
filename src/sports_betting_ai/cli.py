"""CLI: real provider connection checks, ingestion, model fit, research and paper backtest."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from sports_betting_ai.connectors import BallDontLie, TheOddsAPI, utcnow
from sports_betting_ai.storage import connect, ingest_bdl, ingest_injuries, save_odds_snapshot, record_source_check


def emit(obj):
    print(json.dumps(obj, indent=2, default=str))


def main(argv=None):
    p = argparse.ArgumentParser(prog="sbai", description="NBA statistics research (no automated betting)")
    p.add_argument("--db", default=os.getenv("SBAI_DB", "data/sports.db"))
    p.add_argument("--models", default="models")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="Live credential-bound endpoint smoke check")
    c.add_argument("--provider", choices=["bdl", "bdl-stats", "odds", "football", "all"], default="all")
    i = sub.add_parser("ingest", help="Import only BDL verified finished stats plus scheduled games")
    i.add_argument("--start", required=True, help="YYYY-MM-DD")
    i.add_argument("--end", required=True, help="YYYY-MM-DD")
    free = sub.add_parser("games-free", help="Import real NBA fixtures/final scores without paid player stats")
    free.add_argument("--days", type=int, default=7, help="Days to look back, max 90")
    free.add_argument("--forward-days", type=int, default=2, help="Upcoming days, max 7")
    sub.add_parser("injuries", help="Snapshot paid injury data")
    o = sub.add_parser("odds", help="Snapshot current authorized NBA player odds; requires games imported first")
    o.add_argument("--region", default="us", help="Provider region code, e.g. us, eu, uk")
    fi = sub.add_parser("football-ingest", help="Import real football-data.org fixtures & scores")
    fi.add_argument("--competition", required=True, help="e.g. PL, PD, BL1, SA, FL1")
    fi.add_argument("--season", required=True, type=int, help="starting year")
    fd = sub.add_parser("football-daily", help="Uncalibrated football Poisson projections; always NO BET")
    fd.add_argument("--competition", required=True)
    fd.add_argument("--date", required=True)
    sub.add_parser("train", help="Walk-forward model selection and untouched test")
    d = sub.add_parser("daily", help="Paper projections + fail-closed signals")
    d.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    d.add_argument("--availability", default=None, help="Human-verified CSV, never invent records")
    d.add_argument("--out", default="reports")
    b = sub.add_parser("backtest", help="Retrospective grade of actual pre-event paper signals only")
    b.add_argument("--out", default="reports/paper_backtest.json")
    u = sub.add_parser("update", help="Scheduled refresh; safe defaults if APIs/models unavailable")
    u.add_argument("--days", type=int, default=90)
    u.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    args = p.parse_args(argv)
    if args.command == "check":
        outputs = []
        if args.provider in ("bdl", "bdl-stats", "all"):
            client = BallDontLie()
            outputs.append(client.check_stats() if args.provider == "bdl-stats" else client.check())
        if args.provider in ("odds", "all"):
            outputs.append(TheOddsAPI().check())
        if args.provider == "football":
            from sports_betting_ai.connectors import FootballDataOrg
            outputs.append(FootballDataOrg().check())
        emit(outputs)
        return
    if args.command == "football-ingest":
        from sports_betting_ai.connectors import FootballDataOrg
        from sports_betting_ai.storage import ingest_football
        con = connect(args.db)
        emit(ingest_football(FootballDataOrg(), con, args.competition, args.season, utcnow()))
        con.close()
        return
    if args.command == "football-daily":
        from sports_betting_ai.football import league_projections
        con = connect(args.db)
        emit(league_projections(con, competition=args.competition, date=args.date))
        con.close()
        return
    con = connect(args.db)
    if args.command == "games-free":
        from sports_betting_ai.free_games import ingest_free_games
        if not 0 <= args.days <= 90 or not 0 <= args.forward_days <= 7 or args.days + args.forward_days > 90:
            p.error("Invalid free game range: days=0..90, forward-days=0..7, sum <= 90")
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=args.days)).isoformat()
        end = (today + timedelta(days=args.forward_days)).isoformat()
        emit(ingest_free_games(BallDontLie(), con, start, end))
    elif args.command == "ingest":
        if args.start > args.end:
            p.error("start must be <= end")
        emit(ingest_bdl(BallDontLie(), con, args.start, args.end, utcnow()))
    elif args.command == "injuries":
        check_at = utcnow()
        n = ingest_injuries(BallDontLie(), con, check_at)
        record_source_check(con, "balldontlie", "injuries", check_at)
        emit({"injuries": n, "snapshot_at": check_at})
    elif args.command == "odds":
        emit(save_odds_snapshot(TheOddsAPI(), con, utcnow(), region=args.region))
    elif args.command == "train":
        from sports_betting_ai.features import from_db
        from sports_betting_ai.model import train
        emit(train(from_db(con), args.models))
    elif args.command == "daily":
        from sports_betting_ai.daily import generate
        result = generate(con, args.models, args.date, availability_csv=args.availability, report_dir=args.out)
        emit({"status": result["status"], "projections": len(result["projections"]),
              "signals_checked": len(result["signals"]), "selected": result["selected"]})
    elif args.command == "backtest":
        from sports_betting_ai.backtest import run
        emit(run(con, output_path=args.out))
    elif args.command == "update":
        today = datetime.strptime(args.date, "%Y-%m-%d").date()
        if not 1 <= args.days <= 400:
            p.error("--days must be between 1 and 400")
        since = (today - timedelta(days=args.days)).isoformat()
        if not os.getenv("BDL_API_KEY"):
            emit({"status":"NO BET","reason":"BDL_API_KEY not configured"})
            return
        stamp = utcnow()
        imported = ingest_bdl(BallDontLie(), con, since, args.date, stamp)
        output = {"ingestion": imported}
        try:
            c = BallDontLie()
            injury_at = utcnow()
            n = ingest_injuries(c, con, injury_at)
            record_source_check(con, "balldontlie", "injuries", injury_at)
            output["injuries"] = n
        except Exception as exc:
            output["injuries_error"] = type(exc).__name__
        if os.getenv("ODDS_API_KEY"):
            try:
                output["odds"] = save_odds_snapshot(TheOddsAPI(), con, utcnow())
            except Exception as exc:
                output["odds_error"] = type(exc).__name__
        from sports_betting_ai.features import from_db
        from sports_betting_ai.model import train
        from sports_betting_ai.daily import generate
        try:
            output["trained"] = list(train(from_db(con), args.models))
        except ValueError as exc:
            output["training_error"] = str(exc)
        report = generate(con, args.models, args.date)
        output["daily"] = {"status": report["status"], "selected": report["selected"]}
        emit(output)
    con.close()


if __name__ == "__main__":
    main()
