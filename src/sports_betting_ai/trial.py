"""Carefully rate-limited BALLDONTLIE GOAT trial checks and player-stat backfill.

All real data comes from authenticated provider calls; NEVER prints credentials.
No bets, no fictitious success. Import chunks commit individually, allowing audits
and partial backups if a later API request fails.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import os
import sqlite3
import time
from pathlib import Path

from sports_betting_ai.connectors import BallDontLie, DataSourceError, utcnow
from sports_betting_ai.storage import connect, ingest_bdl


class TrialClient(BallDontLie):
    """Throttle all outbound provider calls below the five-per-minute trial cap.

    A 18-second minimum spacing permits ~3.33 logical calls per minute,
    leaving some margin for occasional manual checks. Do not run other jobs
    using the SAME key concurrently. Retries within requests are handled by
    the underlying HTTP client using Retry-After where supplied.
    """

    def __init__(self, key=None, spacing_seconds=18.0, session=None, clock=None, sleeper=None):
        super().__init__(key=key, session=session)
        if spacing_seconds < 15.0:
            raise ValueError("Trial request spacing must be at least 15 seconds")
        self.spacing = float(spacing_seconds)
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.next_call_at = None
        self.calls = 0

    def get(self, path: str, params=None):
        now = self.clock()
        if self.next_call_at is not None and now < self.next_call_at:
            self.sleeper(self.next_call_at - now)
        self.next_call_at = self.clock() + self.spacing
        self.calls += 1
        print(f"Provider request {self.calls}: {path}", flush=True)
        return super().get(path, params=params)


def probe(client: TrialClient) -> dict:
    stats = client.check_stats()
    if not stats.get("stats_access_verified"):
        raise DataSourceError("Player stats endpoint was not verified")
    # An independent GOAT-specific capability; response must follow documented schema.
    advanced = client.get("/nba/v2/stats/advanced", {"seasons[]": 2025, "per_page": 1})
    if not isinstance(advanced, dict) or not isinstance(advanced.get("data"), list):
        raise DataSourceError("Advanced stats response has unexpected schema")
    return {"player_stats_endpoint": "OK", "goat_advanced_endpoint": "OK",
            "advanced_records_in_first_page": len(advanced["data"]),
            "verified_at": utcnow(), "provider_calls": client.calls,
            "odds_coverage_verified": False, "betting_status": "NO BET"}


def windows(start: str, end: str, chunk_days: int = 14):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a > b or (b - a).days > 100:
        raise ValueError("Historical window must be ordered and at most 101 calendar days")
    if b >= date.today():
        raise ValueError("Historical backfill must end before today (completed games only)")
    if not 1 <= chunk_days <= 31:
        raise ValueError("chunk_days must be 1..31")
    while a <= b:
        e = min(a + timedelta(days=chunk_days - 1), b)
        yield a.isoformat(), e.isoformat()
        a = e + timedelta(days=1)


def audit(con: sqlite3.Connection, start: str, end: str) -> dict:
    conditions = (start, end)
    games = con.execute("SELECT COUNT(*) FROM games WHERE game_date BETWEEN ? AND ?", conditions).fetchone()[0]
    finals = con.execute("SELECT COUNT(*) FROM games WHERE game_date BETWEEN ? AND ? AND status='final'", conditions).fetchone()[0]
    stats = con.execute("""SELECT COUNT(*) FROM player_games
                         WHERE game_date BETWEEN ? AND ?""", conditions).fetchone()[0]
    distinct = con.execute("""SELECT COUNT(DISTINCT game_date) FROM player_games
                            WHERE game_date BETWEEN ? AND ?""", conditions).fetchone()[0]
    players = con.execute("""SELECT COUNT(*) FROM (
        SELECT player_id FROM player_games WHERE game_date BETWEEN ? AND ?
        GROUP BY player_id HAVING COUNT(*) >= 20)""", conditions).fetchone()[0]
    unresolved = con.execute("""SELECT COUNT(*) FROM player_games p LEFT JOIN games g ON p.game_id=g.id
                              WHERE g.id IS NULL""").fetchone()[0]
    validity = con.execute("PRAGMA integrity_check").fetchone()[0]
    return {"games": games, "final_games": finals, "player_game_rows": stats,
            "distinct_stat_dates": distinct, "players_with_20_plus_games_in_window": players,
            "orphan_player_game_rows": unresolved, "sqlite_integrity": validity,
            "betting_status": "NO BET", "audited_at": utcnow()}


def backfill(client: TrialClient, database: str, start: str, end: str,
             chunk_days: int = 14, audit_json: str | None = None) -> dict:
    periods = list(windows(start, end, chunk_days))
    con = connect(database)
    batches = []
    try:
        for i, (begin, finish) in enumerate(periods, 1):
            print(f"Batch {i}/{len(periods)}: {begin} through {finish}", flush=True)
            result = ingest_bdl(client, con, begin, finish, utcnow())
            batches.append({"window": [begin, finish], **result})
            print(f"Batch completed: {result['games']} games, "
                  f"{result['final_player_game_records']} player-game records", flush=True)
        check = audit(con, start, end)
        if check['sqlite_integrity'] != 'ok' or check['orphan_player_game_rows']:
            raise ValueError("Imported SQLite data did not pass integrity checks")
        if not check['player_game_rows']:
            raise DataSourceError("No licensed player-game rows returned; cannot train")
        report = {"provider": "balldontlie", "start": start, "end": end,
                  "requests": client.calls, "batches": batches, "audit": check}
        if audit_json:
            path = Path(audit_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    finally:
        con.close()


def main(argv=None):
    p = argparse.ArgumentParser(description="GOAT trial: verify access or import real historical NBA player stats")
    p.add_argument("action", choices=["probe", "backfill"])
    p.add_argument("--start", default="2025-12-01")
    p.add_argument("--end", default="2026-02-28")
    p.add_argument("--db", default="data/goat-trial.sqlite")
    p.add_argument("--report", default="reports/goat-trial-audit.json")
    p.add_argument("--spacing-seconds", type=float, default=18.0)
    args = p.parse_args(argv)
    # Validate dates and credential before making a single billable provider request.
    if args.action == "backfill":
        list(windows(args.start, args.end))
    client = TrialClient(spacing_seconds=args.spacing_seconds)
    if args.action == "probe":
        result = probe(client)
    else:
        result = backfill(client, args.db, args.start, args.end, audit_json=args.report)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
