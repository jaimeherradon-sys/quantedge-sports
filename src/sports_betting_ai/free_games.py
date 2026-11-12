"""Import only NBA fixture and final score data available from licensed free API.

Never requests player-level stats or odds. Every observation includes source and
capture time. Missing results remain NULL, not zero; full pagination precedes commit.
"""
from __future__ import annotations
from datetime import date

from sports_betting_ai.connectors import utcnow


def ingest_free_games(client, con, start: str, end: str, fetched_at: str | None = None) -> dict:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last - first).days > 90:
        raise ValueError("Date interval must be ordered and <= 90 days")
    fetched_at = fetched_at or utcnow()
    raw_games = list(client.games(start, end))
    prepared = []
    seen = set()
    for item in raw_games:
        if not isinstance(item, dict):
            raise ValueError("Malformed game: not an object")
        game_id = int(item["id"])
        if game_id in seen:
            raise ValueError(f"Repeated game id in batch: {game_id}")
        seen.add(game_id)
        gd = str(item["date"])[:10]
        if not first <= date.fromisoformat(gd) <= last:
            raise ValueError(f"Game {game_id}: date outside requested period")
        home, away = item.get("home_team") or {}, item.get("visitor_team") or {}
        hid, aid = int(home["id"]), int(away["id"])
        hn, an = str(home["full_name"]).strip(), str(away["full_name"]).strip()
        if not hn or not an or hid == aid:
            raise ValueError(f"Game {game_id}: invalid teams")
        status = str(item.get("status_state") or "unknown").lower()
        if status == "final":
            if item.get("home_team_score") is None or item.get("visitor_team_score") is None:
                raise ValueError(f"Game {game_id}: final result missing scores")
            hs, vs = int(item["home_team_score"]), int(item["visitor_team_score"])
            if min(hs, vs) < 0:
                raise ValueError(f"Game {game_id}: negative score")
        else:
            hs, vs = None, None  # never interpret a live/unscheduled partial score as final
        prepared.append((game_id, gd, item.get("datetime"), hid, aid, hn, an,
                         status, hs, vs, "balldontlie", fetched_at))
    with con:
        con.execute("""CREATE TABLE IF NOT EXISTS game_snapshots (
          game_id INTEGER NOT NULL, fetched_at TEXT NOT NULL,
          game_date TEXT NOT NULL, status TEXT NOT NULL,
          home_score INTEGER, away_score INTEGER, source TEXT NOT NULL,
          PRIMARY KEY(game_id,fetched_at))""")
        for row in prepared:
            con.execute("""INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              game_date=excluded.game_date,starts_at=excluded.starts_at,
              home_id=excluded.home_id,away_id=excluded.away_id,
              home_name=excluded.home_name,away_name=excluded.away_name,
              status=excluded.status,home_score=excluded.home_score,
              away_score=excluded.away_score,source=excluded.source,
              fetched_at=excluded.fetched_at""", row)
            con.execute("""INSERT OR IGNORE INTO game_snapshots
              (game_id,fetched_at,game_date,status,home_score,away_score,source)
              VALUES(?,?,?,?,?,?,?)""",
              (row[0],row[11],row[1],row[7],row[8],row[9],row[10]))
    return {"provider": "balldontlie", "range_start": start, "range_end": end,
            "games_imported": len(prepared),
            "final_results": sum(row[7] == "final" for row in prepared),
            "scheduled_or_other": sum(row[7] != "final" for row in prepared),
            "player_stats_imported": 0, "fetched_at": fetched_at}
