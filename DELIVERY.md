# Delivery / verification record — 2026-11-12

## Delivered

- Python package (`src/sports_betting_ai`) + local SQLite research storage
- BALLDONTLIE and The Odds API interfaces, plus football-data.org football fixtures
- PTS/REB/AST NBA point estimates and conditional probabilities with time-based model selection
- Provenance and conservative NO BET screening; paper-only backtest with execution cost
- Correlation-aware historical-joint sample bootstrap up to 100,000 draws
- Separate uncalibrated football 1X2/BTTS score-model baseline
- Streamlit dashboard source (UI not launched in this environment)
- GitHub Actions CI and twice-daily research workflows, contingent on repository and Secrets
- Tests (synthetic fixtures intentionally never presented as real sports observations)

## Local verification

- `PYTHONPATH=src pytest -q` — 16 tests passed
- `python -m compileall -q src dashboard.py` — passed
- `pip install -e . --no-deps --no-build-isolation` — passed with already installed Python deps
- `sbai --db <empty.db> backtest` — 0 bets, ROI null (no invented performance)
- `sbai --db <empty.db> daily --date 2026-11-12` — NO BET, 0 projections (no invented data)

## Not verified and not claimed

No `BDL_API_KEY`, `ODDS_API_KEY` or `FOOTBALL_DATA_TOKEN` credentials are available in this execution environment; therefore no authorized protected API endpoints could be successfully called using user credentials. Connection client request formats were checked against provider documentation and simulated integration tests, **not real network calls**. Streamlit is not installed here, so its source is provided but runtime UI not tested. No real basketball predictions, official starting lineups, betting odds, ROI, or profitability are claimed.

The linked GitHub account `jaimeherradon-sys` listed zero accessible repositories; no commit/push was performed. Upload this project to a new or explicitly authorized repository after granting GitHub connector access.

## Known MVP limitations

- Available published sports data can have restrictive terms; NBA.com data is **not** ingested because NBA.com forbids gambling-related use without authorization.
- Probability intervals are heuristic bootstraps; statistical coverage is not formally calibrated.
- Actual historical betting ROI cannot be measured until genuine event-time odds, injury availability, pre-event forecast snapshots and outcomes are collected. Current backtesting is prospective paper-only.
- Football goal model is a baseline and explicitly NO BET; no football odds connector or production historical calibration yet.
- No live wager execution is implemented.
