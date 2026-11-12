# SPORTS BETTING AI · research MVP (v0.1)

**Status: NBA player props MVP (PTS/REB/AST), not a production betting engine.**
No connection credentials, odds or current NBA records are bundled; no fabricated sporting data. `NO BET` is the default whenever evidence is insufficient. Does **not** place any real bets. **18+ / gamble responsibly.**

## What works

1. BALLDONTLIE `/v1/games`, `/v1/stats` and `/v1/player_injuries` clients with cursor pagination, HTTP timeouts/retries and schema validation.
2. The Odds API `/v4/sports/basketball_nba/events` and per-event odds for PTS/REB/AST, exact match on team names and game start, data provenance + provider timestamps.
3. SQLite with finished player-game statistics, source snapshots, odds, injuries, pregame projections, and signals.
4. Leakage-free previous 5/10/20 game averages, home/away and rest days. A genuine temporal split: selection by three walk-forward folds on development data, 20% final untouched holdout. Baseline (rolling mean), Poisson GLM, histogram gradient boost; optional XGBoost and LightGBM.
5. Count distributions (Poisson or negative binomial based on observed training overdispersion), approximate bootstrapped probability *uncertainty* (NOT guaranteed CI coverage), Brier/log loss and expected calibration error (ECE).
6. Market-level model probability, implied probability, two-way no-vig when the paired same-book/same-time line exists, EV and conservative lower-bound EV. No edge or missing data => `NO BET`. Maximum 3 daily selections, one per game.
7. Prospective paper backtest grades **only** signals that were stored before tip-off; net ROI, hit rate, yield, drawdown, bankroll and CLV if an actual later quote exists. Pushes are handled. No post hoc reconstruction.
8. Optional empirical same-context joint bet probability, never naive multiplication for correlated picks; fixed-stake paper risk, fraction-Kelly helper with conservative caps.
9. Streamlit UI for data/projections/signals/paper backtest, GitHub CI and opt-in scheduled research workflow.

**Not yet implemented:** NBA game winner/spreads/team totals, triples and PRA models, paid advanced team/tracking/matchup feature ingestion, reliably projected minutes and confirmed starters ingestion, proper calibrated uncertainty intervals, correlated same-game Monte Carlo prediction from historical residuals, full retrospective odds backtesting and live football ingest. Football currently has a clearly marked *non-betting* independent-Poisson baseline only. All are future milestones, not claimed features.

## Install (Python 3.11 recommended)

```bash
## After downloading and extracting the ZIP, open a terminal in its folder
cd sports-betting-ai
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e '.[test,dashboard,ml]'
pytest -q
```

Create a personal `.env` or set environment variables locally (`.env` is not read automatically; export them in your shell). Never commit keys. Use GitHub Actions **Repository secrets** `BDL_API_KEY`, `ODDS_API_KEY` in hosted workflows.

```bash
# Linux/macOS example; use your own paid keys
export BDL_API_KEY='...'
export ODDS_API_KEY='...'

# Real connectivity checks: these FAIL if keys, tier or network are unavailable
sbai check --provider bdl
sbai check --provider bdl-stats
sbai check --provider odds

# Import real licensed historical and scheduled stats
sbai ingest --start 2025-10-01 --end 2026-11-12
sbai injuries
sbai odds --region us
sbai train
sbai daily --date 2026-11-12
sbai backtest
streamlit run dashboard.py
```

`sbai ingest` can make many requests and consume your subscription quota. Start with a smaller date range; model training requires 60 distinct historical game dates and at least 600 player-game examples with 20 prior games. A single season should generally contain enough observations when data coverage is comprehensive; not guaranteed. NBA games are associated with provider game dates. Automatic workflow uses a 100-day window as a bounded refresh and caches a local DB; GitHub cache is **not guaranteed persistent storage**. For production use PostgreSQL, durable object storage or a dedicated runner; backtest coverage must be checked for gaps. Secrets and schedules do not make API tiers free.

If you have no credentials, `pytest -q` works completely offline with **clearly synthetic unit test fixtures**, and `sbai daily` returns `NO BET` without inventing sports results.

## Explicit human verification of availability

You can optionally provide a **real** CSV after reviewing authorized injury and lineup sources:

```csv
game_id,player_id,status,projected_minutes,verified_at,source
```

The file must list verified player/game IDs, `status=confirmed_available`, realistic projected minutes, a real ISO-8601 UTC timestamp no older than 6 hours, and an auditable source. These values must come from real evidence; no example rows are included on purpose. The BDL injury feed must also have been refreshed within six hours. Even with this file, candidates require a validated model, recent odds (90 minutes), narrow bootstrap intervals and lower-bound EV exceeding 4 percentage points. Run `sbai daily --date YYYY-MM-DD --availability your-file.csv`. This is a conservative research gate, **not** a claim of verified starters.

## Methodology and safeguards

