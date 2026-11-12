"""Exploratory temporal validation on licensed NBA player-game history.

Never uses current bookmaker lines or places real bets. Model selection uses
development dates only; the final chronological block is reported, not tuned.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import warnings

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson
from sklearn.metrics import mean_absolute_error, mean_squared_error, brier_score_loss, log_loss
from sklearn.model_selection import TimeSeriesSplit

from sports_betting_ai.features import COLS, TARGETS, from_db, training_rows
from sports_betting_ai.model import factory, RollingBaseline
from sports_betting_ai.distributions import fit_alpha

RESEARCH_LINES = {"player_points": 9.5, "player_rebounds": 3.5, "player_assists": 1.5}
DEFAULT_MODELS = ["rolling20", "rolling5", "poisson_regression", "hist_gradient_boosting"]


class RollingFive(RollingBaseline):
    def __init__(self, target):
        self.column = target + "_5"


def get_model(name, target):
    return RollingFive(target) if name == "rolling5" else factory(name, target)


def probability(mean, line, alpha):
    mu = np.clip(np.asarray(mean, dtype=float), 1e-6, None)
    k = int(np.floor(line))
    if alpha <= 1e-8:
        return poisson.sf(k, mu)
    shape = 1.0 / alpha
    return nbinom.sf(k, shape, shape / (shape + mu))


def calibration(p, y, bins=10):
    records, ece = [], 0.0
    for i in range(bins):
        idx = (p >= i / bins) & (p < (i + 1) / bins if i < bins - 1 else p <= 1)
        if idx.any():
            avg, observed = float(p[idx].mean()), float(y[idx].mean())
            n = int(idx.sum())
            records.append({"bin": i, "count": n, "predicted": avg, "observed": observed})
            ece += n / len(y) * abs(avg - observed)
    return float(ece), records


def score(y, pred, p, line):
    actual = (y > line).astype(int)
    p = np.clip(p, 1e-7, 1 - 1e-7)
    cal_error, bins = calibration(p, actual)
    return {
        "n": int(len(y)),
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(np.sqrt(mean_squared_error(y, pred))),
        "brier": float(brier_score_loss(actual, p)),
        "log_loss": float(log_loss(actual, p, labels=[0, 1])),
        "ece_10_bins": cal_error,
        "event_frequency": float(actual.mean()),
        "mean_predicted_event_probability": float(p.mean()),
        "calibration": bins,
    }


def fit_and_predict(name, target, train, test, line):
    x_train, y_train = train[COLS].to_numpy(), train[target].to_numpy()
    x_test, y_test = test[COLS].to_numpy(), test[target].to_numpy()
    model = get_model(name, target)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        model.fit(x_train, y_train)
    alpha = fit_alpha(y_train, np.clip(model.predict(x_train), 0.01, None))
    pred = np.clip(model.predict(x_test), 0.01, None)
    probs = probability(pred, line, alpha)
    return model, alpha, score(y_test, pred, probs, line), pred, probs


def backtest_research(db, output, model_names=None, holdout_share=0.20):
    models = model_names or DEFAULT_MODELS
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity check failed")
    games = pd.read_sql_query("SELECT * FROM games", con)
    history = from_db(con)
    odds_count = int(con.execute("SELECT COUNT(*) FROM odds").fetchone()[0])
    injuries_count = int(con.execute("SELECT COUNT(*) FROM injuries").fetchone()[0])
    con.close()
    rows = training_rows(history)
    dates = np.array(sorted(rows.game_date.unique()))
    if len(rows) < 1500 or len(dates) < 35:
        raise ValueError("Insufficient observations or eligible historical dates")
    holdout_start = int(np.floor(len(dates) * (1 - holdout_share)))
    dev_dates, test_dates = dates[:holdout_start], dates[holdout_start:]
    development = rows[rows.game_date.isin(dev_dates)].copy()
    test = rows[rows.game_date.isin(test_dates)].copy()
    folds = []
    for tr, va in TimeSeriesSplit(n_splits=3).split(dev_dates):
        folds.append((development[development.game_date.isin(dev_dates[tr])],
                      development[development.game_date.isin(dev_dates[va])]))
    outcome = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "BALLDONTLIE GOAT, licensed user-supplied SQLite",
        "data_fetched_at_utc": str(history.fetched_at.max()),
        "data": {
            "games": int(len(games)),
            "final_games": int(sum(games.status.eq("final"))),
            "player_game_rows": int(len(history)),
            "unique_players": int(history.player_id.nunique()),
            "unique_teams": int(history.team_id.nunique()),
            "original_dates": int(history.game_date.nunique()),
            "eligible_rows": int(len(rows)),
            "eligible_dates": int(len(dates)),
            "development_rows": int(len(development)),
            "development_dates": len(dev_dates),
            "holdout_rows": int(len(test)),
            "holdout_dates": len(test_dates),
            "train_date_range": [str(dev_dates[0])[:10], str(dev_dates[-1])[:10]],
            "holdout_date_range": [str(test_dates[0])[:10], str(test_dates[-1])[:10]],
            "source_odds_rows": odds_count,
            "source_injuries_rows": injuries_count,
        },
        "method": "Three expanding date-based folds on development; untouched final 20% of eligible dates; lagged player windows 5/10/20",
        "markets": {},
        "betting_status": "NO BET",
        "limitations": [
            "Fixed count lines are research-only examples, not bookmaker prices",
            "Missing injury, lineup, projected minutes and pregame odds",
            "Brier and log loss do not establish a betting edge",
            "The 42 eligible dates in this archive are exploratory, not deployment-grade",
        ],
    }
    saved_predictions = []
    for market, target in TARGETS.items():
        line = RESEARCH_LINES[market]
        cv = {}
        for name in models:
            fold_metrics = []
            for train_fold, valid_fold in folds:
                _, _, met, _, _ = fit_and_predict(name, target, train_fold, valid_fold, line)
                fold_metrics.append(met)
            weights = [m["n"] for m in fold_metrics]
            cv[name] = {
                k: float(np.average([m[k] for m in fold_metrics], weights=weights))
                for k in ["mae", "rmse", "brier", "log_loss", "ece_10_bins"]
            }
            cv[name]["n_validation_rows"] = int(sum(weights))
        # Freeze this decision before evaluating any holdout target.
        selected = min(cv, key=lambda x: cv[x]["log_loss"])
        holdout = {}
        for name in models:
            model, alpha, met, predicted, prob = fit_and_predict(
                name, target, development, test, line)
            holdout[name] = {k: v for k, v in met.items() if k != "calibration"}
            holdout[name]["alpha_train_only"] = float(alpha)
            if name == selected:
                holdout[name]["calibration"] = met["calibration"]
                data = test[["game_id", "game_date", "player_id", "player_name", target]].copy()
                data["market"], data["research_line"] = market, line
                data["predicted_mean"], data["prob_over_line"] = predicted, prob
                saved_predictions.append(data)
                joblib.dump({
                    "model": model, "model_name": name, "market": market,
                    "alpha": alpha, "feature_columns": COLS,
                    "trained_through": str(dev_dates[-1])[:10], "research_only": True,
                }, out / f"{market}_holdout_research.joblib")
        outcome["markets"][market] = {
            "research_line_not_bookmaker_line": line,
            "selected_before_holdout": selected,
            "cv_validation": cv, "untouched_holdout": holdout,
            "holdout_calibration_bins": holdout[selected]["calibration"],
        }
        print(f"{market}: selected={selected}; brier={holdout[selected]['brier']:.4f}", flush=True)
    pd.concat(saved_predictions, ignore_index=True).to_csv(
        out / "historical_holdout_predictions.csv", index=False)
    (out / "research_validation.json").write_text(
        json.dumps(outcome, indent=2), encoding="utf-8")
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    for ax, market in zip(axes, outcome["markets"]):
        item = outcome["markets"][market]
        points = item["holdout_calibration_bins"]
        ax.plot([0, 1], [0, 1], "--", color="gray")
        ax.scatter([p["predicted"] for p in points],
                   [p["observed"] for p in points],
                   s=[max(12, p["count"] / 3) for p in points])
        ax.set(
            xlim=(0, 1), ylim=(0, 1), xlabel="Estimated probability",
            ylabel="Observed frequency",
            title=f'{market.replace("player_", "").title()} > {item["research_line_not_bookmaker_line"]}',
        )
        ax.grid(alpha=0.2)
    fig.suptitle("Historical calibration (not bookmaker lines or EV)")
    fig.tight_layout()
    fig.savefig(out / "historical_calibration.png", dpi=160)
    plt.close(fig)
    return outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args()
    summary = backtest_research(args.db, args.out, args.models)
    print(json.dumps({
        "data": summary["data"],
        "markets": {
            key: {"selected": value["selected_before_holdout"],
                  "holdout_brier": value["untouched_holdout"][value["selected_before_holdout"]]["brier"]}
            for key, value in summary["markets"].items()
        },
    }, indent=2))


if __name__ == "__main__":
    main()
