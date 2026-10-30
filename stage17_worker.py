"""Scheduled halftime predictions, optional live odds, and settlement."""
import datetime
import json
import math
import os
import sys
from pathlib import Path

import requests
import numpy as np
import pandas as pd
from stage17_core import load_history, predict

ROOT = Path(__file__).parent
STORE = ROOT / 'data' / 'stage17_predictions.jsonl'
BASE = 'https://api.thestatsapi.com/api/football/matches'
HT = {'ht', 'halftime', 'half_time', 'half-time', 'half time', 'half_time_break'}
FT = {'ft', 'full_time', 'full-time', 'finished', 'completed', 'ended', 'after_penalties', 'aet'}
BOOKS = {'Bet365', 'Paddy Power', 'BetMGM UK', 'Betfair Exchange'}
MARKET_MAP = {
    'Home full-time win': ('match_odds', 'home'),
    'Away full-time win': ('match_odds', 'away'),
    'Home wins 2H': ('second_half_result', 'home'),
    'Away wins 2H': ('second_half_result', 'away'),
}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def api(path='', params=None):
    r = requests.get(BASE + path,
                     headers={'Authorization': 'Bearer ' + os.environ['STATS_API_KEY']},
                     params=params, timeout=25)
    r.raise_for_status()
    return r.json()


def status(m):
    live = m.get('live') or {}
    return [str(v).strip().lower() for v in [
        m.get('match_status'), m.get('status'), m.get('status_short'),
        live.get('match_status'), live.get('period'), live.get('status')
    ] if v is not None]


def is_ht(m):
    return any(s in HT for s in status(m))


def is_ft(m):
    return any(s in FT for s in status(m))


def score(m, ht=False):
    s = m.get('score') or {}
    h = s.get('half_time_home') if ht else s.get('home')
    a = s.get('half_time_away') if ht else s.get('away')
    if ht and h is None and a is None and is_ht(m):
        h, a = s.get('home'), s.get('away')
    try:
        return int(h), int(a)
    except (ValueError, TypeError):
        return None


def first_half_xg(payload):
    data = payload.get('data') or {}
    meta = data.get('meta') or {}
    if str(meta.get('match_status') or meta.get('period') or '').strip().lower() not in HT:
        return None
    vals = ((data.get('stats') or {}).get('expected_goals') or {}).get('all') or {}
    try:
        h, a = float(vals['home']), float(vals['away'])
        return (h, a) if all(math.isfinite(v) and v >= 0 for v in (h, a)) else None
    except (KeyError, ValueError, TypeError):
        return None


def opening(payload):
    candidates = []
    for b in (payload.get('data') or {}).get('bookmakers') or []:
        odds = (b.get('markets') or {}).get('match_odds') or {}
        try:
            h = float((odds.get('home') or {}).get('opening'))
            a = float((odds.get('away') or {}).get('opening'))
            if not all(math.isfinite(x) and x > 1 for x in (h, a)) or h == a:
                continue
            candidates.append((str(b.get('bookmaker', 'Unknown')),
                               'Home' if h < a else 'Away', min(h, a)))
        except (TypeError, ValueError):
            pass
    if not candidates:
        return None
    return next((v for v in candidates if v[0].lower() == 'pinnacle'), candidates[0])


def all_live():
    found = {}
    max_pages = int(os.getenv('STAGE17_MAX_PAGES', '10'))
    for page in range(1, max_pages + 1):
        payload = api(params={'status': 'live', 'per_page': 100, 'page': page})
        data = payload.get('data')
        if not isinstance(data, list):
            raise RuntimeError('Unexpected live matches payload')
        for m in data:
            if isinstance(m, dict) and m.get('id'):
                found[str(m['id'])] = m
        meta = payload.get('meta') or {}
        try:
            total = int(meta['total_pages'])
        except (ValueError, KeyError, TypeError):
            total = None
        if (total is not None and page >= total) or len(data) < 100:
            break
        if page == max_pages:
            print('WARNING: live fixture pagination may be incomplete')
    return list(found.values())


def read_rows():
    if not STORE.exists():
        return []
    return [json.loads(line) for line in STORE.read_text().splitlines() if line.strip()]


def write_rows(rows):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix('.tmp')
    tmp.write_text(''.join(json.dumps(row, allow_nan=False, separators=(',', ':')) + '\n'
                           for row in rows))
    tmp.replace(STORE)


def positive_price(raw):
    try:
        value = float(raw)
        return value if math.isfinite(value) and value > 1 else None
    except (TypeError, ValueError):
        return None


