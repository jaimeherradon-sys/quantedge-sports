"""Walk-forward model comparison; untouched chronological test block.

Scores refer to fixed *training-set* milestone thresholds. They are not
historical betting returns. Final deployed models are fit on all available
historical rows after model-selection and holdout evaluation.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import joblib
import numpy as np
from scipy.stats import poisson
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import TimeSeriesSplit
from sports_betting_ai.features import COLS, TARGETS, training_rows
from sports_betting_ai.distributions import fit_alpha, over_probability


class RollingBaseline:
    def __init__(self, target):
        self.column = target + "_20"

    def fit(self, X, y):
        return self

    def predict(self, X):
        # Column order defined in COLS.
        return np.maximum(0.01, np.asarray(X)[:, COLS.index(self.column)])


def factory(name: str, target: str):
    if name == "rolling20":
        return RollingBaseline(target)
    if name == "poisson_regression":
        return make_pipeline(StandardScaler(), PoissonRegressor(alpha=3.0, max_iter=300))
    if name == "hist_gradient_boosting":
        return HistGradientBoostingRegressor(loss="poisson", max_iter=130,
                                            learning_rate=0.05, max_leaf_nodes=15,
                                            min_samples_leaf=30, random_state=42)
    if name == "xgboost":
        from xgboost import XGBRegressor
        return XGBRegressor(objective="count:poisson", n_estimators=170,
                            max_depth=3, learning_rate=0.05, subsample=0.85,
                            colsample_bytree=0.9, n_jobs=2, random_state=42)
    if name == "lightgbm":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(objective="poisson", n_estimators=150, max_depth=4,
                             num_leaves=15, learning_rate=0.05, verbosity=-1,
                             random_state=42, n_jobs=2)
    raise ValueError(f"Unknown model {name}")


def available_names():
    names = ["rolling20", "poisson_regression", "hist_gradient_boosting"]
    try:
        import xgboost  # noqa
        names.append("xgboost")
    except ImportError:
        pass
    try:
        import lightgbm  # noqa
        names.append("lightgbm")
    except ImportError:
        pass
    return names


def ece(probs, actual, bins=10):
    probs, actual = np.asarray(probs), np.asarray(actual)
    value = 0.0
    for start in np.linspace(0, 1, bins, endpoint=False):
        mask = (probs >= start) & (probs < start + 1 / bins)
        if start + 1 / bins == 1:
            mask |= probs == 1
        if mask.any():
            value += mask.mean() * abs(probs[mask].mean() - actual[mask].mean())
    return float(value)


def score_model(model, X_tr, y_tr, X_te, y_te, threshold):
    model.fit(X_tr, y_tr)
    fitted = np.clip(model.predict(X_tr), 0.01, None)
    alpha = fit_alpha(y_tr, fitted)
    predicted = np.clip(model.predict(X_te), 0.01, None)
    probs = np.clip([over_probability(float(p), float(threshold), alpha)
                     for p in predicted], 1e-6, 1 - 1e-6)
    actual = (y_te > threshold).astype(int)
    bins = []
    for lower in np.linspace(0, 1, 10, endpoint=False):
        selected = (probs >= lower) & (probs < lower + 0.1)
        if lower > .89:
            selected |= probs == 1
        if selected.any():
            bins.append({"predicted":float(probs[selected].mean()),
                         "observed":float(actual[selected].mean()),
                         "count":int(selected.sum())})
    return {"brier": float(brier_score_loss(actual, probs)),
            "logloss": float(log_loss(actual, probs, labels=[0, 1])),
            "ece": ece(probs, actual), "n": len(actual), "alpha": alpha,
            "reliability": bins}


def _metrics_for_name(rows, target, name, date_splits):
    stats = []
    for train_idx, valid_idx in date_splits:
        train, valid = rows.iloc[train_idx], rows.iloc[valid_idx]
        cutoff = int(np.median(train[target]))
        stats.append(score_model(factory(name, target), train[COLS].to_numpy(),
                                 train[target].to_numpy(), valid[COLS].to_numpy(),
                                 valid[target].to_numpy(), cutoff))
    return {"brier": float(np.average([m["brier"] for m in stats], weights=[m["n"] for m in stats])),
            "logloss": float(np.average([m["logloss"] for m in stats], weights=[m["n"] for m in stats])),
            "ece": float(np.average([m["ece"] for m in stats], weights=[m["n"] for m in stats])),
            "validation_rows": int(sum(m["n"] for m in stats))}


def train(history, out_dir: str, *, min_rows=600, only=None) -> dict:
    rows = training_rows(history)
    if len(rows) < min_rows or rows["game_date"].nunique() < 60:
        raise ValueError("Insufficient legitimate historical games for temporal training")
    dates = np.array(sorted(rows["game_date"].unique()))
    first_holdout = int(len(dates) * 0.8)
    development = rows[rows["game_date"] < dates[first_holdout]].copy()
    test = rows[rows["game_date"] >= dates[first_holdout]].copy()
    dev_dates = np.array(sorted(development["game_date"].unique()))
    splitter = TimeSeriesSplit(n_splits=3)
    splits = [(np.where(development["game_date"].isin(dev_dates[a]))[0],
               np.where(development["game_date"].isin(dev_dates[b]))[0])
              for a, b in splitter.split(dev_dates)]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    summaries = {}
    for market, target in TARGETS.items():
        if only and market not in only:
            continue
        scores = {}
        for name in available_names():
            try:
                scores[name] = _metrics_for_name(development, target, name, splits)
            except (ValueError, ImportError, RuntimeError) as exc:
                scores[name] = {"error": type(exc).__name__}
        good = {k: v for k, v in scores.items() if "logloss" in v}
        if not good:
            raise ValueError(f"No valid models for {market}")
        winner = min(good, key=lambda k: good[k]["logloss"])
        cutoff = int(np.median(development[target]))
        winner_test = score_model(factory(winner, target), development[COLS].to_numpy(),
                                  development[target].to_numpy(), test[COLS].to_numpy(),
                                  test[target].to_numpy(), cutoff)
        baseline_test = score_model(factory("rolling20", target), development[COLS].to_numpy(),
                                    development[target].to_numpy(), test[COLS].to_numpy(),
                                    test[target].to_numpy(), cutoff)
        # These gates are explicitly empirical, not a guarantee of profitability.
        validated = (len(test) >= 150 and winner_test["ece"] < 0.08
                     and winner_test["logloss"] <= baseline_test["logloss"] + 0.02)
        final_model = factory(winner, target)
        X, y = rows[COLS].to_numpy(), rows[target].to_numpy()
        final_model.fit(X, y)
        alpha = fit_alpha(y, np.clip(final_model.predict(X), 0.01, None))
        meta = {"market": market, "selected": winner, "asof_game_date": str(rows["game_date"].max().date()),
                "n_train": len(rows), "test_start": str(dates[first_holdout])[:10],
                "out_of_sample_adequate": bool(validated), "test": winner_test,
                "test_baseline": baseline_test, "walk_forward": scores,
                "threshold_note": "Scores use training-only median milestone, NOT historical bookmaker lines",
                "uncertainty_note": "Player bootstrap interval is heuristic, not calibrated coverage"}
        joblib.dump({"model": final_model, "alpha": alpha, "metadata": meta},
                    Path(out_dir) / f"{market}.joblib")
        summaries[market] = meta
    (Path(out_dir) / "validation.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    return summaries


def load_model(out_dir: str, market: str):
    path = Path(out_dir) / f"{market}.joblib"
    if not path.exists():
        return None
    return joblib.load(path)
