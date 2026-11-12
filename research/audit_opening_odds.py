"""Audit authenticated NBA opening-odds archives against real game/player results.

Usage:
  python research/audit_opening_odds.py \
    --history private/nba-history-merged.sqlite \
    --odds private/goat-odds.sqlite --out-dir private/audit

This is retrospective DATA QUALITY work, not a historical betting strategy.
Quotes captured after the event are opening prices reported by the provider;
these were not necessarily independently available to the analyst at quote_at.
No model probabilities, betting recommendations or ROI are produced.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from statistics import median


MARKETS = {
    'points', 'rebounds', 'assists', 'threes', 'points_rebounds',
    'points_assists', 'rebounds_assists', 'points_rebounds_assists',
}


def _count(c: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(c.execute(sql, params).fetchone()[0])


def analyze(history: str, odds: str) -> dict:
    """Read both licensed SQLite files, avoid mutating either source."""
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('ATTACH DATABASE ? AS history', (str(history),))
        connection.execute('ATTACH DATABASE ? AS market', (str(odds),))
        for schema in ('history', 'market'):
            integrity = connection.execute(f'PRAGMA {schema}.integrity_check').fetchone()[0]
            if integrity != 'ok':
                raise ValueError(f'{schema} integrity failed: {integrity}')
        game_matches = [dict(r) for r in connection.execute('''
            SELECT o.game_id, o.game_date, o.home_name, o.away_name, o.starts_at,
                   h.status AS recorded_status,
                   CASE WHEN h.id IS NULL THEN 0 ELSE 1 END AS historical_match
            FROM market.goat_games o LEFT JOIN history.games h ON h.id=o.game_id
            ORDER BY o.game_id
        ''')]
        quotes_count = _count(connection, 'SELECT COUNT(*) FROM market.goat_odds_quotes')
        pregame_violations = _count(connection, '''
            SELECT COUNT(*) FROM market.goat_odds_quotes q
            JOIN market.goat_games g ON q.game_id=g.game_id
            WHERE q.quote_at >= g.starts_at OR q.quote_at > q.observed_at
        ''')
        acquired_after_tipoff = _count(connection, '''
            SELECT COUNT(*) FROM market.goat_odds_quotes q
            JOIN market.goat_games g ON q.game_id=g.game_id
            WHERE q.observed_at >= g.starts_at
        ''')
        matched = _count(connection, '''
            SELECT COUNT(*) FROM market.goat_odds_quotes q
            JOIN history.player_games p ON q.game_id=p.game_id AND q.player_id=p.player_id
            WHERE q.scope='player'
        ''')
        player_total = _count(connection, "SELECT COUNT(*) FROM market.goat_odds_quotes WHERE scope='player'")
        distinct_players = _count(connection, '''
            SELECT COUNT(DISTINCT player_id) FROM market.goat_odds_quotes WHERE scope='player'
        ''')
        unmatched = [dict(r) for r in connection.execute('''
            SELECT q.game_id, q.player_id, COUNT(*) AS quote_rows
            FROM market.goat_odds_quotes q
            LEFT JOIN history.player_games p ON q.game_id=p.game_id AND q.player_id=p.player_id
            WHERE q.scope='player' AND p.player_id IS NULL
            GROUP BY q.game_id, q.player_id ORDER BY quote_rows DESC
        ''')]
        markets = {str(r[0]): int(r[1]) for r in connection.execute('''
            SELECT market,COUNT(*) FROM market.goat_odds_quotes GROUP BY market ORDER BY COUNT(*) DESC
        ''')}
        vendors = {str(r[0]): int(r[1]) for r in connection.execute('''
            SELECT vendor,COUNT(*) FROM market.goat_odds_quotes GROUP BY vendor ORDER BY COUNT(*) DESC
        ''')}
        groups: dict[tuple, dict[str, float]] = defaultdict(dict)
        over_lines: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        candidates: list[dict] = []
        for r in connection.execute('''
            SELECT game_id,player_id,vendor,market,market_type,side,line,quote_at,decimal_odds
            FROM market.goat_odds_quotes WHERE scope='player' AND market_type='over_under'
        '''):
            k=(r['game_id'],r['player_id'],r['vendor'],r['market'],r['line'],r['quote_at'])
            groups[k][r['side']]=float(r['decimal_odds'])
            if r['side']=='over':
                g=(r['game_id'],r['player_id'],r['market'])
                over_lines[g][r['vendor']].append(float(r['line']))
                candidates.append(dict(r))
        complete = [v for v in groups.values() if 'over' in v and 'under' in v]
        overround = sorted((1/v['over'] + 1/v['under'] - 1) for v in complete)
        def quantile(p: float):
            if not overround:
                return None
            return round(overround[int((len(overround)-1)*p)], 6)
        flagged=[]
        for c in candidates:
            g=(c['game_id'],c['player_id'],c['market'])
            per_vendor = over_lines[g]
            if len(per_vendor) < 3:
                continue
            consensus = median([median(lines) for lines in per_vendor.values()])
            # Heuristic anomaly flag, never a verdict of a bad book or a proven bet.
            if (consensus > 0 and c['line'] < 0.5*consensus and
                1.65 <= c['decimal_odds'] <= 2.2):
                flagged.append({
                    'game_id': c['game_id'], 'player_id': c['player_id'],
                    'market': c['market'], 'vendor': c['vendor'],
                    'line': c['line'], 'consensus_line_median': round(consensus,2),
                    'decimal_odds': round(c['decimal_odds'], 4),
                    'flag': 'requires independent market/period verification',
                })
        return {
            'source': 'BALLDONTLIE NBA GOAT (licensed user-provided artifacts)',
            'audited_at_utc': datetime.now(timezone.utc).isoformat(),
            'game_matches': game_matches,
            'unique_games': len(game_matches),
            'games_matched_to_history': sum(g['historical_match'] for g in game_matches),
            'odds_rows': quotes_count,
            'player_quote_rows': player_total,
            'game_quote_rows': quotes_count-player_total,
            'markets': markets, 'vendors': vendors,
            'unique_players_in_props': distinct_players,
            'player_quote_rows_matched_to_observed_player_games': matched,
            'player_quote_rows_unmatched': player_total-matched,
            'unmatched_player_game_ids': unmatched,
            'quote_at_after_tipoff_or_after_observation': pregame_violations,
            'archival_quotes_observed_after_tipoff': acquired_after_tipoff,
            'complete_player_over_under_pairs': len(complete),
            'median_two_way_overround': quantile(0.5),
            'two_way_overround_05': quantile(0.05),
            'two_way_overround_95': quantile(0.95),
            'suspicious_points_over_quotes_heuristic': sum(f['market']=='points' for f in flagged),
            'suspicious_quotes_heuristic_total':len(flagged),
            'suspicious_quotes_sample': flagged[:15],
            'research_decision': 'NO BET',
            'reasons': [
                'Opening snapshots recovered after the events; not executable today',
                'No pre-event fitted player probability for these exact quote lines',
                'No validated full-season event-time historical odds backtest',
                'Some quotes need roster and market-period verification',
            ],
        }
    finally:
        connection.close()


def create_local_copy(history: str, odds: str, dest: Path) -> None:
    """Keep one private reusable SQLite with both source datasets; no public upload."""
    if dest.exists():
        raise FileExistsError(f'Protecting an existing research database: {dest}')
    shutil.copyfile(history, dest)
    con=sqlite3.connect(dest)
    try:
        con.execute('ATTACH DATABASE ? AS source_odds', (str(odds),))
        with con:
            for table in ('goat_games','goat_odds_raw','goat_odds_quotes'):
                con.execute(f'CREATE TABLE {table} AS SELECT * FROM source_odds.{table}')
            con.execute('CREATE INDEX ix_private_odds_player ON goat_odds_quotes(game_id,player_id,market,quote_at)')
        if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Merged copy failed integrity check')
        print('Private merged database created, integrity_check=ok')
    finally:
        con.close()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--history',required=True)
    p.add_argument('--odds',required=True)
    p.add_argument('--out-dir',default='private/market-audit')
    p.add_argument('--merge-private',action='store_true')
    args=p.parse_args()
    dest=Path(args.out_dir);dest.mkdir(parents=True,exist_ok=True)
    report=analyze(args.history,args.odds)
    (dest/'goat-market-audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    if args.merge_private:
        create_local_copy(args.history,args.odds,dest/'quantedge-with-odds.sqlite')
    print(json.dumps({k:report[k] for k in ('unique_games','odds_rows','player_quote_rows_matched_to_observed_player_games','player_quote_rows_unmatched','complete_player_over_under_pairs','median_two_way_overround','suspicious_quotes_heuristic_total','research_decision')},indent=2))


if __name__=='__main__':
    main()