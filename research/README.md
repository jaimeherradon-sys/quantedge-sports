# NBA historical exploratory model validation

This is an OFFLINE RESEARCH TOOL. It accepts a user-owned SQLite archive from the BALLDONTLIE GOAT API, evaluates historical box-score predictions, and never places bets.

## Run

Keep licensed source data private; NEVER commit it or API keys to this public repository.

    python -m pip install -e '.[test,research]'
    python -m pytest -q
    python -m research.evaluate_history --db data/goat-trial.sqlite --out reports/nba-research

Output: research_validation.json (temporal folds and untouched holdout), historical_holdout_predictions.csv (private observed records), historical_calibration.png (illustrative count lines), player_*_holdout_research.joblib (historical models, research only). Do not load untrusted joblib files or use these historical models to predict current NBA games.

## First GOAT archive audit (2026-11-12)

- 597 final NBA games; 12,849 player-game rows, 529 players, 30 teams.
- 2025-12-01 to 2026-02-28, 83 source dates.
- Sum of player points equals both teams' final scores in 597/597 games.
- 20-game lagged features yield 4,221 eligible player-game rows across 42 dates.
- Development: 3,071 records / 33 dates ending 2026-02-19. Untouched holdout: 1,150 records / 9 dates from 2026-02-20 to 2026-02-28.

| Illustrative count threshold (NOT offered lines) | Model selected in development | Holdout Brier | Log Loss | MAE |
|---|---|---:|---:|---:|
| PTS >9.5 | Poisson regression | 0.1729 | 0.5187 | 4.78 |
| REB >3.5 | Rolling 20 | 0.1967 | 0.5793 | 2.05 |
| AST >1.5 | Rolling 20 | 0.1802 | 0.5387 | 1.45 |

NO BET: This does not demonstrate profitability or superiority to bookmaker markets.

## Gaps

The production training gate requires 60 eligible historical dates; this dataset has only 42 after rolling features. Backfill earlier dates and add current 2026-27 season. Captured database has zero bookmaker odds and zero injury rows, so real EV and backtesting are impossible.

See issue #2: https://github.com/jaimeherradon-sys/quantedge-sports/issues/2

Source data and player-level holdout predictions stay private.