- `EV = p × decimal_odds - 1`. Never select based solely on high p. The no-vig calculation is for a same-line, same-book two-sided market; it does not replace the offered price in EV.
- Train/validation/test are separated chronologically by **game date**. Each player's rolling 5/10/20 features shift backward one completed game. Only facts before that target game are included. In daily predictions a model's training date must precede the event.
- Model selection uses Brier, log loss and ECE for a **training-selected count milestone**, **not** for bookmaker historical offers. Metrics can never be described as demonstrated edge against market.
- A model is marked temporarily valid only if holdout n≥150, ECE<0.08 and its log loss is within 0.02 of rolling baseline. This merely allows *screening*, not proof of profitability.
- Bootstrapped probability bounds are heuristic and not yet calibrated to 95% coverage. The signal gate intentionally uses their lower limit and may be overly optimistic; treat all candidates as manual research only.
- Backtest results are **prospective**: daily candidates must have been saved before the actual event. Without this, historic ROI is **not available**. Exclude data recorded after tipoff. Flat paper stake (default 1) and a simulated 0.5% execution drag.
- `fractional_kelly()` is an optional mathematical paper helper (default quarter Kelly, maximum 0.5% bankroll per selection). No real bookmaker integration; recommended portfolio limit 2% a day, not enforced unless implemented by caller.
- Combining same-game positions is blocked unless aligned joint historical observations are supplied; the empirical joint-probability module needs ≥200 matched observations.

## Architecture

```text
src/sports_betting_ai/
  connectors.py      # licensed BDL / The Odds API
  storage.py         # SQLite, provenance & transactions
  features.py        # shift(1) / rolling 5,10,20
  distributions.py   # Poisson/NB count probability + heuristic bootstrap
  model.py           # temporal walk-forward and holdout model selection
  value.py           # implied, vig, EV, uncertainty gates, Kelly
  daily.py           # projections / NO BET research report
  backtest.py        # genuinely as-of paper signal grading
  combinations.py   # validated historical joint probabilities
  football.py       # not-yet-operational score baseline
  cli.py             # command-line actions
dashboard.py         # Streamlit viewer
.github/workflows/   # CI + scheduled conditional refresh
tests/               # deterministic synthetic test fixtures (NOT league data)
docs/SOURCES.md      # verified data sources and permissions
```

## Planned milestones

1. Build and version independently licensed historical prop-odds + pregame injuries + confirmed projected rotations, then strict historical *event-time* replay and player/game mapping audits.
2. Estimate probabilities conditional on minutes, team pace, opponent defensive scheme, blowout risk, rest/travel; model availability uncertainty, compare baseline/XGB/LightGBM.
3. Properly calibrate intervals and models with out-of-sample temporal plots; measure holdout profitability and closing-line value by bookmaker and market. No threshold retuning on holdout.
4. Add joint NBA PRA, threes, totals, spreads, multi-leg correlated Monte Carlo, with covariance backtests and no-data safety fallback.
5. Add independent football ingestion, authorized fixture/xG/odds feeds, Dixon-Coles baseline and walk-forward scoring for 1X2, Asian handicap, totals and BTTS.
6. Replace CI cache with durable production DB and monitoring, ingestion alerts, data quality/lineup match audits, and reproducibility metadata.

See [data permissions](docs/SOURCES.md). No performance guarantee, no automated real-money wagering.

### Football research-only module

The separate football-data.org integration is now available for league scores and fixtures. It implements a shrinkage-adjusted independent-Poisson home/away goal baseline, outputs 1X2 and BTTS probabilities for all covered fixtures on a requested date, and **always returns `NO BET`** until historical odds, proper calibration, player availability and source licenses are verified. This is a research tool, **not** a completed football betting model.

```bash
export FOOTBALL_DATA_TOKEN='your-key'
sbai football-ingest --competition PL --season 2026
sbai football-daily --competition PL --date 2026-11-14
```

`PL` (Premier League), `PD` (La Liga), `BL1` (Bundesliga), `SA` (Serie A), `FL1` (Ligue 1) are documented example competition codes; availability depends on your plan. Do not infer xG from these observed-score lambdas: they are not shot-based expected-goals statistics.

Attribution required by provider: **Football data provided by the Football-Data.org API**. See provider terms, including use limits and subscription constraints.


## Free NBA data import (fixtures and final scores only)

With a BALLDONTLIE Free API key in `BDL_API_KEY` you can import real NBA games
without the paid player-statistics endpoint:

```bash
sbai games-free --days 7 --forward-days 2
```

This stores source, UTC capture time and an append-only `game_snapshots` trail.
An upcoming or incomplete game has NULL final scores. No NBA player PTS, REB,
AST or odds are available from this command. The outcome is **NO BET** until
paid/licensed player-level historical statistics, real market quotes and
proper out-of-sample validation are present.

Run the workflow manually at
`Actions → Import free NBA games (NO BET) → Run workflow`. It also runs once daily.
The **Actions artifact** includes the SQLite file for each run for up to 30 days;
it is not a durable database or a replacement for backups. Never commit API keys.
