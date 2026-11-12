"""SQLite snapshot store; final game rows are immutable factual observations.

Historical odds are never backfilled from a later snapshot. API date stamps are UTC.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY, game_date TEXT NOT NULL, starts_at TEXT,
  home_id INTEGER NOT NULL, away_id INTEGER NOT NULL,
  home_name TEXT NOT NULL, away_name TEXT NOT NULL,
  status TEXT NOT NULL, home_score INTEGER, away_score INTEGER,
  source TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_games (
  game_id INTEGER NOT NULL, player_id INTEGER NOT NULL, player_name TEXT NOT NULL,
  team_id INTEGER NOT NULL, game_date TEXT NOT NULL, starts_at TEXT,
  home INTEGER NOT NULL, minutes REAL NOT NULL,
  points INTEGER NOT NULL, rebounds INTEGER NOT NULL, assists INTEGER NOT NULL,
  threes INTEGER NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
  PRIMARY KEY(game_id,player_id), FOREIGN KEY(game_id) REFERENCES games(id)
);
CREATE INDEX IF NOT EXISTS ix_player_history ON player_games(player_id,game_date);
CREATE TABLE IF NOT EXISTS odds (
  event_id TEXT NOT NULL, game_id INTEGER, commence_time TEXT NOT NULL,
  bookmaker TEXT NOT NULL, player_name TEXT NOT NULL, market TEXT NOT NULL,
  side TEXT NOT NULL, line REAL NOT NULL, price REAL NOT NULL,
  quote_at TEXT NOT NULL, fetched_at TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY(event_id,bookmaker,player_name,market,side,line,quote_at)
);
CREATE INDEX IF NOT EXISTS ix_odds_event ON odds(game_id,quote_at);
CREATE TABLE IF NOT EXISTS injuries (
  player_id INTEGER NOT NULL, player_name TEXT NOT NULL, status TEXT NOT NULL,
  detail TEXT, snapshot_at TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY(player_id,snapshot_at)
);
CREATE TABLE IF NOT EXISTS projections (
  game_id INTEGER NOT NULL, player_id INTEGER NOT NULL, market TEXT NOT NULL,
  player_name TEXT NOT NULL, estimate REAL NOT NULL, generated_at TEXT NOT NULL,
  model_name TEXT NOT NULL, model_asof TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY(game_id,player_id,market,generated_at)
);
CREATE TABLE IF NOT EXISTS signals (
  game_id INTEGER NOT NULL, player_name TEXT NOT NULL, market TEXT NOT NULL,
  side TEXT NOT NULL, line REAL NOT NULL, bookmaker TEXT NOT NULL, price REAL NOT NULL,
  probability REAL NOT NULL, p_low REAL NOT NULL, p_high REAL NOT NULL,
  implied REAL NOT NULL, ev REAL NOT NULL, ev_lower REAL NOT NULL,
  status TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(game_id,player_name,market,side,line,bookmaker,created_at)
);
"""


def connect(db_path: str):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def minute_value(value) -> float:
    if value is None or value == "":
        return 0.0
    parts = str(value).split(":")
    if len(parts) == 2:
        return float(parts[0]) + float(parts[1]) / 60
    return float(parts[0])


def ingest_bdl(client, con, start: str, end: str, fetched_at: str) -> dict:
    """Transactional import. No partial committed data if a source fails mid-pagination."""
    games = list(client.games(start, end))
    stats = list(client.player_stats(start, end))
    indexed = {}
    with con:
        for g in games:
            g_id = int(g["id"])
            status = str(g.get("status_state", "unknown"))
            home = g.get("home_team", {})
            away = g.get("visitor_team", {})
            if not (home.get("id") and away.get("id") and home.get("full_name") and away.get("full_name")):
                raise ValueError(f"Invalid game metadata: {g_id}")
            indexed[g_id] = g
            con.execute("""INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET status=excluded.status, starts_at=excluded.starts_at,
              home_score=excluded.home_score,away_score=excluded.away_score,fetched_at=excluded.fetched_at""",
              (g_id, g["date"], g.get("datetime"), home["id"], away["id"],
               home["full_name"], away["full_name"], status, g.get("home_team_score"),
               g.get("visitor_team_score"), "balldontlie", fetched_at))
        count = 0
        for s in stats:
            g_id = int(s["game"]["id"])
            g = indexed.get(g_id)
            # Strict: only a verified final and a positive participation record.
            if not g or g.get("status_state") != "final":
                continue
            mins = minute_value(s.get("min"))
            if mins <= 0:
                continue
            player, team = s["player"], s["team"]
            if any(s.get(k) is None for k in ("pts", "reb", "ast", "fg3m")):
                continue
            con.execute("""INSERT INTO player_games VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(game_id,player_id) DO UPDATE SET
               minutes=excluded.minutes,points=excluded.points,rebounds=excluded.rebounds,
               assists=excluded.assists,threes=excluded.threes,fetched_at=excluded.fetched_at""",
               (g_id, int(player["id"]), f'{player["first_name"]} {player["last_name"]}',
                int(team["id"]), g["date"], g.get("datetime"),
                int(int(team["id"]) == int(g["home_team"]["id"])), mins,
                int(s["pts"]), int(s["reb"]), int(s["ast"]), int(s["fg3m"]),
                "balldontlie", fetched_at))
            count += 1
    return {"games": len(games), "final_player_game_records": count, "fetched_at": fetched_at}


