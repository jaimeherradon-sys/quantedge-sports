"""Regression: never bridge the 2025-26 / 2026-27 offseason."""
import pandas as pd
from sports_betting_ai.features import future_row, training_rows

def test_previous_season_is_not_last_20_for_new_season():
    old = pd.date_range("2026-01-01", periods=25, freq="D")
    current = pd.date_range("2026-10-20", periods=9, freq="D")
    rows = [
        {"player_id": 1, "game_id": idx + 1, "game_date": date.date().isoformat(),
         "home": idx % 2, "minutes": 30, "points": 20 if idx < 25 else 11,
         "rebounds": 5, "assists": 6}
        for idx, date in enumerate([*old, *current])
    ]
    history = pd.DataFrame(rows)
    data = training_rows(history)
    assert len(data[data.game_date >= pd.Timestamp("2026-10-20")]) == 0
    assert future_row(history, 1, "2026-10-29", 100, True) is None
    assert future_row(history, 1, "2026-01-26", 100, True) is not None
