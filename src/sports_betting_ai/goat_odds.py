"""Auditable NBA GOAT market snapshots; NOT a betting recommendation engine.

BALDONTLIE 2026 API: /v2/odds and /v2/odds/player_props are current
quotes; /nba/v2/odds/opening and /nba/v2/odds/player_props/opening
are historical OPENING quotes, not complete past line movement.

All provider timestamps are preserved separately from acquisition timestamps.
No values are synthesized when lines/odds/timestamps are absent.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
import time
from pathlib import Path
import sqlite3

from sports_betting_ai.connectors import BallDontLie, DataSourceError, utcnow
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class TrialClient(BallDontLie):
    """At most one logical request per 18 seconds; use no concurrent BDL workflows."""
    def __init__(self, *args, spacing_seconds=18.0, clock=None, sleeper=None, **kwargs):
        if spacing_seconds < 15.0:
            raise ValueError("At least 15 seconds between trial calls")
        super().__init__(*args, **kwargs)
        # Avoid unthrottled internal retries during the five-requests/minute trial.
        if hasattr(self.session, "mount"):
            self.session.mount("https://", HTTPAdapter(max_retries=Retry(total=0)))
        self.spacing = float(spacing_seconds)
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.next_call_at = None

    def get(self, path: str, params=None):
        now = self.clock()
        if self.next_call_at is not None and now < self.next_call_at:
            self.sleeper(self.next_call_at - now)
        self.next_call_at = self.clock() + self.spacing
        print(f"BALLDONTLIE request {path}", flush=True)
        return super().get(path, params=params)


SOURCE = "balldontlie"
PROP_TYPES = frozenset({
    "points", "rebounds", "assists", "threes", "points_rebounds_assists",
    "points_rebounds", "points_assists", "rebounds_assists", "blocks", "steals",
})

DDL = """
CREATE TABLE IF NOT EXISTS goat_games (
 game_id INTEGER PRIMARY KEY, game_date TEXT NOT NULL, starts_at TEXT NOT NULL,
 home_name TEXT NOT NULL, away_name TEXT NOT NULL, status TEXT NOT NULL,
 fetched_at TEXT NOT NULL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goat_odds_raw (
 id INTEGER PRIMARY KEY AUTOINCREMENT, request_path TEXT NOT NULL,
 request_params TEXT NOT NULL, fetched_at TEXT NOT NULL, response_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goat_odds_quotes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL CHECK(kind IN ('live','opening')),
 scope TEXT NOT NULL CHECK(scope IN ('game','player')),
 game_id INTEGER NOT NULL REFERENCES goat_games(game_id),
 player_id INTEGER, vendor TEXT NOT NULL, market TEXT NOT NULL,
 market_type TEXT NOT NULL, side TEXT NOT NULL, line REAL,
 american INTEGER NOT NULL, decimal_odds REAL NOT NULL,
 implied_probability REAL NOT NULL, quote_at TEXT NOT NULL,
 observed_at TEXT NOT NULL, pregame INTEGER NOT NULL CHECK(pregame IN (0,1)),
 source TEXT NOT NULL, endpoint TEXT NOT NULL,
 UNIQUE(kind,scope,game_id,player_id,vendor,market,market_type,side,line,
        american,quote_at,observed_at)
);
CREATE INDEX IF NOT EXISTS ix_goat_quotes_game ON goat_odds_quotes(game_id,kind,scope);
CREATE INDEX IF NOT EXISTS ix_goat_quotes_player ON goat_odds_quotes(player_id,market,quote_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_goat_quote_identity ON goat_odds_quotes(
 kind,scope,game_id,COALESCE(player_id,-1),vendor,market,market_type,side,
 COALESCE(line,-999999),american,quote_at,observed_at);
"""


def parse_utc(value: str) -> datetime:
    if not value:
        raise ValueError("Missing timestamp")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Naive timestamp: UTC offset required")
    return dt.astimezone(timezone.utc)


def as_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Timezone required")
    return dt.astimezone(timezone.utc).isoformat()


def american_to_decimal(value: object) -> float:
    """Converts American sportsbook prices, never decimal-form vendor values."""
    if value is None or isinstance(value, bool):
        raise ValueError("Missing American price")
    n = float(value)
    if not math.isfinite(n) or not n.is_integer() or abs(n) < 100:
        raise ValueError("Invalid American price")
    out = 1 + (n / 100 if n > 0 else 100 / abs(n))
    return round(out, 9)


def valid_line(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def no_vig_pair(a: float, b: float) -> tuple[float, float]:
    if not all(math.isfinite(x) and x > 1 for x in (a,b)):
        raise ValueError("Both decimal prices must exceed 1")
    x,y = 1/a,1/b
    return x/(x+y),y/(x+y)


def get_list(client: TrialClient, path: str, params: dict, *, paged: bool) -> tuple[list[dict],list[dict]]:
    """Return records and raw response envelopes; cursor support only where documented."""
    entries, envelopes = [], []
    seen = set()
    current = dict(params)
    for _ in range(100 if paged else 1):
        payload = client.get(path, params=current)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise DataSourceError(f"Unexpected odds response from {path}")
        envelopes.append({"path": path, "params": dict(current), "payload": payload, "received_at": utcnow()})
        entries.extend(payload["data"])
        cursor = payload.get("meta", {}).get("next_cursor") if paged else None
        if cursor is None:
            return entries,envelopes
        if str(cursor) in seen:
            raise DataSourceError("Repeating odds cursor")
        seen.add(str(cursor))
        current["cursor"] = cursor
    raise DataSourceError("Odd pagination exceeded 100 pages; refusing partial success")


def game_record(g: dict, retrieved_at: str) -> tuple | None:
    try:
        starts = parse_utc(g["datetime"])
        gid = int(g["id"])
        home = str(g["home_team"]["full_name"]).strip()
        away = str(g["visitor_team"]["full_name"]).strip()
        status = str(g.get("status_state") or "unknown").lower()
        gd = date.fromisoformat(str(g["date"])[:10]).isoformat()
        if not home or not away or gid <= 0 or home == away:
            return None
    except (TypeError,ValueError,KeyError,AttributeError):
        return None
    return (gid, gd, as_iso(starts), home, away, status, retrieved_at, SOURCE)


def game_odds_rows(row: dict, *, kind: str, observed_at: str, starts: datetime):
    try:
        gid = int(row["game_id"])
        vendor = str(row["vendor"]).strip().lower()
        quote_at = parse_utc(row["opened_at" if kind == "opening" else "updated_at"])
    except (KeyError,TypeError,ValueError):
        return
    if not vendor or quote_at > parse_utc(observed_at) or quote_at >= starts:
        return
    if kind == "live" and parse_utc(observed_at) >= starts:
        return
    fields = [
        ("moneyline", "home", None, row.get("moneyline_home_odds")),
        ("moneyline", "away", None, row.get("moneyline_away_odds")),
        ("spread", "home", valid_line(row.get("spread_home_value")), row.get("spread_home_odds")),
        ("spread", "away", valid_line(row.get("spread_away_value")), row.get("spread_away_odds")),
        ("total", "over", valid_line(row.get("total_value")), row.get("total_over_odds")),
        ("total", "under", valid_line(row.get("total_value")), row.get("total_under_odds")),
    ]
    for market, side, line, price in fields:
        if market in ("spread","total") and line is None:
            continue
        try:
            dec = american_to_decimal(price)
        except ValueError:
            continue
        yield (kind, "game", gid, None, vendor, market, market, side, line,
               int(float(price)), dec, 1/dec, as_iso(quote_at), observed_at, 1,
               SOURCE, "/nba/v2/odds/opening" if kind == "opening" else "/v2/odds")


def player_odds_rows(row: dict, *, kind: str, observed_at: str, starts: datetime):
    try:
        gid, pid = int(row["game_id"]), int(row["player_id"])
        vendor = str(row["vendor"]).strip().lower()
        prop = str(row["prop_type"]).strip().lower()
        market = row["market"]
        market_type = str(market["type"])
        line = valid_line(row.get("line_value"))
        quote_at = parse_utc(row["opened_at" if kind == "opening" else "updated_at"])
    except (KeyError,TypeError,ValueError):
        return
    if (gid <= 0 or pid <= 0 or not vendor or prop not in PROP_TYPES or line is None
        or line < 0 or quote_at > parse_utc(observed_at) or quote_at >= starts):
        return
    if kind == "live" and parse_utc(observed_at) >= starts:
        return
    if market_type == "over_under":
        sides = [("over",market.get("over_odds")),("under",market.get("under_odds"))]
    elif market_type == "milestone":
        sides = [("yes",market.get("odds"))]
    else:
        return
    for side, price in sides:
        try:
            dec = american_to_decimal(price)
        except ValueError:
            continue
        yield (kind, "player", gid, pid, vendor, prop, market_type, side, line,
               int(float(price)), dec, 1/dec, as_iso(quote_at), observed_at, 1,
               SOURCE, "/nba/v2/odds/player_props/opening" if kind == "opening" else "/v2/odds/player_props")


def _insert_raw(con: sqlite3.Connection, envelopes: list[dict]) -> None:
    con.executemany("INSERT INTO goat_odds_raw(request_path,request_params,fetched_at,response_json) VALUES (?,?,?,?)",
        [(e["path"], json.dumps(e["params"], sort_keys=True), e["received_at"],
          json.dumps(e["payload"], ensure_ascii=False, separators=(",",":"))) for e in envelopes])


def ingest(client: TrialClient, *, day: str, kind: str, db_path: str, max_games: int = 3, now=None) -> dict:
    if kind not in {"live","opening"}:
        raise ValueError("Only live or opening supported")
    requested_day = date.fromisoformat(day)
    if not 1 <= max_games <= 10:
        raise ValueError("max-games must be 1..10")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    if requested_day > now.date() + timedelta(days=2):
        raise ValueError("Do not request dates more than two days ahead")
    if kind == "opening" and requested_day >= now.date():
        raise ValueError("Opening backfill only for days before today")
    # BDL returns completed game rows with shared game IDs across stats and odds.
    raw_games = list(client.games(day, day))
    retrieved = utcnow()
    prepared = [game_record(g, retrieved) for g in raw_games]
    prepared = [g for g in prepared if g is not None and g[1] == day]
    if kind == "live":
        games = [g for g in prepared if parse_utc(g[2]) > now and g[5] not in ("final","in_progress")]
    else:
        games = [g for g in prepared if parse_utc(g[2]) < now and g[5] == "final"]
    games.sort(key=lambda r:(r[2],r[0]))
    games = games[:max_games]
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(DDL)
    try:
        with con:
            con.executemany("""INSERT INTO goat_games VALUES (?,?,?,?,?,?,?,?)
                 ON CONFLICT(game_id) DO UPDATE SET status=excluded.status,
                 fetched_at=excluded.fetched_at""",games)
        if not games:
            return {"status":"NO BET", "reason":"No eligible games for selected day/mode",
                    "games_seen":len(raw_games),"games_selected":0,"quote_rows":0,"date":day,"kind":kind}
        ids={g[0] for g in games}
        by_id={g[0]:parse_utc(g[2]) for g in games}
        gp = "/nba/v2/odds/opening" if kind=="opening" else "/v2/odds"
        gparams={"game_ids[]":sorted(ids),"per_page":100}
        game_rows,envs=get_list(client,gp,gparams,paged=True)
        with con:
            _insert_raw(con,envs)
            for g in game_rows:
                if not isinstance(g,dict) or g.get("game_id") not in ids:
                    continue
                normalized=list(game_odds_rows(g,kind=kind,observed_at=utcnow(),starts=by_id[g["game_id"]]))
                con.executemany("""INSERT OR IGNORE INTO goat_odds_quotes
                  (kind,scope,game_id,player_id,vendor,market,market_type,side,line,
                   american,decimal_odds,implied_probability,quote_at,observed_at,
                   pregame,source,endpoint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",normalized)
        pp = "/nba/v2/odds/player_props/opening" if kind=="opening" else "/v2/odds/player_props"
        for gid in sorted(ids):
            rows,envs=get_list(client,pp,{"game_id":gid},paged=False)
            with con:
                _insert_raw(con,envs)
                for item in rows:
                    if not isinstance(item,dict) or item.get("game_id") != gid:
                        continue
                    normalized=list(player_odds_rows(item,kind=kind,observed_at=utcnow(),starts=by_id[gid]))
                    con.executemany("""INSERT OR IGNORE INTO goat_odds_quotes
                      (kind,scope,game_id,player_id,vendor,market,market_type,side,line,
                       american,decimal_odds,implied_probability,quote_at,observed_at,
                       pregame,source,endpoint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",normalized)
        integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("SQLite integrity check failed")
        counts=dict(con.execute("SELECT market, COUNT(*) FROM goat_odds_quotes GROUP BY market"))
        vendors=dict(con.execute("SELECT vendor, COUNT(*) FROM goat_odds_quotes GROUP BY vendor"))
        pairs=con.execute("""SELECT COUNT(*) FROM (
            SELECT kind,game_id,player_id,vendor,market,line,quote_at,observed_at
            FROM goat_odds_quotes WHERE market_type='over_under'
            GROUP BY kind,game_id,player_id,vendor,market,line,quote_at,observed_at
            HAVING COUNT(DISTINCT side)=2
        )""").fetchone()[0]
        count=con.execute("SELECT COUNT(*) FROM goat_odds_quotes").fetchone()[0]
        return {"status":"NO BET", "reason":"Market acquisition only; no validated event-time player predictions",
                "source":SOURCE,"kind":kind,"date":day,"games_seen":len(raw_games),
                "games_selected":len(games),"game_ids":sorted(ids),"quote_rows":count,
                "by_market":counts,"by_vendor":vendors,"two_way_pairs":pairs,
                "raw_response_envelopes":con.execute("SELECT COUNT(*) FROM goat_odds_raw").fetchone()[0],
                "sqlite_integrity":integrity,"audited_at":utcnow()}
    finally:
        con.close()


def main(argv=None):
    p=argparse.ArgumentParser(description="BALLDONTLIE GOAT odds snapshots; research only, NO BET")
    p.add_argument("kind",choices=["live","opening"])
    p.add_argument("--date",default=date.today().isoformat(),help="NBA game date YYYY-MM-DD")
    p.add_argument("--db",default="data/goat-odds.sqlite")
    p.add_argument("--report",default="reports/goat-odds-summary.json")
    p.add_argument("--max-games",type=int,default=3)
    p.add_argument("--spacing-seconds",type=float,default=18)
    args=p.parse_args(argv)
    client=TrialClient(spacing_seconds=args.spacing_seconds)
    result=ingest(client,day=args.date,kind=args.kind,db_path=args.db,max_games=args.max_games)
    path=Path(args.report)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