def get_live_prices(mid):
    """Collect best observed back prices for only exactly matched Stage 17 markets."""
    data = (api('/' + mid + '/odds/live').get('data') or {})
    candidates = {market: [] for market in MARKET_MAP}
    for book in data.get('bookmakers') or []:
        bookmaker = str(book.get('bookmaker', ''))
        if bookmaker not in BOOKS:
            continue
        markets = book.get('markets') or {}
        for prediction_market, (api_market, selection) in MARKET_MAP.items():
            quote = ((markets.get(api_market) or {}).get(selection) or {})
            if not isinstance(quote, dict):
                continue
            if bookmaker == 'Betfair Exchange':
                backs = quote.get('available_to_back') or []
                levels = []
                for level in backs:
                    if not isinstance(level, dict):
                        continue
                    price = positive_price(level.get('price'))
                    try:
                        size = float(level.get('size'))
                    except (ValueError, TypeError):
                        continue
                    if price is not None and math.isfinite(size) and size > 0:
                        levels.append((price, size))
                if not levels:
                    continue
                price, size = max(levels, key=lambda x: x[0])
                candidates[prediction_market].append({
                    'bookmaker': bookmaker, 'odds': price, 'available_size': size
                })
            else:
                price = positive_price(quote.get('live'))
                if price is not None:
                    candidates[prediction_market].append({
                        'bookmaker': bookmaker, 'odds': price
                    })
    return {market: max(options, key=lambda x: x['odds'])
            for market, options in candidates.items() if options}


def add_prices(preds, quotes):
    """Attach observed prices and gross edge; commission is deliberately not assumed."""
    for prediction in preds:
        quote = quotes.get(prediction.get('market'))
        if not quote:
            continue
        try:
            p = float(prediction['probability'])
        except (TypeError, ValueError, KeyError):
            continue
        if not (math.isfinite(p) and 0 < p < 1):
            continue
        prediction['fair_odds'] = round(1 / p, 4)
        prediction['live_odds'] = quote['odds']
        prediction['live_bookmaker'] = quote['bookmaker']
        if 'available_size' in quote:
            prediction['available_size'] = quote['available_size']
        prediction['gross_expected_roi_pct'] = round(100 * (p * quote['odds'] - 1), 2)



def prospective_goal_predictions(history, captured_utc, ht_h, ht_a, odds, xgh, xga):
    """Stage 20C: point-in-time goal model. No future/same-day results allowed."""
    date_col = 'date' if 'date' in history.columns else 'Date' if 'Date' in history.columns else None
    if date_col is None:
        print('Stage 20C withheld: no history date column')
        return []
    pool = history.copy()
    pool['_goal_date'] = pd.to_datetime(pool[date_col], errors='coerce', dayfirst=True, utc=True)
    cutoff = pd.Timestamp(captured_utc).normalize()
    pool = pool[pool['_goal_date'].notna() & (pool['_goal_date'] < cutoff)].copy()
    pool['g2h'] = pool['FTHG'] - pool['HTHG']
    pool['g2a'] = pool['FTAG'] - pool['HTAG']
    pool = pool[pool['g2h'].between(0, 12) & pool['g2a'].between(0, 12)
                & pool['fav'].between(1.01, 20)]
    if len(pool) < 100:
        return []
    weights = np.exp(-0.5 * (
        ((pool['HTHG'].to_numpy(float) - ht_h) / 1.20)**2 +
        ((pool['HTAG'].to_numpy(float) - ht_a) / 1.20)**2 +
        ((pool['fav'].to_numpy(float) - odds) / 0.85)**2 +
        ((pool['ht_xg_home_final'].to_numpy(float) - xgh) / 0.75)**2 +
        ((pool['ht_xg_away_final'].to_numpy(float) - xga) / 0.75)**2))
    sw = float(weights.sum())
    if sw < 1e-6:
        return []
    ess = sw * sw / max(float(np.square(weights).sum()), 1e-12)
    prior = 60.
    lh = max(0.05, (float(weights @ pool['g2h'].to_numpy(float)) +
                    prior * float(pool['g2h'].mean())) / (sw + prior))
    la = max(0.05, (float(weights @ pool['g2a'].to_numpy(float)) +
                    prior * float(pool['g2a'].mean())) / (sw + prior))
    def pois(lam):
        a = np.empty(13, dtype=float)
        a[0] = math.exp(-lam)
        for i in range(1, 13):
            a[i] = a[i-1] * lam / i
        a[-1] += max(0., 1. - float(a.sum()))
        return a
    joint = np.outer(pois(lh), pois(la))
    h, a = np.indices(joint.shape)
    final = ht_h + h - ht_a - a
    probabilities = {
        'Home full-time win': float(joint[final > 0].sum()),
        'Away full-time win': float(joint[final < 0].sum()),
        'Home scores in 2H': float(joint[h >= 1].sum()),
        'Away scores in 2H': float(joint[a >= 1].sum()),
        'Home wins 2H': float(joint[h > a].sum()),
        'Away wins 2H': float(joint[h < a].sum()),
    }
    return [{'method': 'Goal model (prospective)', 'market': market,
             'probability': round(prob, 8), 'sample': len(pool),
             'ess': round(ess, 3), 'model_version': '20C-v1',
             'training_cutoff_exclusive_utc': cutoff.isoformat()}
            for market, prob in probabilities.items()]