def ingest_injuries(client, con, fetched_at: str) -> int:
    entries = list(client.injuries())
    with con:
        for e in entries:
            p = e["player"]
            con.execute("INSERT OR REPLACE INTO injuries VALUES(?,?,?,?,?,?)",
                        (int(p["id"]), f'{p["first_name"]} {p["last_name"]}',
                         e.get("status") or "Unknown", e.get("description"), fetched_at, "balldontlie"))
    return len(entries)


def save_odds_snapshot(client, con, fetched_at: str, region="us") -> dict:
    """Only exact scheduled BDL game/team matching; no unverified cross-provider join."""
    from sports_betting_ai.utils import norm_name, parse_utc
    events = client.events()
    known = con.execute("SELECT * FROM games").fetchall()
    n = 0
    with con:
        for event in events:
            starts = event.get("commence_time")
            if not starts:
                continue
            matches = [g for g in known if norm_name(g["home_name"]) == norm_name(event.get("home_team", ""))
                       and norm_name(g["away_name"]) == norm_name(event.get("away_team", ""))
                       and g["starts_at"] and abs((parse_utc(g["starts_at"]) - parse_utc(starts)).total_seconds()) < 24*3600]
            if len(matches) != 1:
                continue
            game_id = matches[0]["id"]
            payload = client.event_props(str(event["id"]), regions=region)
            for bookmaker in payload.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    kind = market.get("key")
                    if kind not in ("player_points", "player_rebounds", "player_assists"):
                        continue
                    quote_at = market.get("last_update") or bookmaker.get("last_update")
                    if not quote_at or parse_utc(quote_at) > parse_utc(fetched_at):
                        continue
                    for outcome in market.get("outcomes", []):
                        if outcome.get("name") not in ("Over", "Under") or not outcome.get("description"):
                            continue
                        try:
                            price, line = float(outcome["price"]), float(outcome["point"])
                        except (ValueError, TypeError, KeyError):
                            continue
                        if price <= 1 or line < 0 or line % 1 == 0:
                            # Integer player-prop lines can push; MVP supports half-lines only.
                            continue
                        con.execute("""INSERT OR IGNORE INTO odds
                          (event_id,game_id,commence_time,bookmaker,player_name,market,side,line,price,quote_at,fetched_at,source)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (str(event["id"]), game_id, starts, bookmaker["key"],
                           outcome["description"], kind, outcome["name"].lower(),
                           line, price, quote_at, fetched_at, "the-odds-api"))
                        n += 1
    return {"events_seen": len(events), "quotes_processed": n, "fetched_at": fetched_at}


def record_source_check(con, provider: str, category: str, checked_at: str):
    with con:
        con.execute("""CREATE TABLE IF NOT EXISTS source_checks (
          provider TEXT NOT NULL, category TEXT NOT NULL, checked_at TEXT NOT NULL,
          PRIMARY KEY(provider,category,checked_at))""")
        con.execute("INSERT OR IGNORE INTO source_checks VALUES(?,?,?)", (provider, category, checked_at))


def latest_source_check(con, provider: str, category: str):
    con.execute("""CREATE TABLE IF NOT EXISTS source_checks (
          provider TEXT NOT NULL, category TEXT NOT NULL, checked_at TEXT NOT NULL,
          PRIMARY KEY(provider,category,checked_at))""")
    row = con.execute("SELECT MAX(checked_at) AS checked_at FROM source_checks WHERE provider=? AND category=?",
                      (provider, category)).fetchone()
    return row["checked_at"] if row else None

FOOTBALL_SCHEMA = """
CREATE TABLE IF NOT EXISTS football_matches (
 id INTEGER PRIMARY KEY, competition TEXT NOT NULL, season INTEGER NOT NULL,
 starts_at TEXT NOT NULL, home_team_id INTEGER NOT NULL, away_team_id INTEGER NOT NULL,
 home_team TEXT NOT NULL, away_team TEXT NOT NULL,
 status TEXT NOT NULL, home_goals INTEGER, away_goals INTEGER,
 source TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_football_league_date ON football_matches(competition,starts_at);
"""


def ingest_football(client, con, competition: str, season: int, fetched_at: str) -> dict:
    matches = list(client.matches(competition, season))
    con.executescript(FOOTBALL_SCHEMA)
    n = 0
    with con:
        for m in matches:
            home, away = m.get("homeTeam", {}), m.get("awayTeam", {})
            if not (m.get("utcDate") and home.get("id") and away.get("id") and
                    home.get("name") and away.get("name")):
                continue
            status = str(m.get("status", "UNKNOWN"))
            goals = (m.get("score") or {}).get("fullTime") or {}
            hg, ag = (goals.get("home"), goals.get("away"))
            if status != "FINISHED":
                hg, ag = None, None
            if status == "FINISHED" and (hg is None or ag is None):
                continue
            con.execute("""INSERT INTO football_matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET status=excluded.status,home_goals=excluded.home_goals,
            away_goals=excluded.away_goals,fetched_at=excluded.fetched_at""",
            (int(m["id"]), competition, season, m["utcDate"], int(home["id"]), int(away["id"]),
             home["name"],away["name"],status,hg,ag,"football-data.org",fetched_at))
            n += 1
    return {"competition":competition,"matches_ingested":n,"fetched_at":fetched_at}
