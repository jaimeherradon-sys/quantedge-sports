"""Fail-closed audit for real GOAT odds snapshots; no betting signals.

This checks provenance, pregame timing, paired bookmaker markets and suspicious
cross-book line differences. It does NOT measure model win probabilities or EV+.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from statistics import median


def as_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Missing UTC offset")
    return result.astimezone(timezone.utc)


def audit_file(db_file: str) -> dict:
    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row
    try:
        games = {int(r["game_id"]): r for r in con.execute("SELECT * FROM goat_games")}
        quotes = [dict(r) for r in con.execute("SELECT * FROM goat_odds_quotes")]
        valid_pairs, errors, line_groups = [], [], defaultdict(list)
        buckets = defaultdict(dict)
        for q in quotes:
            qid = int(q["id"])
            game = games.get(int(q["game_id"]))
            if game is None:
                errors.append(f"Quote {qid}: missing event")
                continue
            try:
                start, quoted, observed = (as_utc(v) for v in
                    [game["starts_at"], q["quote_at"], q["observed_at"]])
                dec = float(q["decimal_odds"])
                implied = float(q["implied_probability"])
                if not quoted <= observed < start:
                    errors.append(f"Quote {qid}: not a pre-event observation")
                if int(q["pregame"]) != 1:
                    errors.append(f"Quote {qid}: not marked pregame")
                if dec <= 1.0 or not math.isfinite(dec) or not math.isclose(
                        implied, 1 / dec, abs_tol=1e-7):
                    errors.append(f"Quote {qid}: invalid price or implied probability")
            except (TypeError, ValueError, KeyError) as exc:
                errors.append(f"Quote {qid}: invalid timestamp/price ({type(exc).__name__})")
                continue
            scope = str(q["scope"])
            market = str(q["market"])
            line = q["line"]
            group_key = (int(q["game_id"]), scope, q["player_id"],
                         str(q["vendor"]), market, line)
            if q["side"] in ("over", "under", "home", "away"):
                buckets[group_key][q["side"]] = q
            if scope == "player" and q["market_type"] == "over_under" and q["side"] == "over":
                line_groups[(int(q["game_id"]), int(q["player_id"]), market)].append(
                    (str(q["vendor"]), float(line)))

        margins = []
        for group_key, sides in buckets.items():
            kind = group_key[4]
            required = ("home", "away") if kind in ("moneyline", "spread") else ("over", "under")
            if not all(s in sides for s in required):
                continue
            a, b = (float(sides[s]["implied_probability"]) for s in required)
            margin = a + b - 1
            valid_pairs.append((group_key, margin))
            if margin < -1e-5 or margin > 0.30:
                errors.append(f"Invalid two-way book margin: {group_key}")
            margins.append(margin)

        outliers = []
        # Flag markets with at least four distinct bookmakers and non-standard
        # main lines. A flagged quote is NOT proof of a bad provider response.
        for key, entries in line_groups.items():
            if len(set(v for v, line in entries)) < 4:
                continue
            center = median([line for v, line in entries])
            threshold = max(3.0, abs(center) * 0.25)
            for vendor, line in entries:
                if abs(line - center) > threshold:
                    outliers.append({"game_id": key[0], "player_id": key[1],
                                     "market": key[2], "vendor": vendor,
                                     "quoted_line": line, "peer_median_line": center,
                                     "difference": round(line-center, 3)})
        sample = sorted(outliers, key=lambda x: abs(x["difference"]), reverse=True)[:30]
        return {
            "status": "NO BET", "reason": "Market integrity report, no independent calibrated player probability or verified lineup",
            "data_provenance": "BALLDONTLIE GOAT; player/market price snapshots",
            "integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
            "games": len(games), "quotes": len(quotes),
            "players": len(set(q["player_id"] for q in quotes if q["player_id"] is not None)),
            "vendors": len(set(q["vendor"] for q in quotes)),
            "paired_markets": len(valid_pairs),
            "paired_player_markets": sum(1 for k, _ in valid_pairs if k[1] == "player"),
            "median_two_way_margin_pct": round(100 * median(margins), 2) if margins else None,
            "nonstandard_line_quote_count": len(outliers),
            "nonstandard_line_samples": sample,
            "errors": errors[:50], "error_count": len(errors),
            "game_ids": sorted(games),
        }
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser(description="Audit GOAT sportsbook quotes without recommending wagers")
    p.add_argument("--db", required=True)
    p.add_argument("--out", default="reports/goat-market-integrity.json")
    a = p.parse_args()
    report = audit_file(a.db)
    output = Path(a.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "nonstandard_line_samples"}, indent=2))
    if report["integrity"] != "ok" or report["error_count"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