def run():
    history = load_history(ROOT / 'football_merged_32653.csv')
    rows = read_rows()
    byid = {str(r['match_id']): r for r in rows}
    created = settled = 0
    live = all_live()
    # Stage 21B: observe API status strings without changing capture rules.
    from collections import Counter
    status_counts = Counter()
    for match in live:
        values = status(match)
        status_counts[tuple(values) if values else ('<missing>',)] += 1
    print('STAGE 21B LIVE MATCH STATUS AUDIT')
    print('  live_matches: ' + str(len(live)))
    for values, count in sorted(status_counts.items(), key=lambda item: (-item[1], item[0])):
        print('  status_values=' + repr(values) + ' count=' + str(count) +
              ' recognized_ht=' + str(any(v in HT for v in values)))
    diagnostics = {
        'live_found': len(live), 'recognized_ht': 0, 'already_recorded': 0,
        'missing_ht_score': 0, 'snapshot_request_error': 0,
        'missing_ht_xg': 0, 'missing_opening_odds': 0,
        'no_base_predictions': 0, 'goal_predictions_added': 0,
        'goal_predictions_withheld': 0, 'new_records': 0,
    }
    for m in live:
        mid = str(m['id'])
        if not is_ht(m):
            continue
        diagnostics['recognized_ht'] += 1
        if mid in byid:
            diagnostics['already_recorded'] += 1
            continue
        ht = score(m, ht=True)
        if ht is None:
            diagnostics['missing_ht_score'] += 1
            continue
        try:
            xg = first_half_xg(api('/' + mid + '/live-stats'))
            op = opening(api('/' + mid + '/odds'))
        except (requests.RequestException, ValueError, TypeError) as e:
            diagnostics['snapshot_request_error'] += 1
            print('Snapshot unavailable', mid, str(e)[:150])
            continue
        if xg is None:
            diagnostics['missing_ht_xg'] += 1
        if op is None:
            diagnostics['missing_opening_odds'] += 1
        if xg is None or op is None:
            continue
        captured = now()
        preds = predict(history, *ht, op[2], *xg, op[1])
        if not preds:
            diagnostics['no_base_predictions'] += 1
        try:
            goal_preds = prospective_goal_predictions(history, captured, *ht, op[2], *xg)
            if goal_preds:
                diagnostics['goal_predictions_added'] += 1
            else:
                diagnostics['goal_predictions_withheld'] += 1
            preds += goal_preds
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            diagnostics['goal_predictions_withheld'] += 1
            print("Stage 20C model withheld", mid, str(exc)[:150])
        if not preds:
            continue
        record = {
            'match_id': mid,
            'match': str((m.get('home_team') or {}).get('name', 'Home')) + ' v ' +
                     str((m.get('away_team') or {}).get('name', 'Away')),
            'captured_utc': captured,
            'ht_home': ht[0], 'ht_away': ht[1],
            'xg_home': xg[0], 'xg_away': xg[1],
            'favourite_side': op[1], 'favourite_odds': op[2],
            'odds_bookmaker': op[0], 'status': 'pending',
            'ft_home': None, 'ft_away': None, 'settled_utc': None,
            'predictions': preds,
        }
        # A live-odds failure must never prevent an otherwise valid snapshot.
        try:
            quotes = get_live_prices(mid)
            add_prices(preds, quotes)
            record['live_odds_captured_utc'] = now()
            record['live_odds_markets_found'] = len(quotes)
        except (requests.RequestException, ValueError, TypeError, KeyError) as e:
            print('Live odds unavailable', mid, str(e)[:150])
            record['live_odds_markets_found'] = 0
        rows.append(record)
        byid[mid] = record
        created += 1
        diagnostics['new_records'] += 1
    # Check each pending fixture by ID. Never infer full time from live-list absence.
    for row in rows:
        if row.get('status') != 'pending':
            continue
        try:
            response = api('/' + str(row['match_id']))
            m = response.get('data') if isinstance(response, dict) else None
            if not isinstance(m, dict) or not is_ft(m):
                continue
            ft = score(m)
            if ft is None:
                continue
            row.update(status='settled', ft_home=ft[0], ft_away=ft[1], settled_utc=now())
            settled += 1
        except (requests.RequestException, ValueError, TypeError) as e:
            print('Settlement deferred', row['match_id'], str(e)[:150])
    write_rows(rows)
    print('STAGE 21A COLLECTOR DIAGNOSTICS')
    for key, value in diagnostics.items():
        print('  ' + key + ': ' + str(value))
    print('Created', created, 'settled', settled, 'total', len(rows),
          'pending', sum(r['status'] == 'pending' for r in rows))


if __name__ == '__main__':
    if 'STATS_API_KEY' not in os.environ:
        sys.exit('Missing STATS_API_KEY secret')
    run()
