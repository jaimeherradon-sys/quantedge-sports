"""Strict chronological features. Rolling values exclude the row being predicted."""
from __future__ import annotations
import numpy as np
import pandas as pd

TARGETS = {"player_points": "points", "player_rebounds": "rebounds", "player_assists": "assists"}
WINDOWS = (5, 10, 20)
COLS = ["home", "rest_days"] + [f"{s}_{w}" for s in ("points", "rebounds", "assists", "minutes") for w in WINDOWS]


def from_db(con) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM player_games ORDER BY game_date,game_id,player_id", con)


def training_rows(history: pd.DataFrame) -> pd.DataFrame:
    """One row per completed player-game; no target value from future events enters X."""
    if history.empty:
        return pd.DataFrame(columns=list(history.columns) + COLS)
    h = history.copy()
    h["game_date"] = pd.to_datetime(h["game_date"])
    h = h.sort_values(["player_id", "game_date", "game_id"]).reset_index(drop=True)
    grp = h.groupby("player_id", sort=False)
    h["rest_days"] = (grp["game_date"].diff().dt.days - 1).clip(lower=0)
    for stat in ("points", "rebounds", "assists", "minutes"):
        for w in WINDOWS:
            h[f"{stat}_{w}"] = grp[stat].transform(lambda s: s.shift(1).rolling(w, min_periods=w).mean())
    h = h.dropna(subset=COLS)
    return h.sort_values(["game_date", "game_id", "player_id"]).reset_index(drop=True)


def future_row(history: pd.DataFrame, player_id: int, game_date: str, game_id: int, home: bool):
    h = history.loc[history["player_id"] == player_id].copy()
    if h.empty:
        return None
    cutoff = pd.Timestamp(game_date)
    h["game_date"] = pd.to_datetime(h["game_date"])
    h = h[h["game_date"] < cutoff].sort_values(["game_date", "game_id"])
    if len(h) < 20:
        return None
    row = {"player_id": player_id, "game_id": game_id, "game_date": cutoff,
           "home": int(home), "rest_days": max(0, (cutoff - h.iloc[-1]["game_date"]).days - 1)}
    for stat in ("points", "rebounds", "assists", "minutes"):
        for w in WINDOWS:
            row[f"{stat}_{w}"] = float(h[stat].tail(w).mean())
    return row
