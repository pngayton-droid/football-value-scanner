import math
from datetime import datetime, timezone
import io
import re
from pathlib import Path
import pandas as pd
import streamlit as st

import requests
st.set_page_config(page_title='Football Value Scanner',layout='wide')
st.title('Football Value Scanner · Research prototype')
st.caption('Historical research and live-data diagnostics. API odds may be stale; no bets are placed.')
DATA=Path(__file__).parent/'football_merged_32653.csv'
@st.cache_data(show_spinner='Loading historical matches…')
def load_data():
    d=pd.read_csv(DATA,low_memory=False,encoding='utf-8-sig')
    for c in ['HTHG','HTAG','FTHG','FTAG','B365H','B365A','ht_xg_home_final','ht_xg_away_final']:
        if c in d:d[c]=pd.to_numeric(d[c],errors='coerce')
    return d

def wilson_lower(wins,n,z=1.96):
    if n==0:return 0.
    p=wins/n
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)

if not DATA.exists():
    st.error('Historical CSV missing. Add football_merged_32653.csv next to app.py.')
    st.stop()
d=load_data()
with st.sidebar:
    st.header('Match at halftime')
    home=st.text_input('Home team','Home')
    away=st.text_input('Away team','Away')
    ht_h=st.number_input('Home HT goals',0,15,0)
    ht_a=st.number_input('Away HT goals',0,15,0)
    fav=st.number_input('Pre-match favourite odds',1.01,50.,1.35,0.05)
    xgh=st.number_input('Home HT xG',0.,10.,0.30,0.05)
    xga=st.number_input('Away HT xG',0.,10.,0.22,0.05)
    xg_width=st.slider('xG tolerance per team',0.10,1.50,0.40,0.05)
    odds_width=st.slider('Favourite odds tolerance',0.05,2.00,0.35,0.05)
    min_n=st.number_input('Minimum sample',10,1000,100,10)
    commission=st.slider('Exchange commission (%)',0.,10.,2.,0.5)/100
    st.caption('Betfair delayed prices must never be treated as currently executable.')

xg1='ht_xg_home_final';xg2='ht_xg_away_final'
for c in (xg1,xg2):
    if c not in d:
        st.error(f'Missing expected xG column: {c}')
        st.stop()
HISTORY = d.dropna(subset=['HTHG','HTAG','FTHG','FTAG','B365H','B365A',xg1,xg2]).copy()
HISTORY['fav'] = HISTORY[['B365H','B365A']].min(axis=1)


def comparable_matches(ht_home, ht_away, favourite_odds, home_xg, away_xg,
                       xg_tolerance, odds_tolerance):
    if any(v is None for v in (ht_home, ht_away, favourite_odds, home_xg, away_xg)):
        return HISTORY.iloc[0:0]
    return HISTORY[
        (HISTORY.HTHG == ht_home) & (HISTORY.HTAG == ht_away)
        & HISTORY.fav.between(max(1.01, favourite_odds - odds_tolerance),
                              favourite_odds + odds_tolerance)
        & HISTORY[xg1].between(max(0, home_xg - xg_tolerance), home_xg + xg_tolerance)
        & HISTORY[xg2].between(max(0, away_xg - xg_tolerance), away_xg + xg_tolerance)
    ]




def stage11_diagnostics(ht_home, ht_away, favourite_odds, home_xg, away_xg,
                        xg_tolerance, odds_tolerance):
    """Descriptive funnel and sensitivity only; never changes production estimates."""
    if any(v is None for v in (ht_home, ht_away, favourite_odds, home_xg, away_xg)):
        return None, None, None
    exact = HISTORY[(HISTORY.HTHG == int(ht_home)) & (HISTORY.HTAG == int(ht_away))]
    odds = exact[exact.fav.between(max(1.01, favourite_odds - odds_tolerance),
                                   favourite_odds + odds_tolerance)]
    hx = odds[odds[xg1].between(max(0, home_xg - xg_tolerance), home_xg + xg_tolerance)]
    ax = hx[hx[xg2].between(max(0, away_xg - xg_tolerance), away_xg + xg_tolerance)]
    funnel = pd.DataFrame([
        ('Usable historical records', len(HISTORY)),
        ('Exact halftime score', len(exact)),
        ('Plus favourite odds band', len(odds)),
        ('Plus home HT xG band', len(hx)),
        ('Plus away HT xG band (current sample)', len(ax)),
    ], columns=['Filter stage', 'Remaining matches'])
    scenarios = [
        ('Current (unchanged)', xg_tolerance, odds_tolerance),
        ('xG +0.10', min(1.50, xg_tolerance + 0.10), odds_tolerance),
        ('xG +0.20', min(1.50, xg_tolerance + 0.20), odds_tolerance),
        ('Odds +0.15', xg_tolerance, min(2.00, odds_tolerance + 0.15)),
        ('Odds +0.30', xg_tolerance, min(2.00, odds_tolerance + 0.30)),
        ('Both modestly wider', min(1.50, xg_tolerance + 0.10),
         min(2.00, odds_tolerance + 0.15)),
    ]
    key_markets = ['Home full-time win', 'Draw full-time', 'Away full-time win',
                   'Home scores in 2H', 'Away scores in 2H',
                   'Home wins 2H', 'Away wins 2H', 'Over 1.5 goals 2H']
    base_probs = market_outcomes(ax)
    records = []
    for name, xwidth, owidth in scenarios:
        sample = comparable_matches(ht_home, ht_away, favourite_odds,
                                    home_xg, away_xg, xwidth, owidth)
        outcomes = market_outcomes(sample)
        changes = []
        for market in key_markets:
            if len(sample) and len(ax):
                changes.append(abs(float(outcomes[market].mean()) -
                                   float(base_probs[market].mean())) * 100)
        records.append({
            'Scenario': name, 'xG tolerance': round(xwidth, 2),
            'Odds tolerance': round(owidth, 2), 'Matches': len(sample),
            'Extra matches': len(sample) - len(ax),
            'Largest change in 8 key markets (pp)': round(max(changes), 1) if changes else None,
        })
    sensitivity = pd.DataFrame(records)
    # Check whether the historical favourite was on the same home/away side as the live favourite.
    home_fav = int((ax.B365H < ax.B365A).sum())
    away_fav = int((ax.B365A < ax.B365H).sum())
    fav_side = pd.DataFrame([{'Historical favourite side': 'Home', 'Matches': home_fav},
                             {'Historical favourite side': 'Away', 'Matches': away_fav},
                             {'Historical favourite side': 'Equal opening prices',
                              'Matches': len(ax) - home_fav - away_fav}])
    return funnel, sensitivity, fav_side


def show_stage11_diagnostics(ht_home, ht_away, favourite_odds, home_xg, away_xg,
                             xg_tolerance, odds_tolerance):
    funnel, sensitivity, fav_side = stage11_diagnostics(
        ht_home, ht_away, favourite_odds, home_xg, away_xg,
        xg_tolerance, odds_tolerance)
    if funnel is None:
        st.info('Need a halftime score, both xG values and favourite odds for Stage 11.')
        return
    st.markdown('**Where the historical matches disappear**')
    st.dataframe(funnel, hide_index=True, use_container_width=True)
    st.markdown('**Sensitivity experiments (research only)**')
    st.dataframe(sensitivity, hide_index=True, use_container_width=True)
    st.caption('Percentage-point changes compare the same eight market outcomes against '
               'the current sample. Small changes are NOT proof of equal predictive quality; '
               'overlapping samples, selection effects and out-of-sample validation matter. '
               'The live opportunity tracker still uses the original tolerances and minimum sample.')
    st.markdown('**Home/away favourite mix in the current sample**')
    st.dataframe(fav_side, hide_index=True, use_container_width=True)
    st.warning('The current historical filter matches the favourite PRICE, not which team '
               'was favourite. This diagnostic identifies the mix but does not silently '
               'change the matching method.')

def market_outcomes(sample):
    second_home = sample.FTHG - sample.HTHG
    second_away = sample.FTAG - sample.HTAG
    total_goals = sample.FTHG + sample.FTAG
    return {
        'Home full-time win': sample.FTHG > sample.FTAG,
        'Draw full-time': sample.FTHG == sample.FTAG,
        'Away full-time win': sample.FTHG < sample.FTAG,
        'Home scores in 2H': second_home >= 1,
        'Away scores in 2H': second_away >= 1,
        'Over 0.5 goals 2H': second_home + second_away >= 1,
        'Over 1.5 goals 2H': second_home + second_away >= 2,
        'Over 2.5 goals 2H': second_home + second_away >= 3,
        'Home wins 2H': second_home > second_away,
        'Draw 2H': second_home == second_away,
        'Away wins 2H': second_home < second_away,
        'BTTS Yes FT': (sample.FTHG >= 1) & (sample.FTAG >= 1),
        'Over 1.5 goals FT': total_goals >= 2,
        'Under 1.5 goals FT': total_goals <= 1,
        'Over 2.5 goals FT': total_goals >= 3,
        'Under 2.5 goals FT': total_goals <= 2,
        'Over 3.5 goals FT': total_goals >= 4,
        'Under 3.5 goals FT': total_goals <= 3,
    }


def historical_estimates(sample):
    estimates = []
    for market, outcomes in market_outcomes(sample).items():
        n = len(outcomes)
        wins = int(outcomes.sum())
        probability = wins / n if n else 0
        estimates.append({
            'Market': market, 'Matches': n, 'Wins': wins,
            'Strike rate': round(probability * 100, 1) if n else None,
            'Fair odds': round(1 / probability, 2) if probability else None,
            'Wilson lower %': round(wilson_lower(wins, n) * 100, 1) if n else None,
        })
    return pd.DataFrame(estimates)



# Stage 12: out-of-sample matching-method comparison (research only).
# Training matches are strictly earlier than the test period; no model settings are
# selected from the test period and then used to claim an unbiased final performance.
def stage12_validation(history, max_test=600):
    import numpy as np
    date_col = next((c for c in ('Date', 'date', 'match_date', 'MatchDate') if c in history.columns), None)
    if date_col is None:
        return None, 'No historical match-date column found; chronological validation cannot run safely.'
    dates = pd.to_datetime(history[date_col], errors='coerce', dayfirst=True)
    dated = history.loc[dates.notna()].copy()
    dated['_validation_date'] = dates.loc[dates.notna()]
    dated = dated.sort_values('_validation_date')
    if len(dated) < 1000:
        return None, 'Too few dated matches for meaningful chronological validation.'
    split = int(len(dated) * 0.8)
    train, test = dated.iloc[:split], dated.iloc[split:]
    # Same-date fixtures cannot appear on both sides of the cutoff.
    cutoff = test['_validation_date'].iloc[0]
    train = train[train['_validation_date'] < cutoff]
    test = test[test['_validation_date'] >= cutoff]
    if len(train) < 500 or len(test) < 100:
        return None, 'Insufficient clean training and test matches after date separation.'
    if len(test) > max_test:
        indices = np.linspace(0, len(test)-1, max_test, dtype=int)
        test = test.iloc[indices]
    features = ['HTHG', 'HTAG', 'fav', xg1, xg2]
    tr = train[features].to_numpy(dtype=float)
    te = test[features].to_numpy(dtype=float)
    tr_homefav = (train['B365H'].to_numpy(float) < train['B365A'].to_numpy(float))
    te_homefav = (test['B365H'].to_numpy(float) < test['B365A'].to_numpy(float))
    train_outcomes = market_outcomes(train)
    test_outcomes = market_outcomes(test)
    candidates = [
        ('Original exact score', .40, .35, 'exact', False),
        ('Wider xG +0.10', .50, .35, 'exact', False),
        ('Wider odds +0.15', .40, .50, 'exact', False),
        ('Both modestly wider', .50, .50, 'exact', False),
        ('Original + same favourite side', .40, .35, 'exact', True),
        ('Wider + same favourite side', .50, .50, 'exact', True),
        ('Same goal difference and total', .40, .35, 'goal_profile', False),
    ]
    # Note: goal-profile is equivalent to exact score mathematically; omit it.
    candidates = candidates[:-1]
    tr_y={k:v.to_numpy(dtype=float) for k,v in train_outcomes.items()}
    te_y={k:v.to_numpy(dtype=float) for k,v in test_outcomes.items()}
    results=[]
    for label, xwidth, owidth, score_type, side in candidates:
        estimates = {k: [] for k in train_outcomes}
        truths = {k: [] for k in train_outcomes}
        sizes=[]
        for i, row in enumerate(te):
            mask = ((tr[:,0] == row[0]) & (tr[:,1] == row[1])
                    & (abs(tr[:,2] - row[2]) <= owidth)
                    & (abs(tr[:,3] - row[3]) <= xwidth)
                    & (abs(tr[:,4] - row[4]) <= xwidth))
            if side:
                mask &= (tr_homefav == te_homefav[i])
            n=int(mask.sum())
            if n < 30: continue
            sizes.append(n)
            for k in estimates:
                y=tr_y[k][mask]
                # Laplace smoothing reduces overconfident estimates from small samples.
                estimates[k].append((float(y.sum())+1)/(n+2))
                truths[k].append(float(te_y[k][i]))
        for k in estimates:
            n=len(estimates[k])
            if n < 100: continue
            pred=np.asarray(estimates[k]); actual=np.asarray(truths[k])
            brier=float(np.mean((pred-actual)**2))
            # Baseline uses the training period's unconditional market frequency.
            base=(float(train_outcomes[k].sum())+1)/(len(train)+2)
            base_brier=float(np.mean((base-actual)**2))
            results.append({'Market':k,'Matching method':label,
                'Test predictions':n,'Average sample':round(float(np.mean(sizes)),1),
                'Brier score (lower better)':round(brier,5),
                'Simple baseline Brier':round(base_brier,5),
                'Improvement vs baseline':round(base_brier-brier,5),
                'Test start':str(cutoff.date()),
                'Train matches':len(train),'Test matches evaluated':len(test)})
    return pd.DataFrame(results), None

st.subheader('Stage 12 · Historical matching accuracy laboratory')
st.caption('Chronological holdout experiment. This does not change the live scanner or opportunity tracker.')
with st.expander('Compare matching methods on later, unseen matches'):
    st.write('We compare the original filters, slightly wider filters and same-side favourite filters. '
             'Each method predicts later matches using earlier matches only. '
             'Lower Brier score means better probability accuracy; this is not proof of betting profit.')
    if st.button('Run Stage 12 validation', key='stage12_run'):
        with st.spinner('Testing historical matching methods…'):
            validation, error = stage12_validation(HISTORY)
        if error:
            st.error(error)
        elif validation.empty:
            st.warning('No methods produced at least 100 test predictions with 30+ comparable training matches. '
                       'We need more data or a different validation design.')
        else:
            st.session_state['stage12_validation'] = validation
    if 'stage12_validation' in st.session_state:
        validation=st.session_state['stage12_validation']
        st.dataframe(validation, hide_index=True, use_container_width=True)
        st.download_button('Download Stage 12 validation CSV',
            validation.to_csv(index=False).encode('utf-8'),
            'stage12_holdout_validation.csv', 'text/csv')
        st.warning('Research-only: methods were compared on the same holdout. Selecting the best '
                   'after seeing results requires another untouched test period. '
                   'Missing historical odds, league effects, market correlations and data quality '
                   'remain limitations. A positive Brier improvement does not establish positive ROI.')


# STAGE 13 — RESEARCH-ONLY, TWO-PERIOD PAIRED MATCHING VALIDATION
# Does not alter live scanner, historical production filters, or opportunity tracker.
def stage13_paired_validation(history, max_per_period=400, minimum_comparables=30):
    import numpy as np
    date_col = next((c for c in ('Date', 'date', 'match_date', 'MatchDate')
                     if c in history.columns), None)
    if date_col is None:
        return None, 'No historical date column is available.'
    dates = pd.to_datetime(history[date_col], errors='coerce', dayfirst=True)
    dated = history.loc[dates.notna()].copy()
    dated['_stage13_date'] = dates.loc[dates.notna()]
    dated = dated.sort_values('_stage13_date').reset_index(drop=True)
    if len(dated) < 1200:
        return None, 'Not enough dated historical matches for three chronological periods.'

    # Separate entire dates, preventing same-day fixtures from crossing periods.
    first_boundary = dated['_stage13_date'].iloc[int(len(dated) * .70)]
    second_boundary = dated['_stage13_date'].iloc[int(len(dated) * .85)]
    if first_boundary >= second_boundary:
        return None, 'Historical dates do not permit distinct validation and final periods.'
    training = dated[dated['_stage13_date'] < first_boundary]
    validation = dated[(dated['_stage13_date'] >= first_boundary) &
                       (dated['_stage13_date'] < second_boundary)]
    final = dated[dated['_stage13_date'] >= second_boundary]
    if min(len(training), len(validation), len(final)) < 100:
        return None, 'One of the chronological periods is too small.'

    methods = [
        ('Original filters', .40, .35, False),
        ('Wider xG', .50, .35, False),
        ('Wider favourite odds', .40, .50, False),
        ('Both wider', .50, .50, False),
        ('Original + favourite side', .40, .35, True),
        ('Both wider + favourite side', .50, .50, True),
    ]
    focus = ['Home full-time win', 'Away full-time win',
             'Home scores in 2H', 'Away scores in 2H',
             'Home wins 2H', 'Away wins 2H']
    output = []
    for period_name, prior, future in [
        ('Validation', training, validation),
        ('Later confirmation', dated[dated['_stage13_date'] < second_boundary], final),
    ]:
        if len(future) > max_per_period:
            positions = np.linspace(0, len(future)-1, max_per_period, dtype=int)
            future = future.iloc[positions]
        fields = ['HTHG', 'HTAG', 'fav', xg1, xg2]
        tr = prior[fields].to_numpy(dtype=float)
        te = future[fields].to_numpy(dtype=float)
        train_side = prior.B365H.to_numpy(float) < prior.B365A.to_numpy(float)
        test_side = future.B365H.to_numpy(float) < future.B365A.to_numpy(float)
        train_y = {k: v.to_numpy(dtype=float) for k, v in market_outcomes(prior).items()
                   if k in focus}
        test_y = {k: v.to_numpy(dtype=float) for k, v in market_outcomes(future).items()
                  if k in focus}
        predicted = {name: {} for name, _, _, _ in methods}
        for i, row in enumerate(te):
            base = (tr[:, 0] == row[0]) & (tr[:, 1] == row[1])
            for name, xwidth, owidth, require_side in methods:
                mask = (base & (np.abs(tr[:, 2] - row[2]) <= owidth)
                        & (np.abs(tr[:, 3] - row[3]) <= xwidth)
                        & (np.abs(tr[:, 4] - row[4]) <= xwidth))
                if require_side:
                    mask &= train_side == test_side[i]
                count = int(mask.sum())
                if count >= minimum_comparables:
                    predicted[name][i] = (count, {
                        market: (float(outcome[mask].sum()) + 1) / (count + 2)
                        for market, outcome in train_y.items()
                    })
        original = predicted['Original filters']
        for market in focus:
            for name, _, _, _ in methods:
                candidate = predicted[name]
                # Every comparison is paired on fixtures covered by BOTH methods.
                shared = sorted(set(original) & set(candidate))
                if len(shared) < 30:
                    continue
                actual = np.array([test_y[market][i] for i in shared])
                base_p = np.array([original[i][1][market] for i in shared])
                method_p = np.array([candidate[i][1][market] for i in shared])
                base_loss = (base_p - actual) ** 2
                method_loss = (method_p - actual) ** 2
                delta = base_loss - method_loss
                # Approximate paired interval, descriptive only; fixtures are correlated.
                se = float(delta.std(ddof=1) / np.sqrt(len(shared))) if len(shared) > 1 else 0.
                output.append({
                    'Period': period_name, 'Market': market, 'Method': name,
                    'Paired test matches': len(shared),
                    'Original coverage': len(original),
                    'Method coverage': len(candidate),
                    'Original Brier': round(float(base_loss.mean()), 5),
                    'Method Brier': round(float(method_loss.mean()), 5),
                    'Improvement (+ better)': round(float(delta.mean()), 5),
                    'Approx. 95% lower': round(float(delta.mean()) - 1.96 * se, 5),
                    'Approx. 95% upper': round(float(delta.mean()) + 1.96 * se, 5),
                    'Average method sample': round(float(np.mean([candidate[i][0] for i in shared])), 1),
                    'Training matches': len(prior),
                    'Period start': str(future['_stage13_date'].min().date()),
                    'Period end': str(future['_stage13_date'].max().date()),
                })
    if not output:
        return None, 'Too few shared predictions; no paired comparison was possible.'
    return pd.DataFrame(output), None


# Stage 14 — parallel research comparison only; original production estimates stay unchanged.
STAGE14_MARKETS = ['Home full-time win', 'Away full-time win',
                   'Home scores in 2H', 'Away scores in 2H',
                   'Home wins 2H', 'Away wins 2H']

def stage14_parallel(ht_home, ht_away, favourite_odds, home_xg, away_xg,
                     favourite_side, xwidth, owidth):
    if favourite_side not in ('Home', 'Away'):
        return None
    base = comparable_matches(ht_home, ht_away, favourite_odds, home_xg,
                              away_xg, xwidth, owidth)
    wider = comparable_matches(ht_home, ht_away, favourite_odds, home_xg,
                               away_xg, min(1.50, xwidth + .10),
                               min(2.00, owidth + .15))
    if favourite_side == 'Home':
        base_side = base[base.B365H < base.B365A]
        wider_side = wider[wider.B365H < wider.B365A]
    else:
        base_side = base[base.B365A < base.B365H]
        wider_side = wider[wider.B365A < wider.B365H]
    samples = [('Original (live scanner)', base),
               ('Original + favourite side', base_side),
               ('Wider + favourite side', wider_side)]
    rows = []
    for market in STAGE14_MARKETS:
        for method, sample in samples:
            n = len(sample)
            wins = int(market_outcomes(sample)[market].sum()) if n else 0
            rate = wins / n if n else None
            rows.append({'Market': market, 'Method': method, 'Matches': n,
                         'Historical win %': round(100 * rate, 1) if rate is not None else None,
                         'Descriptive fair odds': round(1 / rate, 2) if rate else None,
                         'At least 100 matches': n >= 100})
    return pd.DataFrame(rows)


def stage14_show(ht_home, ht_away, favourite_odds, home_xg, away_xg,
                 favourite_side, xwidth, owidth):
    table = stage14_parallel(ht_home, ht_away, favourite_odds, home_xg,
                             away_xg, favourite_side, xwidth, owidth)
    if table is None:
        st.info('Favourite side unavailable. No Stage 14 comparison is possible.')
        return
    st.write(f'Opening favourite: {favourite_side}. The original live scanner remains unchanged.')
    st.dataframe(table, hide_index=True, use_container_width=True)
    st.download_button('Download Stage 14 side-by-side CSV',
                       table.to_csv(index=False).encode('utf-8-sig'),
                       'stage14_parallel_comparison.csv', 'text/csv',
                       key=f'stage14_export_{ht_home}_{ht_away}_{favourite_side}_{int(favourite_odds*100)}')
    st.caption('The wider method adds 0.10 to each xG tolerance and 0.15 to the odds tolerance. '
               'Historical rates are descriptive, not calibrated probabilities. '
               'Side matching can reduce samples below the 100-match research threshold. '
               'No betting decision, scanner estimate, or tracker entry is changed.')

# Stage 15 — weighted-neighbour research. No production settings are changed.
def stage15_weighted_sample(pool, odds, home_xg, away_xg, k, scale_xg=.35, scale_odds=.35):
    import numpy as np
    if pool.empty:
        return pool.iloc[:0], np.array([]), 0.
    distances = (((pool[xg1].to_numpy(float) - home_xg) / scale_xg) ** 2 +
                 ((pool[xg2].to_numpy(float) - away_xg) / scale_xg) ** 2 +
                 ((pool.fav.to_numpy(float) - odds) / scale_odds) ** 2)
    chosen = np.argsort(distances, kind='stable')[:k]
    weights = np.exp(-.5 * distances[chosen])
    total = weights.sum()
    effective = float(total ** 2 / (weights @ weights)) if total else 0.
    return pool.iloc[chosen], weights, effective


def stage15_manual(ht_home, ht_away, odds, home_xg, away_xg, side, neighbours):
    import numpy as np
    pool = HISTORY[(HISTORY.HTHG == ht_home) & (HISTORY.HTAG == ht_away)]
    if side == 'Home':
        pool = pool[pool.B365H < pool.B365A]
    elif side == 'Away':
        pool = pool[pool.B365A < pool.B365H]
    selected, weights, effective = stage15_weighted_sample(
        pool, odds, home_xg, away_xg, neighbours)
    rows = []
    if len(selected):
        outcomes = market_outcomes(selected)
        for market in STAGE14_MARKETS:
            probability = float(np.average(outcomes[market].to_numpy(float), weights=weights))
            rows.append({'Market': market, 'Selected neighbours': len(selected),
                         'Effective sample size': round(effective, 1),
                         'Weighted historical %': round(probability * 100, 1),
                         'Research threshold (ESS >= 100)': effective >= 100})
    return pd.DataFrame(rows), len(pool)


def stage15_holdout(history, max_tests=350, neighbours=150):
    import numpy as np
    date_col = next((c for c in ('Date', 'date', 'match_date', 'MatchDate')
                     if c in history.columns), None)
    if not date_col:
        return None, 'No historical match-date column.'
    dates = pd.to_datetime(history[date_col], errors='coerce', dayfirst=True)
    dated = history.loc[dates.notna()].copy()
    dated['_stage15_date'] = dates.loc[dates.notna()]
    dated = dated.sort_values('_stage15_date')
    if len(dated) < 1200:
        return None, 'Not enough dated matches.'
    cutoff = dated['_stage15_date'].iloc[int(len(dated) * .8)]
    train = dated[dated['_stage15_date'] < cutoff]
    test = dated[dated['_stage15_date'] >= cutoff]
    if len(test) > max_tests:
        test = test.iloc[np.linspace(0, len(test)-1, max_tests, dtype=int)]
    records = []
    for _, match in test.iterrows():
        pool = train[(train.HTHG == match.HTHG) & (train.HTAG == match.HTAG)]
        same = pool[(pool.B365H < pool.B365A) if match.B365H < match.B365A
                    else (pool.B365A < pool.B365H)]
        original = pool[pool.fav.between(max(1.01, match.fav-.35), match.fav+.35)]
        original = original[original[xg1].between(max(0, match[xg1]-.40), match[xg1]+.40)]
        original = original[original[xg2].between(max(0, match[xg2]-.40), match[xg2]+.40)]
        # Compare on identical fixtures, and require both approaches to have meaningful evidence.
        if len(original) < 30:
            continue
        chosen, weights, ess = stage15_weighted_sample(same, match.fav, match[xg1], match[xg2], neighbours)
        if ess < 30:
            continue
        actual = market_outcomes(pd.DataFrame([match]))
        orig_y = market_outcomes(original)
        weighted_y = market_outcomes(chosen)
        for market in STAGE14_MARKETS:
            truth = float(actual[market].iloc[0])
            original_p = (float(orig_y[market].sum()) + 1) / (len(original) + 2)
            weighted_p = float(np.average(weighted_y[market].to_numpy(float), weights=weights))
            records.append({'Market': market, 'Original loss': (original_p-truth)**2,
                            'Weighted loss': (weighted_p-truth)**2,
                            'Effective sample': ess})
    if not records:
        return None, 'Too few paired matches with at least 30 effective weighted neighbours.'
    data = pd.DataFrame(records)
    summary = []
    for market, group in data.groupby('Market', sort=False):
        n = len(group)
        summary.append({'Market': market, 'Paired test matches': n,
                        'Original Brier': round(group['Original loss'].mean(), 5),
                        'Weighted Brier': round(group['Weighted loss'].mean(), 5),
                        'Improvement (+ better)': round((group['Original loss']-group['Weighted loss']).mean(), 5),
                        'Average effective sample': round(group['Effective sample'].mean(), 1),
                        'Test start': str(cutoff.date())})
    return pd.DataFrame(summary), None


# Stage 16 — rolling-origin paired validation; research only.
def stage16_rolling_validation(history, max_tests_per_period=180, neighbours=150):
    import numpy as np
    date_col = next((c for c in ('Date', 'date', 'match_date', 'MatchDate')
                     if c in history.columns), None)
    if date_col is None:
        return None, 'No historical match-date column.'
    dates = pd.to_datetime(history[date_col], errors='coerce', dayfirst=True)
    dated = history.loc[dates.notna()].copy()
    dated['_s16_date'] = dates.loc[dates.notna()]
    dated = dated.sort_values('_s16_date').reset_index(drop=True)
    if len(dated) < 1500:
        return None, 'Not enough dated matches for rolling validation.'
    boundaries = [dated['_s16_date'].iloc[int(len(dated)*fraction)]
                  for fraction in (.55, .70, .85)]
    if len(set(boundaries)) != 3:
        return None, 'Cannot create three separate date-based periods.'
    methods = ['Original', 'Same-side fixed', 'Wider same-side', 'Weighted same-side']
    markets = STAGE14_MARKETS
    records = []
    for period_number, start in enumerate(boundaries, 1):
        end = boundaries[period_number] if period_number < 3 else None
        train = dated[dated['_s16_date'] < start]
        test = dated[dated['_s16_date'] >= start]
        if end is not None:
            test = test[test['_s16_date'] < end]
        if len(train) < 500 or len(test) < 50:
            continue
        if len(test) > max_tests_per_period:
            test = test.iloc[np.linspace(0, len(test)-1, max_tests_per_period, dtype=int)]
        train_outcomes = {k: v.to_numpy(float) for k,v in market_outcomes(train).items()
                          if k in markets}
        test_outcomes = {k: v.to_numpy(float) for k,v in market_outcomes(test).items()
                         if k in markets}
        tr = train[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
        tr_side = np.sign(train.B365A.to_numpy(float) - train.B365H.to_numpy(float))
        te = test[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
        te_side = np.sign(test.B365A.to_numpy(float) - test.B365H.to_numpy(float))
        pred = {name:{} for name in methods}
        for i, row in enumerate(te):
            same_score = (tr[:,0] == row[0]) & (tr[:,1] == row[1])
            same_side = same_score & (tr_side == te_side[i]) & (te_side[i] != 0)
            for name, base, xwidth, owidth in [
                ('Original', same_score, .40, .35),
                ('Same-side fixed', same_side, .40, .35),
                ('Wider same-side', same_side, .50, .50),
            ]:
                mask = (base & (np.abs(tr[:,2]-row[2]) <= owidth)
                        & (np.abs(tr[:,3]-row[3]) <= xwidth)
                        & (np.abs(tr[:,4]-row[4]) <= xwidth))
                n = int(mask.sum())
                if n >= 30:
                    pred[name][i] = (n, {market: (train_outcomes[market][mask].sum()+1)/(n+2)
                                          for market in markets})
            indices = np.flatnonzero(same_side)
            if len(indices):
                delta = tr[indices,2:5] - row[2:5]
                dist = (delta[:,0]/.35)**2 + (delta[:,1]/.35)**2 + (delta[:,2]/.35)**2
                selected = np.argsort(dist,kind='stable')[:neighbours]
                selected_indices = indices[selected]
                weights = np.exp(-.5*dist[selected])
                total = weights.sum()
                ess = float(total**2/(weights@weights)) if total > 0 else 0
                if ess >= 30:
                    pred['Weighted same-side'][i] = (ess, {
                        market: float(np.average(train_outcomes[market][selected_indices],weights=weights))
                        for market in markets})
        # Pair every method with original on identical fixtures.
        for method in methods:
            common = sorted(set(pred['Original']) & set(pred[method]))
            if len(common) < 30:
                continue
            for market in markets:
                actual = np.array([test_outcomes[market][i] for i in common])
                original_p = np.array([pred['Original'][i][1][market] for i in common])
                other_p = np.array([pred[method][i][1][market] for i in common])
                loss_original = (original_p-actual)**2
                loss_method = (other_p-actual)**2
                difference = loss_original-loss_method
                se = float(difference.std(ddof=1)/np.sqrt(len(common))) if len(common)>1 else 0
                records.append({
                    'Period': period_number, 'Period begins': str(start.date()),
                    'Period ends': str((end if end is not None else test['_s16_date'].max()).date()),
                    'Market': market, 'Method': method,
                    'Paired fixtures': len(common),
                    'Original coverage': len(pred['Original']),
                    'Method coverage': len(pred[method]),
                    'Original Brier': round(float(loss_original.mean()),5),
                    'Method Brier': round(float(loss_method.mean()),5),
                    'Improvement (+ better)': round(float(difference.mean()),5),
                    'Approx 95% lower': round(float(difference.mean()-1.96*se),5),
                    'Approx 95% upper': round(float(difference.mean()+1.96*se),5),
                    'Mean method sample/ESS': round(float(np.mean([pred[method][i][0] for i in common])),1),
                    'Training matches': len(train),
                })
    if not records:
        return None, 'Insufficient paired predictions across the three periods.'
    return pd.DataFrame(records), None


# Stage 17 — read-only view of GitHub Actions' persisted prospective observations.
st.subheader('Stage 17 · Automatic prospective prediction journal')
st.caption('Predictions are recorded at halftime by a separate scheduled GitHub Action, then settled from the provider. No bets are placed.')
import json as _json17
_stage17_file = Path(__file__).parent / 'data' / 'stage17_predictions.jsonl'
_stage17_url = ('https://raw.githubusercontent.com/pngayton-droid/'
                'football-value-scanner/main/data/stage17_predictions.jsonl')

@st.cache_data(ttl=120, show_spinner=False)
def _load_stage17_remote():
    """Read the public GitHub journal; never send API keys or write to GitHub."""
    response = requests.get(_stage17_url, timeout=8,
                            headers={'Accept': 'text/plain'})
    response.raise_for_status()
    if len(response.content) > 10_000_000:
        raise ValueError('Journal exceeds 10 MB display limit')
    return response.text

if st.button('Refresh Stage 17 journal', key='stage17_refresh'):
    _load_stage17_remote.clear()

_stage17_source = 'GitHub (latest saved journal; refreshes at most every 2 minutes)'
try:
    _stage17_text = _load_stage17_remote()
except (requests.RequestException, ValueError) as _stage17_error:
    _stage17_source = 'Local deployed file (GitHub could not be reached)'
    _stage17_text = (_stage17_file.read_text(encoding='utf-8')
                     if _stage17_file.exists() else '')
    st.caption('GitHub journal temporarily unavailable; showing the deployed copy if present.')

_records17 = []
_invalid17 = 0
for _line17 in _stage17_text.splitlines():
    if not _line17.strip():
        continue
    try:
        _item17 = _json17.loads(_line17)
        if isinstance(_item17, dict):
            _records17.append(_item17)
        else:
            _invalid17 += 1
    except (ValueError, TypeError):
        _invalid17 += 1
st.caption(f'Journal source: {_stage17_source}')
if _invalid17:
    st.warning(f'{_invalid17} malformed journal entries were skipped.')
if not _records17:
    st.info('No automatic observations available yet. Check the GitHub Actions collector.')
else:
    _pending17 = sum(r.get('status') == 'pending' for r in _records17)
    _settled17 = [r for r in _records17 if r.get('status') == 'settled' and r.get('ft_home') is not None and r.get('ft_away') is not None]
    _a17,_b17,_c17 = st.columns(3)
    _a17.metric('Halftime snapshots',len(_records17))
    _b17.metric('Settled',len(_settled17))
    _c17.metric('Pending',_pending17)
    if _records17:
        _latest17 = max(str(r.get('captured_utc','')) for r in _records17)
        st.caption(f'Latest saved halftime snapshot: {_latest17}. Use Refresh Stage 17 journal to check the latest committed predictions.')
        _snapshots17 = pd.DataFrame([{'Match':r.get('match'),'Captured UTC':r.get('captured_utc'),
            'HT score':f"{r.get('ht_home')}-{r.get('ht_away')}", 'Status':r.get('status'),
            'FT score':f"{r.get('ft_home')}-{r.get('ft_away')}" if r.get('status')=='settled' else 'Pending',
            'Model predictions':len(r.get('predictions') or [])} for r in _records17])
        st.dataframe(_snapshots17.tail(150).iloc[::-1],hide_index=True,use_container_width=True)
        st.download_button('Download Stage 17 snapshot journal CSV',_snapshots17.to_csv(index=False).encode('utf-8-sig'),
                           'stage17_snapshots.csv','text/csv',key='stage17_snapshots_export')
    _scores17=[];_detail17=[]
    for _r17 in _settled17:
        _sh17=int(_r17['ft_home'])-int(_r17['ht_home']); _sa17=int(_r17['ft_away'])-int(_r17['ht_away'])
        _truth17={'Home full-time win':int(_r17['ft_home']>_r17['ft_away']),
                  'Away full-time win':int(_r17['ft_home']<_r17['ft_away']),
                  'Home scores in 2H':int(_sh17>=1),'Away scores in 2H':int(_sa17>=1),
                  'Home wins 2H':int(_sh17>_sa17),'Away wins 2H':int(_sh17<_sa17)}
        for _p17 in _r17.get('predictions') or []:
            _market17=_p17.get('market')
            if _market17 not in _truth17:continue
            _prob17=float(_p17['probability']);_actual17=_truth17[_market17]
            _detail17.append({'Match':_r17['match'],'Captured UTC':_r17['captured_utc'],
                'Method':_p17['method'],'Market':_market17,'Probability':_prob17,
                'Actual':_actual17,'Brier loss':(_prob17-_actual17)**2,
                'Sample':_p17.get('sample'),'ESS':_p17.get('ess')})
    if _detail17:
        _df17=pd.DataFrame(_detail17)
        _summary17=_df17.groupby(['Method','Market'],as_index=False).agg(
            Matches=('Brier loss','size'),Brier=('Brier loss','mean'),
            Mean_probability=('Probability','mean'),Actual_frequency=('Actual','mean'))
        st.markdown('**Prospective prediction accuracy — lower Brier is better**')
        st.dataframe(_summary17,hide_index=True,use_container_width=True)
        st.download_button('Download Stage 17 prediction-level CSV',_df17.to_csv(index=False).encode('utf-8-sig'),
                           'stage17_predictions.csv','text/csv',key='stage17_predictions_export')
        st.caption('Methods can have different match coverage. Compare on identical matches before declaring a winner. No price or profit validation is implied.')
    else:
        st.info('Accuracy tables will appear after the provider confirms final scores for recorded matches.')
st.warning('Scheduled collection is best-effort: GitHub Actions may run late or be skipped. Matches missed at halftime are deliberately not backfilled. Check workflow history and API usage; this is not a guaranteed continuous feed.')

# Stage 18 — read-only bookmaker quote and prospective paper-return display.
# All prices must originate from recorded halftime snapshots, never reconstructed later.
st.subheader('Stage 18 · Recorded bookmaker prices and paper results')
st.caption('Observed API quotes only. Prices can be delayed, suspended, unavailable or too small to fill; no bets are placed.')
_stage18_rows = []
for _r18 in _records17:
    _settled18 = (_r18.get('status') == 'settled' and
                  _r18.get('ft_home') is not None and _r18.get('ft_away') is not None)
    if _settled18:
        _fh18, _fa18 = int(_r18['ft_home']), int(_r18['ft_away'])
        _sh18 = _fh18 - int(_r18['ht_home'])
        _sa18 = _fa18 - int(_r18['ht_away'])
        _outcomes18 = {
            'Home full-time win': _fh18 > _fa18,
            'Away full-time win': _fh18 < _fa18,
            'Home wins 2H': _sh18 > _sa18,
            'Away wins 2H': _sh18 < _sa18,
        }
    else:
        _outcomes18 = {}
    for _p18 in _r18.get('predictions') or []:
        _market18 = _p18.get('market')
        try:
            _price18 = float(_p18['live_odds'])
            _prob18 = float(_p18['probability'])
        except (KeyError, ValueError, TypeError):
            continue
        if not (math.isfinite(_price18) and _price18 > 1 and
                math.isfinite(_prob18) and 0 < _prob18 < 1):
            continue
        _book18 = str(_p18.get('live_bookmaker') or 'Unknown')
        _actual18 = _outcomes18.get(_market18)
        _net_win18 = (_price18 - 1) * (1 - commission if _book18 == 'Betfair Exchange' else 1)
        _expected18 = 100 * (_prob18 * (1 + _net_win18) - 1)
        _return18 = (_net_win18 if _actual18 else -1.) if _actual18 is not None else None
        _stage18_rows.append({
            'Match': _r18.get('match'), 'Captured UTC': _r18.get('captured_utc'),
            'Odds captured UTC': _r18.get('live_odds_captured_utc'),
            'Method': _p18.get('method'), 'Market': _market18,
            'Bookmaker': _book18, 'Observed odds': _price18,
            'Available back size': _p18.get('available_size'),
            'Model probability %': round(_prob18 * 100, 2),
            'Model fair odds': round(1 / _prob18, 3),
            'Expected ROI % (model)': round(_expected18, 2),
            'Result': ('Won' if _actual18 else 'Lost') if _actual18 is not None else 'Pending',
            'Paper P/L per £1': round(_return18, 4) if _return18 is not None else None,
        })
if not _stage18_rows:
    st.info('No recorded bookmaker quotes yet. Existing Stage 17 snapshots without prices remain valid; only future priced snapshots will appear here.')
else:
    _df18 = pd.DataFrame(_stage18_rows)
    _priced18 = len(_df18)
    _finished18 = _df18[_df18['Result'].isin(['Won', 'Lost'])]
    _col18a, _col18b, _col18c = st.columns(3)
    _col18a.metric('Priced model selections', _priced18)
    _col18b.metric('Settled priced selections', len(_finished18))
    _col18c.metric('Paper ROI (flat £1)',
                   f"{_finished18['Paper P/L per £1'].mean()*100:+.1f}%" if len(_finished18) else 'Awaiting results')
    _only_value18 = st.checkbox('Show model-positive expected ROI only', value=False, key='stage18_positive_only')
    _shown18 = (_df18[_df18['Expected ROI % (model)'] > 0] if _only_value18 else _df18)
    st.dataframe(_shown18.iloc[::-1], hide_index=True, use_container_width=True)
    st.download_button('Download Stage 18 priced predictions CSV',
                       _df18.to_csv(index=False).encode('utf-8-sig'),
                       'stage18_priced_predictions.csv', 'text/csv', key='stage18_export')
    if len(_finished18):
        _group18 = _finished18.groupby(['Method', 'Market'], as_index=False).agg(
            Selections=('Paper P/L per £1', 'size'),
            Paper_profit_per_1_staked=('Paper P/L per £1', 'sum'),
            Paper_ROI_pct=('Paper P/L per £1', lambda values: round(values.mean() * 100, 2)))
        st.markdown('**Settled paper results by model and market**')
        st.dataframe(_group18, hide_index=True, use_container_width=True)
    st.caption('One hypothetical £1 back bet per priced model prediction, including negative-value quotes. '
               'Betfair winning profit is adjusted using the sidebar commission setting; other bookmaker '
               'prices assume no commission. These are not executable fills, and several models can '
               'predict the same match and market. Overall paper ROI counts each model prediction '
               'separately; it is not the return of a tested staking strategy.')
st.warning('Stage 18 values depend on the worker saving genuine halftime quotes. '
           'Expected ROI is based on uncalibrated model probabilities, not a proven edge. '
           'No quote means no paper trade, and historic unpriced snapshots cannot be backfilled.')

# Stage 19 — halftime research shortlist, deduplicated by observed market quote.
# Keeps the Stage 18 raw audit intact; does not create new model probabilities.
st.subheader('Stage 19 · Unique halftime value shortlist (research)')
st.caption('One candidate per match, market and observed bookmaker quote. Models agreeing on the same quote are counted once. This is NOT the dual-model probability engine yet.')
if not _stage18_rows:
    st.info('Waiting for recorded halftime bookmaker quotes from Stage 18.')
else:
    _v19 = _df18[_df18['Expected ROI % (model)'] > 0].copy()
    if _v19.empty:
        st.info('No model-positive priced predictions recorded yet.')
    else:
        # Treat bookmaker quotes at different timestamps as separate observations,
        # but never multiply the same quote by the number of modelling methods.
        _keys19 = ['Match', 'Captured UTC', 'Odds captured UTC', 'Market', 'Bookmaker', 'Observed odds']
        _group19 = _v19.groupby(_keys19, dropna=False, sort=False)
        _unique19 = _group19.agg(
            Models_agreeing=('Method', 'nunique'),
            Methods=('Method', lambda s: ', '.join(sorted(set(map(str, s))))),
            Lowest_model_EV_pct=('Expected ROI % (model)', 'min'),
            Highest_model_EV_pct=('Expected ROI % (model)', 'max'),
            Lowest_probability_pct=('Model probability %', 'min'),
            Highest_probability_pct=('Model probability %', 'max'),
            Result=('Result', 'first'),
            Paper_PL_per_1=('Paper P/L per £1', 'first'),
        ).reset_index()
        _unique19['Extreme price review'] = _unique19['Observed odds'] >= 10
        _settled19 = _unique19[_unique19['Result'].isin(['Won', 'Lost'])]
        _a19, _b19, _c19 = st.columns(3)
        _a19.metric('Unique positive-value quotes', len(_unique19))
        _b19.metric('Distinct matches', _unique19['Match'].nunique())
        _c19.metric('Unique quote paper ROI',
                    f"{_settled19['Paper_PL_per_1'].mean()*100:+.1f}%" if len(_settled19) else 'Awaiting results')
        _review19 = st.checkbox('Show only extreme-price quotes (10.00+)', value=False, key='stage19_extreme')
        _display19 = _unique19[_unique19['Extreme price review']] if _review19 else _unique19
        st.dataframe(_display19.iloc[::-1], hide_index=True, use_container_width=True)
        st.download_button('Download Stage 19 unique quote research CSV',
                           _unique19.to_csv(index=False).encode('utf-8-sig'),
                           'stage19_unique_value_quotes.csv', 'text/csv', key='stage19_export')
        st.caption('Research-only: ROI assumes one hypothetical £1 selection per distinct quote, not one per model. Different markets in the same match remain separate. Agreement does not validate probabilities, and 10.00+ is a review flag, not a rejection rule.')

st.subheader('Stage 16 · Rolling historical accuracy comparison')
st.caption('Three chronological test periods, six priority markets. Research only; live scanner unchanged.')
with st.expander('Compare original, same-side and weighted methods across three periods'):
    st.write('Each method is evaluated against the original on identical fixtures, '
             'using only matches before the test period for training. '
             'The weighted method uses 150 nearest neighbours and requires at least 30 effective matches.')
    if st.button('Run Stage 16 rolling validation', key='stage16_run'):
        with st.spinner('Testing three historical periods…'):
            table16, error16 = stage16_rolling_validation(HISTORY)
        if error16:
            st.warning(error16)
        else:
            st.session_state['stage16_results'] = table16
    if 'stage16_results' in st.session_state:
        table16 = st.session_state['stage16_results']
        st.dataframe(table16, hide_index=True, use_container_width=True)
        st.download_button('Download Stage 16 results CSV',
                           table16.to_csv(index=False).encode('utf-8-sig'),
                           'stage16_rolling_validation.csv', 'text/csv', key='stage16_download')
    st.warning('These periods reuse earlier training data and are not independent experiments. '
               'The approximate intervals ignore fixture clustering and multiple comparisons. '
               'The model choices were informed by earlier tests on this database, so these '
               'results are exploratory, not proof of an edge or future profitability.')


st.subheader('Stage 15 · Weighted historical neighbours laboratory')
st.caption('Research only: six priority markets; live scanner and tracker remain unchanged.')
with st.expander('Explore weighted matches and effective sample size'):
    st.write('Uses the manual halftime score, odds and xG from the sidebar. '
             'Matches must have the same halftime score and favourite side. '
             'Closer odds and xG receive more weight; this does not create extra evidence.')
    stage15_side = st.selectbox('Favourite side for Stage 15', ['Home', 'Away'],
                                key='stage15_side')
    stage15_k = st.slider('Maximum nearest historical matches', 50, 500, 150, 25,
                          key='stage15_k')
    stage15_table, stage15_pool = stage15_manual(
        ht_h, ht_a, fav, xgh, xga, stage15_side, stage15_k)
    st.write(f'Historical pool with matching score and favourite side: {stage15_pool:,}')
    if stage15_table.empty:
        st.warning('No historical matches for this scenario.')
    else:
        st.dataframe(stage15_table, hide_index=True, use_container_width=True)
        st.download_button('Download Stage 15 weighted scenario CSV',
                           stage15_table.to_csv(index=False).encode(),
                           'stage15_weighted_scenario.csv', 'text/csv')
    st.caption('Effective sample size accounts for unequal weights. A low ESS means '
               'the probability is unstable even when many matches were selected.')
with st.expander('Test weighted predictions on later matches'):
    st.write('Paired chronological holdout: original fixed-width method versus '
             '150 nearest same-side weighted neighbours, on the same later fixtures.')
    if st.button('Run Stage 15 weighted holdout', key='stage15_run'):
        with st.spinner('Testing weighted neighbours against later results…'):
            table15, error15 = stage15_holdout(HISTORY)
        if error15:
            st.warning(error15)
        else:
            st.session_state['stage15_holdout'] = table15
    if 'stage15_holdout' in st.session_state:
        st.dataframe(st.session_state['stage15_holdout'], hide_index=True,
                     use_container_width=True)
        st.download_button('Download Stage 15 holdout CSV',
                           st.session_state['stage15_holdout'].to_csv(index=False).encode(),
                           'stage15_weighted_holdout.csv', 'text/csv')
    st.warning('Exploratory holdout, not proof of an edge. Neighbour count and distance '
               'scales have not been independently tuned; prices and returns are not tested.')

st.subheader('Stage 14 · Parallel favourite-side research')
st.caption('Compare original and improved matching methods without changing the live scanner.')
with st.expander('Compare matching methods for the manual halftime scenario'):
    manual_side = st.selectbox('Which team was the pre-match favourite?',
                               ['Unknown', 'Home', 'Away'], key='stage14_manual_side')
    if manual_side == 'Unknown':
        st.info('Choose Home or Away to enable the parallel comparison.')
    else:
        stage14_show(ht_h, ht_a, fav, xgh, xga, manual_side, xg_width, odds_width)

st.subheader('Stage 13 · Six-market accuracy and stability laboratory')
st.caption('Research only. This leaves the live scanner, Stage 10 tracker and all 18 markets unchanged.')
with st.expander('Compare six key markets across two later historical periods'):
    st.write('The original matching filters are compared with wider filters and matching '
             'the pre-match favourite on the same home/away side. Each comparison uses '
             'the same fixtures for both methods, so coverage differences do not '
             'distort the accuracy comparison.')
    st.caption('Validation uses the earliest 70% for training and the next 15% for testing. '
               'Later confirmation trains on the earliest 85% and tests on the final 15%. '
               'At most 400 evenly spaced fixtures are evaluated per period to keep the app responsive.')
    if st.button('Run Stage 13 paired validation', key='stage13_run'):
        with st.spinner('Checking six markets across both historical periods…'):
            stage13_table, stage13_error = stage13_paired_validation(HISTORY)
        if stage13_error:
            st.error(stage13_error)
        else:
            st.session_state['stage13_results'] = stage13_table
    if 'stage13_results' in st.session_state:
        stage13_table = st.session_state['stage13_results']
        chosen_market = st.selectbox(
            'Market to inspect',
            ['All six markets'] + ['Home full-time win', 'Away full-time win',
             'Home scores in 2H', 'Away scores in 2H',
             'Home wins 2H', 'Away wins 2H'], key='stage13_market')
        shown = (stage13_table if chosen_market == 'All six markets'
                 else stage13_table[stage13_table['Market'] == chosen_market])
        st.dataframe(shown, hide_index=True, use_container_width=True)
        st.download_button('Download complete Stage 13 results CSV',
                           stage13_table.to_csv(index=False).encode('utf-8-sig'),
                           'stage13_paired_validation.csv', 'text/csv',
                           key='stage13_download')
        st.warning('Exploratory comparisons only. The later period is a confirmation check, '
                   'not an untouched test after choosing a winning method. The approximate '
                   'interval does not adjust for fixture dependence or multiple comparisons. '
                   'A lower Brier score does not prove profitable betting, and no live '
                   'matching settings are changed automatically.')

st.subheader('Stage 11 · Historical sample quality laboratory')
with st.expander('Inspect filter losses and safer sample-width experiments'):
    show_stage11_diagnostics(ht_h, ht_a, fav, xgh, xga, xg_width, odds_width)

d = comparable_matches(ht_h, ht_a, fav, xgh, xga, xg_width, odds_width)
markets = market_outcomes(d)
st.subheader(f'{home} v {away} · HT {ht_h}–{ht_a}')
a,b,c=st.columns(3)
a.metric('Comparable matches',f'{len(d):,}')
b.metric('Historical data', f'{len(HISTORY):,} usable / 32,653 source')
c.metric('Market types',len(markets))
st.warning('Screening estimates only: these historical matches are not a calibrated predictive model. Overlapping markets, odds selection and out-of-sample validation matter.')
st.markdown('**Enter available Betfair back prices for the markets you want to check.** Leave other prices at zero.')
prices={}
cols=st.columns(3)
for i,k in enumerate(markets):
    prices[k]=cols[i%3].number_input(k+' · price',min_value=0.,max_value=1000.,value=0.,step=0.05,key='p'+str(i))
rows=[]
for k,v in markets.items():
    n=len(v);wins=int(v.sum());p=wins/n if n else 0
    low=wilson_lower(wins,n)
    price=prices[k];be=1/(1+(price-1)*(1-commission)) if price>1 else None
    verdict=('RESEARCH CANDIDATE' if n>=min_n and be is not None and low>be else 'NO BET') if price>1 else 'NO PRICE'
    rows.append(dict(Market=k,Matches=n,Wins=wins,Strike_rate=f'{p:.1%}' if n else '—',Fair_odds=round(1/p,2) if p else None,Wilson_95pct_lower=f'{low:.1%}' if n else '—',Back_price=price if price>1 else None,Break_even=f'{be:.1%}' if be else None,Screen=verdict))
result=pd.DataFrame(rows)
st.dataframe(result,hide_index=True,use_container_width=True)
st.download_button('Export comparison CSV',result.to_csv(index=False).encode(),'scanner_comparison.csv','text/csv')
st.caption('Markets requiring goal timestamps (next goal), halftime corners/cards, Asian handicap prices or reliable live feeds are deliberately not shown as validated here. No bets are placed.')







# CLEAN LIVE SCANNER — all API access is on button clicks.
st.divider()
st.header("🔎 Automatic Halftime Scanner")
st.caption("Checks paginated live matches for halftime, xG, opening prices and bookmaker coverage. No automatic betting signals.")
MAX_LIVE_PAGES = st.slider("Maximum live fixture pages to check", 1, 10, 3, help="Each page is one API request (up to 100 matches). Increase only when needed on busy matchdays.")
SCAN_SCOPE = st.radio("Competition coverage", ["All leagues (recommended)", "Priorities 1–3 only", "Priority 1 only"], horizontal=True, help="All leagues keeps maximum coverage; priority tiers determine display order. Unknown competition names are never silently classified as major leagues.")
st.caption("Priorities affect display and optional filtering only. Fixture pages are collected before filtering; a page limit can still cause incomplete coverage.")
AUTO_COMPETITION_LOOKUP = st.checkbox('Resolve missing competition names during scan (up to 8 extra API requests)', value=True, help='Only one match-detail request per new competition ID. Names are cached in this Streamlit session; a restart clears the cache.')

# Display classification uses league/country text only, not unverified provider IDs.
# The provider's actual competition fields are shown in diagnostics below.
PRIORITY_ONE = {
    'england': ['premier league', 'championship', 'league one', 'league two', 'efl league 1', 'efl league 2'],
    'italy': ['serie a'], 'france': ['ligue 1', 'ligue one'],
    'germany': ['bundesliga'], 'spain': ['la liga', 'laliga', 'primera division'],
    'netherlands': ['eredivisie'], 'portugal': ['primeira liga', 'liga portugal'],
    'belgium': ['pro league', 'first division a', 'jupiler'],
    'scotland': ['premiership', 'scottish premier'],
}
PRIORITY_TWO = {
    'england': ['national league', 'national league north', 'national league south', 'women s super league'],
    'germany': ['2. bundesliga', '2 bundesliga', 'zweite bundesliga'],
    'italy': ['serie b'], 'france': ['ligue 2'],
    'spain': ['segunda', 'la liga 2', 'laliga 2'],
    'netherlands': ['eerste divisie'], 'scotland': ['championship'],
    'turkey': ['super lig', 'süper lig'], 'austria': ['bundesliga'],
    'switzerland': ['super league'], 'denmark': ['superliga'],
    'norway': ['eliteserien'], 'sweden': ['allsvenskan'],
}
PRIORITY_THREE = ['champions league', 'europa league', 'conference league',
                  'fa cup', 'efl cup', 'carabao cup', 'copa del rey', 'coppa italia',
                  'dfb pokal', 'coupe de france', 'scottish cup']


def normalise_label(value):
    value = str(value or '').casefold().replace('ü', 'u').replace('é', 'e')
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()


def _usable_competition_metadata(record):
    """Extract only explicit provider names, never infer them from an ID."""
    if not isinstance(record, dict):
        return '', ''
    for key in ('competition', 'league', 'tournament'):
        obj = record.get(key)
        if isinstance(obj, dict):
            name = obj.get('name') or obj.get('title') or obj.get('short_name') or ''
            country = obj.get('country_name') or obj.get('country') or ''
            if isinstance(country, dict):
                country = country.get('name') or ''
            if name:
                return str(name), str(country)
    name = record.get('competition_name') or record.get('league_name') or record.get('tournament_name') or ''
    country = record.get('country_name') or record.get('country') or ''
    if isinstance(country, dict):
        country = country.get('name') or ''
    return str(name), str(country)


def enriched_competition_match(match):
    """Use metadata from a successfully fetched match detail only if IDs match."""
    match = dict(match)
    ident = str(match.get('competition_id') or match.get('league_id') or '')
    if not ident:
        return match
    record = st.session_state.get('verified_competition_metadata', {}).get(ident)
    if record:
        name, country = record['name'], record['country']
        match['competition_name'] = name
        match['country_name'] = country
        match['competition_resolution_source'] = 'Match detail API response'
    return match


def competition_details(match):
    # Provider formats may differ. Retain raw fields in coverage diagnostics.
    raw = None
    for key in ('competition', 'league', 'tournament'):
        if match.get(key):
            raw = match[key]
            break
    if isinstance(raw, dict):
        name = raw.get('name') or raw.get('title') or raw.get('short_name') or ''
        country = raw.get('country') or raw.get('country_name') or ''
        if isinstance(country, dict):
            country = country.get('name') or ''
        ident = raw.get('id') or raw.get('competition_id') or ''
    else:
        name, country, ident = raw or '', '', ''
    name = name or match.get('league_name') or match.get('competition_name') or match.get('tournament_name') or ''
    country = country or match.get('country_name') or match.get('country') or ''
    if isinstance(country, dict):
        country = country.get('name') or ''
    ident = ident or match.get('league_id') or match.get('competition_id') or ''
    return str(name), str(country), str(ident)


def competition_priority(match):
    name, country, _ = competition_details(match)
    n, c = normalise_label(name), normalise_label(country)
    if not n:
        return 4, 'Unknown competition'
    # Continental competitions don't have a single country.
    if any(normalise_label(term) in n for term in PRIORITY_THREE):
        return 3, 'Priority 3 — continental/cup'
    # If country is missing, classify only distinctive names whose competition is unambiguous.
    # Generic labels such as 'Premier League', 'Championship' or 'Bundesliga'
    # remain unclassified until the provider supplies a country.
    if not c:
        distinctive = {
            'la liga': 1, 'laliga': 1, 'eredivisie': 1, 'primeira liga': 1,
            'liga portugal': 1, 'ligue 1': 1, 'ligue 2': 2,
            'eliteserien': 2, 'allsvenskan': 2, 'eerste divisie': 2,
            'copa del rey': 3, 'coppa italia': 3, 'dfb pokal': 3,
            'puchar polski': 3, 'turkiye kupasi': 3, 'turkiye kupas': 3,
        }
        tier = distinctive.get(n)
        if tier:
            return tier, f'Priority {tier} — name only (country unverified)'
        return 4, 'Unclassified — missing country'
    for country_key, names in PRIORITY_TWO.items():
        if normalise_label(country_key) in c and any(normalise_label(term) == n for term in names):
            return 2, 'Priority 2'
    for country_key, names in PRIORITY_ONE.items():
        if normalise_label(country_key) in c and any(normalise_label(term) == n for term in names):
            return 1, 'Priority 1'
    return 4, 'Other / unclassified'


def ordered_matches(matches):
    return sorted(matches, key=lambda m: (competition_priority(m)[0],
                                          normalise_label(competition_details(m)[0]),
                                          match_name(m)))


def selected_matches(matches):
    if SCAN_SCOPE == 'All leagues (recommended)':
        return ordered_matches(matches)
    limit = 1 if SCAN_SCOPE == 'Priority 1 only' else 3
    return ordered_matches([m for m in matches if competition_priority(m)[0] <= limit])


def show_coverage(matches, title='Live fixture coverage'):
    st.subheader(title)
    rows = []
    for m in matches:
        league, country, ident = competition_details(m)
        _, tier = competition_priority(m)
        rows.append({'Priority': tier, 'Country': country or 'Not supplied',
                     'Competition': league or 'Not supplied',
                     'Competition ID': ident or 'Not supplied',
                     'Match': match_name(m), 'At halftime': is_halftime(m)})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info('No live fixtures returned.')
    unknown = sum(competition_priority(m)[0] == 4 for m in matches)
    if unknown:
        st.caption(f'{unknown} fixtures are outside the named priorities or have incomplete competition metadata. All-leagues mode retains them.')
    with st.expander('Provider competition fields — inspect before adding exact IDs'):
        for m in matches[:5]:
            st.json({'match': match_name(m),
                     'competition': m.get('competition'), 'league': m.get('league'),
                     'tournament': m.get('tournament'),
                     'league_name': m.get('league_name'),
                     'country': m.get('country'),
                     'competition_id': m.get('competition_id')})

API_BASE = "https://api.thestatsapi.com/api/football/matches"
HT_STATES = {"ht", "halftime", "half_time", "half-time", "half time", "half_time_break"}


def api_get(path="", params=None):
    response = requests.get(
        API_BASE + path,
        headers={"Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"},
        params=params,
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def live_matches():
    """Fetch live fixtures across pages; do not silently treat a partial scan as complete."""
    found = {}
    total_pages = None
    page = 0
    for page in range(1, MAX_LIVE_PAGES + 1):
        payload = api_get(params={"status": "live", "per_page": 100, "page": page})
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError(f"Unexpected live match list on page {page}")
        for match in data:
            if isinstance(match, dict) and match.get("id"):
                found[str(match["id"])] = match
        meta = payload.get("meta") or {}
        if total_pages is None:
            try:
                total_pages = int(meta["total_pages"])
            except (KeyError, TypeError, ValueError):
                total_pages = None
        if total_pages is not None and page >= total_pages:
            break
        if len(data) < 100:
            break
    st.session_state["live_coverage_pages_checked"] = page
    st.session_state["live_coverage_reported_pages"] = total_pages
    st.session_state["live_coverage_all_matches"] = list(found.values())
    if total_pages is not None and total_pages > MAX_LIVE_PAGES:
        st.warning(f"Partial fixture scan: API reports {total_pages} pages, but the limit is {MAX_LIVE_PAGES}. Increase the limit to cover every match.")
    elif total_pages is None and len(data) == 100 and page == MAX_LIVE_PAGES:
        st.warning("Fixture scan may be incomplete: last page was full and the API supplied no usable total_pages value.")
    return [enriched_competition_match(m) for m in found.values()]


def resolve_competitions_from_match_details(matches, limit=8):
    """Optional, bounded diagnostic. Match detail route may not be supported."""
    st.session_state.setdefault('verified_competition_metadata', {})
    known = st.session_state['verified_competition_metadata']
    report = []
    seen = set()
    for match in matches:
        _, _, ident = competition_details(match)
        if not ident or ident in seen or ident in known:
            continue
        seen.add(ident)
        if len(report) >= limit:
            break
        match_id = match.get('id')
        try:
            payload = api_get(f'/{match_id}')
            data = payload.get('data') if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                report.append({'Competition ID': ident, 'Result': 'No match-detail object', 'Name': ''})
                continue
            # Do not assign a name from a different competition.
            detail_id = data.get('competition_id') or data.get('league_id')
            if detail_id is not None and str(detail_id) != ident:
                report.append({'Competition ID': ident, 'Result': 'ID mismatch', 'Name': ''})
                continue
            name, country = _usable_competition_metadata(data)
            if not name and isinstance(data.get('match'), dict):
                name, country = _usable_competition_metadata(data['match'])
            if name:
                known[ident] = {'name': name, 'country': country}
                report.append({'Competition ID': ident, 'Result': 'Name resolved' if not country else 'Name and country resolved', 'Name': f'{name} ({country})' if country else name})
            else:
                report.append({'Competition ID': ident, 'Result': 'Competition name missing', 'Name': ''})
        except requests.RequestException as exc:
            report.append({'Competition ID': ident, 'Result': f'Match detail unavailable ({getattr(getattr(exc, "response", None), "status_code", "request error")})', 'Name': ''})
        except (ValueError, TypeError, KeyError):
            report.append({'Competition ID': ident, 'Result': 'Unexpected response', 'Name': ''})
    return report


def is_halftime(match):
    live = match.get("live") or {}
    if not isinstance(live, dict):
        live = {}
    fields = [match.get("match_status"), match.get("status_short"),
              live.get("match_status"), live.get("period"), live.get("status")]
    return any(str(v).strip().lower() in HT_STATES for v in fields if v is not None)


def first_half_xg(payload):
    data = payload.get("data") or {}
    meta = data.get("meta") or {}
    status = str(meta.get("match_status") or meta.get("period") or "").lower().strip()
    if status not in HT_STATES:
        return None, None
    stats = data.get("stats") or {}
    values = (stats.get("expected_goals") or {}).get("all") or {}
    try:
        h, a = float(values["home"]), float(values["away"])
        if all(math.isfinite(x) and x >= 0 for x in (h, a)):
            return h, a
    except (TypeError, ValueError, KeyError):
        pass
    return None, None




def positive_odds(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 1 else None
    except (ValueError, TypeError):
        return None


def opening_favourite(payload):
    books = (payload.get("data") or {}).get("bookmakers") or []
    candidates = []
    for book in books:
        if not isinstance(book, dict):
            continue
        match_odds = (book.get("markets") or {}).get("match_odds") or {}
        h = positive_odds((match_odds.get("home") or {}).get("opening"))
        a = positive_odds((match_odds.get("away") or {}).get("opening"))
        if h is None or a is None:
            continue
        side = "Home" if h < a else "Away" if a < h else "Level"
        candidates.append((str(book.get("bookmaker", "Unknown")), side, min(h, a)))
    if not candidates:
        return "Unknown", None, "Unavailable", 0
    preferred = next((c for c in candidates if c[0].lower() == "pinnacle"), candidates[0])
    return preferred[1], preferred[2], preferred[0], len(candidates)


def bookmaker_names(payload):
    books = (payload.get("data") or {}).get("bookmakers") or []
    return [str(b.get("bookmaker", "Unknown")) for b in books if isinstance(b, dict)]


def match_name(match):
    home = (match.get("home_team") or {}).get("name", "Home")
    away = (match.get("away_team") or {}).get("name", "Away")
    return f"{home} v {away}"


# Read-only diagnostic: inspect the live-stats fields used for halftime xG.
# Does not change the filtering, fair odds, or live scanner behaviour.
st.subheader("🧪 Halftime xG diagnostics")
st.caption("Choose a live match to inspect the provider's status and expected-goals fields. No API key is displayed.")
if st.button("Find matches for xG diagnostics", key="xg_diag_find"):
    try:
        st.session_state["xg_diag_matches"] = selected_matches(live_matches())
    except (requests.RequestException, ValueError, KeyError) as exc:
        st.error(f"Could not retrieve live matches: {exc}")

_diag_matches = st.session_state.get("xg_diag_matches", [])
if _diag_matches:
    _diag_choices = {f"{match_name(m)} [{m['id']}]": m for m in _diag_matches}
    _diag_selected = st.selectbox("Match to inspect", list(_diag_choices), key="xg_diag_match")
    if st.button("Inspect halftime xG response", key="xg_diag_inspect"):
        _diag_match = _diag_choices[_diag_selected]
        try:
            _diag_response = api_get(f"/{_diag_match['id']}/live-stats")
            _diag_data = _diag_response.get("data") or {}
            _diag_meta = _diag_data.get("meta") or {}
            _diag_stats = _diag_data.get("stats") or {}
            _diag_xg = _diag_stats.get("expected_goals")
            _diag_values = (_diag_xg or {}).get("all") if isinstance(_diag_xg, dict) else None
            _diag_h, _diag_a = first_half_xg(_diag_response)
            st.json({
                "match": match_name(_diag_match),
                "list_live_status": (_diag_match.get("live") or {}).get("match_status"),
                "stats_meta": _diag_meta,
                "stats_available_keys": list(_diag_stats.keys()),
                "expected_goals_raw": _diag_xg,
                "expected_goals_all": _diag_values,
                "accepted_halftime_xg": {"home": _diag_h, "away": _diag_a},
            })
            if _diag_h is None or _diag_a is None:
                st.warning("xG was not accepted. Compare stats_meta.match_status with expected_goals_raw to see whether the status or the values are missing.")
            else:
                st.success("Halftime xG successfully extracted.")
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            st.error(f"Live-stats diagnostic failed: {exc}")



st.subheader('🗂️ Competition-name lookup — diagnostic')
st.caption('Optional test: checks one match-detail request per unknown competition (maximum 8). If the provider does not expose league names, nothing is guessed and All leagues remains safe. This may consume trial API requests.')
if st.button('Test competition-name lookup (up to 8 requests)', key='competition_name_lookup'):
    try:
        _lookup_matches = st.session_state.get('live_coverage_all_matches') or live_matches()
        _lookup_report = resolve_competitions_from_match_details(_lookup_matches)
        if _lookup_report:
            st.dataframe(pd.DataFrame(_lookup_report), hide_index=True, use_container_width=True)
        else:
            st.info('No new competition IDs to test. Previously resolved names are retained for this session.')
        st.caption(f"Cached competition names in this session: {len(st.session_state.get('verified_competition_metadata', {}))}")
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        st.warning(f'Lookup could not complete: {exc}')

if st.button("🔍 Run Complete Halftime Scan", key="clean_ht_scan"):
    try:
        st.session_state["stage10_scan_token"] = datetime.now(timezone.utc).isoformat()
        # Clear any previous snapshot so old prices cannot masquerade as current.
        st.session_state['research_ht_rows'] = []
        st.session_state['research_live_quotes'] = {}
        st.session_state['auto_estimates'] = {}
        all_matches = live_matches()
        if AUTO_COMPETITION_LOOKUP:
            _new_lookup = resolve_competitions_from_match_details(all_matches, limit=8)
            if _new_lookup:
                st.caption(f'Competition metadata lookup: {len(_new_lookup)} new IDs checked; {sum("resolved" in r["Result"].lower() for r in _new_lookup)} names found. Up to 8 extra API requests.')
            all_matches = [enriched_competition_match(m) for m in all_matches]
        matches = selected_matches(all_matches)
        halftime = [m for m in matches if is_halftime(m)]
        st.write(f"Fixture pages actually checked: {st.session_state.get('live_coverage_pages_checked', 'Unknown')}")
        reported = st.session_state.get('live_coverage_reported_pages')
        st.write(f"API-reported total pages: {reported if reported is not None else 'Not supplied'}")
        st.write(f"Live matches returned (before filtering): {len(all_matches)}")
        st.write(f"Matches in selected scope: {len(matches)}")
        st.caption(f"Competition names cached this session: {len(st.session_state.get('verified_competition_metadata', {}))}")
        with st.expander('Competition coverage and priority diagnostics'):
            show_coverage(all_matches)
        st.write(f"Live matches returned: {len(matches)}")
        st.write(f"Halftime matches detected: {len(halftime)}")
        if not halftime:
            st.info("No halftime matches detected in the checked fixture pages. Try again during live fixtures.")
            with st.expander("Inspect status labels"):
                for m in matches[:15]:
                    st.write({"Match": match_name(m), "live": m.get("live")})
        else:
            rows = []
            st.session_state["research_live_quotes"] = {}
            st.session_state["auto_estimates"] = {}
            for m in halftime:
                match_id = str(m["id"])
                score = m.get("score") or {}
                ht_h, ht_a = score.get("half_time_home"), score.get("half_time_away")
                # When explicitly at HT, current score is a fallback if HT-specific keys are missing.
                if ht_h is None and ht_a is None and is_halftime(m):
                    ht_h, ht_a = score.get("home"), score.get("away")
                xgh = xga = opening = None
                favourite, source, source_count = "Unknown", "Unavailable", 0
                books = []
                issues = []
                try:
                    xgh, xga = first_half_xg(api_get(f"/{match_id}/live-stats"))
                except (requests.RequestException, ValueError, TypeError) as e:
                    issues.append(f"xG: {e}")
                try:
                    favourite, opening, source, source_count = opening_favourite(
                        api_get(f"/{match_id}/odds"))
                except (requests.RequestException, ValueError, TypeError) as e:
                    issues.append(f"Opening odds: {e}")
                try:
                    live_odds_payload = api_get(f"/{match_id}/odds/live")
                    books = bookmaker_names(live_odds_payload)
                    st.session_state["research_live_quotes"][match_id] = live_odds_payload
                except (requests.RequestException, ValueError, TypeError) as e:
                    issues.append(f"Live odds: {e}")
                complete = (ht_h is not None and ht_a is not None and xgh is not None
                            and xga is not None and opening is not None
                            and favourite in ("Home", "Away") and bool(books))
                # Use the SAME filtering and market functions as the manual scanner.
                estimates = None
                if (ht_h is not None and ht_a is not None and xgh is not None
                        and xga is not None and opening is not None):
                    try:
                        sample = comparable_matches(int(ht_h), int(ht_a), opening,
                                                    xgh, xga, xg_width, odds_width)
                        estimates = historical_estimates(sample)
                    except (ValueError, TypeError):
                        issues.append('Historical comparison: invalid score or inputs')
                if estimates is not None:
                    if 'auto_estimates' not in st.session_state:
                        st.session_state['auto_estimates'] = {}
                    st.session_state['auto_estimates'][match_id] = estimates
                league, country, _ = competition_details(m)
                _, priority = competition_priority(m)
                rows.append({
                    "Priority": priority, "Competition": league or "Not supplied", "Country": country or "Not supplied",
                    "Match": match_name(m), "Match ID": match_id,
                    "HT score": f"{ht_h}-{ht_a}" if ht_h is not None and ht_a is not None else "Unavailable",
                    "Home HT xG": xgh, "Away HT xG": xga,
                    "Opening favourite": favourite, "Opening odds": opening,
                    "Opening bookmaker": source, "Opening sources": source_count,
                    "Comparable matches": (int(estimates['Matches'].iloc[0])
                                           if estimates is not None else None),
                    "Sample sufficient": (bool(estimates['Matches'].iloc[0] >= min_n)
                                          if estimates is not None else False),
                    "Live bookmakers": len(books),
                    "Betfair Exchange": any("betfair exchange" in b.lower() for b in books),
                    "Data status": "Inputs found — verify" if complete else "Incomplete",
                    "Request errors": "; ".join(issues),
                })
            st.session_state["research_ht_rows"] = rows
            report = pd.DataFrame(rows)
            st.dataframe(report, hide_index=True, use_container_width=True)
            st.subheader('Historical fair odds for detected halftime matches')
            st.caption('Calculated with the exact same filters as the manual scanner. '
                       'Strike rates are descriptive, not validated predictions. '
                       'Opening odds may differ from the historical pre-match odds definition.')
            for item in rows:
                match_id = item['Match ID']
                estimates = st.session_state.get('auto_estimates', {}).get(match_id)
                if estimates is None:
                    continue
                with st.expander(f"{item['Match']} · {item['Comparable matches']} comparable matches"):
                    with st.expander('Stage 11 · Why this sample size?'):
                        show_stage11_diagnostics(
                            int(item['HT score'].split('-')[0]),
                            int(item['HT score'].split('-')[1]),
                            item['Opening odds'], item['Home HT xG'], item['Away HT xG'],
                            xg_width, odds_width)
                    if item['Comparable matches'] < min_n:
                        st.warning('Insufficient historical sample for the selected minimum.')
                    st.dataframe(estimates, hide_index=True, use_container_width=True)
                    with st.expander('Stage 14 · Compare original vs favourite-side matching'):
                        stage14_show(
                            int(item['HT score'].split('-')[0]),
                            int(item['HT score'].split('-')[1]),
                            item['Opening odds'], item['Home HT xG'], item['Away HT xG'],
                            item['Opening favourite'], xg_width, odds_width)

                    st.download_button('Download 18-market estimates',
                                       estimates.to_csv(index=False).encode(),
                                       f'historical_{match_id}.csv', 'text/csv',
                                       key=f'download_estimates_{match_id}')
            st.download_button("Download halftime results", report.to_csv(index=False).encode(),
                               "halftime_combined.csv", "text/csv")
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        st.error(f"Scan failed: {e}")

st.caption("Opening prices are not verified closing prices. HT xG is accepted only when the live-stats endpoint confirms halftime.")

# One consolidated odds explorer replaces multiple experimental monitors.
st.divider()
st.header("💷 Live Odds Explorer")
st.caption("Inspect bookmaker quotes and candidate market paths for one live match. Quotes may be delayed or suspended.")

# These are tentative mappings. Five markets still have no validated API equivalent.
MARKET_PATHS = {
    "Home full-time win": ("match_odds", "home"),
    "Draw full-time": ("match_odds", "draw"),
    "Away full-time win": ("match_odds", "away"),
    "Home scores in 2H": None,
    "Away scores in 2H": None,
    "Over 0.5 goals 2H": None,
    "Over 1.5 goals 2H": None,
    "Over 2.5 goals 2H": None,
    "Home wins 2H": ("second_half_result", "home"),
    "Draw 2H": ("second_half_result", "draw"),
    "Away wins 2H": ("second_half_result", "away"),
    "BTTS Yes FT": ("btts", "yes"),
    "Over 1.5 goals FT": ("total_goals", "1.5", "over"),
    "Under 1.5 goals FT": ("total_goals", "1.5", "under"),
    "Over 2.5 goals FT": ("total_goals", "2.5", "over"),
    "Under 2.5 goals FT": ("total_goals", "2.5", "under"),
    "Over 3.5 goals FT": ("total_goals", "3.5", "over"),
    "Under 3.5 goals FT": ("total_goals", "3.5", "under"),
}


def walk_quotes(obj, path=()):
    if isinstance(obj, dict):
        if "live" in obj or "available_to_back" in obj:
            yield path, obj
            return
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                yield from walk_quotes(value, path + (str(key),))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from walk_quotes(value, path + (str(i),))


def quote_rows(payload, commission):
    rows = []
    books = (payload.get("data") or {}).get("bookmakers") or []
    for book in books:
        if not isinstance(book, dict):
            continue
        name = str(book.get("bookmaker", "Unknown"))
        exchange = "betfair exchange" in name.lower()
        for path, node in walk_quotes(book.get("markets") or {}):
            if len(path) < 2:
                continue
            price = None
            size = None
            if exchange:
                offers = []
                for offer in node.get("available_to_back") or []:
                    if not isinstance(offer, dict):
                        continue
                    p = positive_odds(offer.get("price"))
                    try:
                        s = float(offer.get("size", 0))
                    except (ValueError, TypeError):
                        s = 0
                    if p is not None and math.isfinite(s) and s > 0:
                        offers.append((p, s))
                if offers:
                    price, size = max(offers)
            else:
                price = positive_odds(node.get("live"))
            effective = (1 + (price - 1) * (1 - commission)) if exchange and price else price
            rows.append({"Bookmaker": name, "Market": path[0],
                         "Selection": "/".join(path[1:]).replace("_", "."), "Odds": price,
                         "Effective odds": effective, "Back size": size,
                         "Exchange": exchange})
    return pd.DataFrame(rows)


if st.button("Find live matches for odds", key="clean_find_odds"):
    try:
        st.session_state["clean_live_matches"] = selected_matches(live_matches())
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        st.error(f"Live match search failed: {e}")

odds_matches = st.session_state.get("clean_live_matches", [])
if odds_matches:
    choices = {f"{match_name(m)} [{m['id']}]": m for m in odds_matches}
    label = st.selectbox("Choose match", list(choices), key="clean_match_select")
    match = choices[label]
    if st.button("Load live bookmaker prices", key="clean_load_odds"):
        try:
            payload = api_get(f"/{match['id']}/odds/live")
            st.session_state["clean_odds_result"] = (str(match['id']), payload)
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            st.error(f"Live odds request failed: {e}")
    saved = st.session_state.get("clean_odds_result")
    if saved and saved[0] == str(match["id"]):
        raw = saved[1]
        st.write("Bookmakers:", ", ".join(bookmaker_names(raw)) or "None")
        all_prices = quote_rows(raw, commission)
        if all_prices.empty:
            st.info("No quote nodes found.")
        else:
            comparison = []
            for market, path in MARKET_PATHS.items():
                if path is None:
                    comparison.append({"Historical market": market, "Status": "Not mapped"})
                    continue
                candidates = all_prices[
                    (all_prices["Market"] == path[0]) &
                    (all_prices["Selection"] == "/".join(path[1:]))
                ].dropna(subset=["Effective odds"])
                if candidates.empty:
                    comparison.append({"Historical market": market, "Status": "No matching quote"})
                else:
                    best = candidates.sort_values("Effective odds", ascending=False).iloc[0]
                    comparison.append({"Historical market": market, "Status": "Candidate — verify",
                                       "Bookmaker": best["Bookmaker"], "Back odds": best["Odds"],
                                       "Effective odds": best["Effective odds"],
                                       "Back size": best["Back size"]})
            st.subheader("18-market candidate comparison")
            st.dataframe(pd.DataFrame(comparison), hide_index=True, use_container_width=True)
            with st.expander("All bookmaker selection paths"):
                st.dataframe(all_prices.drop(columns=["Exchange"]), hide_index=True, use_container_width=True)
            with st.expander("Raw live odds response"):
                st.json(raw)
            st.warning("These mappings are provisional; confirm market settlement and price freshness. Exchange commission applies to net winnings, and quoted liquidity may be unavailable.")
else:
    st.info("Press 'Find live matches for odds' when games are underway.")


# Research-only comparison, built from the SAME halftime snapshot used above.
# No additional live requests and no claim that a quote remains executable.
st.divider()
st.header("📊 Halftime Value Research — provisional")
st.caption("Matches from the most recent complete halftime scan only. Historical strike rates are not calibrated predictions. "
           "Quotes may be stale, suspended, or unavailable; these are NOT betting signals.")

research_rows = []
research_missing = []
for item in st.session_state.get("research_ht_rows", []):
    mid = item["Match ID"]
    estimates = st.session_state.get("auto_estimates", {}).get(mid)
    payload = st.session_state.get("research_live_quotes", {}).get(mid)
    if estimates is None or payload is None:
        research_missing.append(f"{item['Match']}: missing historical estimates or live prices")
        continue
    quotes = quote_rows(payload, commission)
    if quotes.empty:
        research_missing.append(f"{item['Match']}: no usable quote records")
        continue
    for _, est in estimates.iterrows():
        market = est["Market"]
        path = MARKET_PATHS.get(market)
        if path is None:
            continue
        candidates = quotes.loc[
            (quotes["Market"] == path[0]) &
            (quotes["Selection"] == "/".join(path[1:]))
        ].dropna(subset=["Effective odds"])
        if candidates.empty:
            continue
        best = candidates.sort_values("Effective odds", ascending=False).iloc[0]
        n = int(est["Matches"])
        wins = int(est["Wins"])
        prob = wins / n if n else None
        effective = float(best["Effective odds"])
        estimated_roi = (100 * (prob * effective - 1)) if prob is not None else None
        lower_roi = (100 * (wilson_lower(wins, n) * effective - 1)) if n else None
        research_rows.append({
            "Match ID": mid, "Match": item["Match"], "HT score": item["HT score"],
            "Market": market, "Bookmaker": best["Bookmaker"],
            "Quoted odds": round(float(best["Odds"]), 3),
            "After commission": round(effective, 3),
            "Fair odds (historical)": est["Fair odds"],
            "Historical win %": est["Strike rate"],
            "Comparable matches": n,
            "Estimated ROI %": round(estimated_roi, 1) if estimated_roi is not None else None,
            "Wilson lower ROI %": round(lower_roi, 1) if lower_roi is not None else None,
            "Sample sufficient": n >= min_n,
            "Mapping": "Provisional — verify settlement",
            "Price status": "Unverified / may be delayed",
        })

if research_rows:
    research = pd.DataFrame(research_rows)
    research = research.sort_values("Estimated ROI %", ascending=False, na_position="last")
    st.warning("RESEARCH ONLY: Every displayed mapping and price remains unverified. "
               "A positive estimated ROI is NOT evidence of a genuine edge. "
               "Opening favourite prices may not match historical closing-price definitions.")
    st.dataframe(research, hide_index=True, use_container_width=True)
    st.download_button("Download research comparison CSV", research.to_csv(index=False).encode(),
                       "halftime_value_research.csv", "text/csv", key="download_research_comparison")
    st.caption("Missing markets are omitted, not assigned invented prices. The five unmapped markets remain in historical research.")
else:
    st.info("No comparable halftime price research yet. Run the Complete Halftime Scan when matches are at halftime "
            "and both teams' xG is available.")
if research_missing:
    with st.expander("Why some halftime matches are missing"):
        for reason in research_missing:
            st.write(reason)


# STAGE 10 — SCAN-TRIGGERED OPPORTUNITY LOG AND HUMAN DECISION SHORTLIST
# No additional API requests. Snapshot only the results of a fresh, completed scan.
st.divider()
st.header("📋 Stage 10 · Opportunity tracker and shortlist")
st.caption("Automatically captures provisional priced research candidates when you run a complete scan. "
           "No unattended monitoring, no live bet placement, no automatic price verification or settlement. "
           "Records remain in Streamlit session memory until exported.")
TRACK_COLUMNS = ["Opportunity ID", "Scan UTC", "Match ID", "Match", "HT score", "Market",
                 "Bookmaker", "Quoted odds", "After commission", "Historical win %",
                 "Comparable matches", "Estimated ROI %", "Wilson lower ROI %",
                 "Sample sufficient", "Price status", "Mapping", "Decision", "Decision UTC", "Notes"]
if "stage10_opportunities" not in st.session_state:
    st.session_state["stage10_opportunities"] = []
if "stage10_last_logged_token" not in st.session_state:
    st.session_state["stage10_last_logged_token"] = ""

def stage10_id(row, scan_token):
    # Stable within a scan; never merge distinct scans just because prices coincide.
    import hashlib
    key = "|".join(str(row.get(k, "")) for k in
                   ("Match ID", "Market", "Bookmaker", "Quoted odds"))
    return hashlib.sha256((scan_token + "|" + key).encode("utf-8")).hexdigest()[:20]

scan_token = st.session_state.get("stage10_scan_token", "")
if scan_token and scan_token != st.session_state["stage10_last_logged_token"]:
    # Even a zero-opportunity scan is marked complete, preventing accidental duplicates.
    captured = 0
    for row in research_rows:
        if not row.get("Sample sufficient"):
            continue
        if pd.isna(row.get("Quoted odds")) or pd.isna(row.get("Estimated ROI %")):
            continue
        if float(row["Quoted odds"]) <= 1:
            continue
        # Keep all priced, sample-sufficient mapped markets, not only apparent winners.
        item = {key: row.get(key, "") for key in TRACK_COLUMNS}
        item.update({"Opportunity ID": stage10_id(row, scan_token),
                     "Scan UTC": scan_token, "Decision": "Unreviewed",
                     "Decision UTC": "", "Notes": "Unverified API quote; research only"})
        st.session_state["stage10_opportunities"].append(item)
        captured += 1
    st.session_state["stage10_last_logged_token"] = scan_token
    st.info(f"Stage 10 logged {captured} priced, sample-sufficient observations from this scan. "
            "These are not verified or executable betting opportunities.")

with st.expander("Import an earlier Stage 10 opportunity CSV (optional)"):
    stage10_upload = st.file_uploader("Stage 10 CSV", type="csv", key="stage10_import_file")
    if stage10_upload is not None and st.button("Import opportunity records", key="stage10_import_button"):
        try:
            incoming = pd.read_csv(stage10_upload, dtype=str, keep_default_na=False)
            if not {"Opportunity ID", "Match", "Market", "Decision"}.issubset(incoming.columns):
                st.error("This is not a Stage 10 opportunity CSV.")
            else:
                current = pd.DataFrame(st.session_state["stage10_opportunities"], columns=TRACK_COLUMNS)
                for column in TRACK_COLUMNS:
                    if column not in incoming:
                        incoming[column] = ""
                merged = pd.concat([current, incoming[TRACK_COLUMNS]], ignore_index=True)
                merged = merged.drop_duplicates(subset=["Opportunity ID"], keep="first")
                st.session_state["stage10_opportunities"] = merged.fillna("").to_dict("records")
                st.success(f"Imported. {len(merged)} unique records now available in this session.")
        except (ValueError, TypeError, UnicodeError) as error:
            st.error(f"Could not import the CSV: {error}")

opportunities = st.session_state["stage10_opportunities"]
if opportunities:
    tracked = pd.DataFrame(opportunities)
    for numeric_column in ("Quoted odds", "Estimated ROI %", "Wilson lower ROI %", "Comparable matches"):
        tracked[numeric_column] = pd.to_numeric(tracked[numeric_column], errors="coerce")
    st.caption("The shortlist is ranked by historical estimated ROI, which may be unreliable. "
               "Missing or delayed odds, thin liquidity and unverified market mapping can invalidate the apparent edge.")
    st.metric("Logged observations (including passes)", len(tracked))
    min_edge = st.number_input("Minimum displayed historical estimated ROI (%)", min_value=-100.0,
                               max_value=1000.0, value=0.0, step=1.0, key="stage10_min_edge")
    only_latest = st.checkbox("Show latest scan only", value=True, key="stage10_latest_only")
    shortlist = tracked.copy()
    if only_latest:
        shortlist = shortlist[shortlist["Scan UTC"] == shortlist["Scan UTC"].max()]
    shortlist = shortlist[shortlist["Estimated ROI %"] >= min_edge]
    shortlist = shortlist.sort_values("Estimated ROI %", ascending=False)
    st.subheader("Ranked research shortlist")
    if shortlist.empty:
        st.info("No logged observations meet this display threshold. Try lowering the threshold.")
    else:
        st.dataframe(shortlist[["Match", "HT score", "Market", "Bookmaker", "Quoted odds",
                                "Historical win %", "Comparable matches", "Estimated ROI %",
                                "Wilson lower ROI %", "Price status", "Decision"]],
                     hide_index=True, use_container_width=True)
    st.subheader("Your decision — never automatic")
    choices = {f"{i+1}. {r['Match']} · {r['Market']} @ {r['Quoted odds']} [{r['Decision']}]": i
               for i, r in enumerate(opportunities)}
    with st.form("stage10_decision_form"):
        chosen_label = st.selectbox("Choose a recorded observation", list(choices), key="stage10_chosen")
        decision = st.selectbox("Decision", ["Watching", "Selected", "Passed", "Unreviewed"],
                                key="stage10_decision")
        decision_note = st.text_input("Optional note (e.g. price too short, insufficient liquidity)",
                                      key="stage10_decision_note")
        decision_submit = st.form_submit_button("Save my decision")
    if decision_submit:
        record = opportunities[choices[chosen_label]]
        record["Decision"] = decision
        record["Decision UTC"] = datetime.now(timezone.utc).isoformat()
        if decision_note.strip():
            record["Notes"] = (str(record.get("Notes") or "") + " | " + decision_note.strip()).strip(" |")
        st.success("Decision saved in this session. Export the updated CSV to keep it.")
    decisions = pd.DataFrame(opportunities)["Decision"].value_counts()
    st.caption("Decision totals: " + ", ".join(f"{k}: {v}" for k, v in decisions.items()))
    export = pd.DataFrame(opportunities, columns=TRACK_COLUMNS)
    st.download_button("⬇️ Download Stage 10 opportunity log CSV",
                       export.to_csv(index=False).encode("utf-8-sig"),
                       "football_stage10_opportunities.csv", "text/csv", key="stage10_download")
    st.caption("Stage 10 decisions are separate from the Stage 9 paper journal. "
               "'Selected' means your research decision, not that a real bet was placed. "
               "Re-running a scan creates a new observation snapshot; exported records can be reimported later.")
else:
    st.info("No priced observations logged yet. Run a complete halftime scan when fixtures are at halftime "
            "and the API supplies xG and supported market prices. No test prices are invented.")


# STAGE 9 — PAPER-TRADE RESEARCH JOURNAL
# User-controlled, no automatic bets or unverified result settlement.
st.divider()
st.header("📝 Stage 9 · Halftime price and outcome journal")
st.caption("Paper research only. Record the actual halftime price you observed, then settle the selection after full time. "
           "Nothing is submitted to a bookmaker. Download your CSV regularly: Streamlit session memory is temporary.")
JOURNAL_COLUMNS = ["Recorded UTC", "Match ID", "Match", "HT score", "Market", "Source",
                   "Observed odds", "Commission %", "Effective odds", "Model probability %",
                   "Comparable matches", "Estimated EV %", "Observed price time UTC", "Price verified",
                   "Available stake GBP", "Status", "Outcome", "Net units", "Notes"]
if "paper_journal" not in st.session_state:
    st.session_state["paper_journal"] = []

with st.expander("Import an earlier journal CSV (optional)"):
    uploaded_journal = st.file_uploader("Choose a previous Stage 9 journal CSV", type=["csv"], key="stage9_import")
    if uploaded_journal is not None and st.button("Import journal (merge without duplicates)", key="stage9_import_button"):
        try:
            incoming = pd.read_csv(uploaded_journal).fillna("")
            if not {"Match", "Market", "Observed odds", "Status"}.issubset(incoming.columns):
                st.error("This CSV does not contain the expected journal columns.")
            else:
                old = pd.DataFrame(st.session_state["paper_journal"])
                merged = pd.concat([old, incoming], ignore_index=True)
                for c in JOURNAL_COLUMNS:
                    if c not in merged.columns:
                        merged[c] = ""
                merged = merged[JOURNAL_COLUMNS].drop_duplicates().fillna("")
                st.session_state["paper_journal"] = merged.to_dict("records")
                st.success(f"Journal now contains {len(merged)} records.")
        except Exception as exc:
            st.error(f"Couldn't import journal: {exc}")

st.markdown("**Record a halftime quote**")
# Research comparison is built above. Manual entry works when the API has no mapped quote.
research_options = ["Manual entry"]
if research_rows:
    research_options += [f"{i+1}: {r['Match']} · {r['Market']}" for i, r in enumerate(research_rows)]
selected_research = st.selectbox("Prefill from latest scan (optional)", research_options, key="stage9_prefill")
prefill = research_rows[int(selected_research.split(":", 1)[0]) - 1] if selected_research != "Manual entry" else None
with st.form("stage9_record_form"):
    a, b = st.columns(2)
    match_text = a.text_input("Fixture", value=prefill["Match"] if prefill else "")
    ht_text = b.text_input("Halftime score", value=prefill["HT score"] if prefill else "")
    market_text = st.selectbox("Market", list(market_outcomes(HISTORY.iloc[:1]).keys()),
        index=list(market_outcomes(HISTORY.iloc[:1]).keys()).index(prefill["Market"]) if prefill else 0)
    c, e = st.columns(2)
    odds_value = c.number_input("Observed back odds (decimal)", min_value=1.01, max_value=1000.0,
                                value=float(prefill["Quoted odds"]) if prefill else 2.0, step=0.05)
    source_value = e.text_input("Bookmaker / exchange", value=prefill["Bookmaker"] if prefill else "")
    c2, e2 = st.columns(2)
    price_time = c2.text_input("Time you actually saw the quote (UTC)", placeholder="2026-10-29 15:45")
    available_stake = e2.number_input("Available back liquidity / stake (£), if known", min_value=0.0, value=0.0, step=1.0)
    confirmed_price = st.checkbox("I personally checked this price was available at the recorded time")
    model_p = st.number_input("Model probability (%) — enter only if available", min_value=0.0, max_value=100.0,
        value=float(prefill["Historical win %"]) if prefill and pd.notna(prefill["Historical win %"]) else 0.0, step=0.1)
    comparable_n = st.number_input("Comparable historical matches", min_value=0, value=int(prefill["Comparable matches"]) if prefill else 0)
    note = st.text_input("Notes (e.g. suspended, delayed, unverified market mapping)")
    add_record = st.form_submit_button("Add to paper journal")
if add_record:
    if not match_text.strip() or not source_value.strip():
        st.error("Please enter a fixture and price source.")
    else:
        effective = 1 + (odds_value - 1) * (1 - commission)
        ev = 100 * (model_p / 100 * effective - 1) if model_p > 0 else ""
        st.session_state["paper_journal"].append({
            "Recorded UTC": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "Match ID": "", "Match": match_text.strip(), "HT score": ht_text.strip(),
            "Market": market_text, "Source": source_value.strip(), "Observed odds": odds_value,
            "Commission %": round(commission * 100, 2), "Effective odds": round(effective, 4),
            "Model probability %": model_p if model_p > 0 else "", "Comparable matches": comparable_n,
            "Estimated EV %": round(ev, 2) if ev != "" else "", "Observed price time UTC": price_time.strip(),
            "Price verified": bool(confirmed_price), "Available stake GBP": available_stake if available_stake else "",
            "Status": "Pending", "Outcome": "", "Net units": "", "Notes": note.strip()})
        st.success("Paper observation added. Download the CSV to keep it safe.")

journal_df = pd.DataFrame(st.session_state["paper_journal"], columns=JOURNAL_COLUMNS)
if not journal_df.empty:
    st.dataframe(journal_df, use_container_width=True, hide_index=True)
    st.download_button("⬇️ Download paper journal CSV", journal_df.to_csv(index=False).encode("utf-8-sig"),
                       "football_halftime_paper_journal.csv", "text/csv", key="stage9_download")
    pending_indices = [i for i, r in enumerate(st.session_state["paper_journal"]) if r.get("Status") == "Pending"]
    if pending_indices:
        st.markdown("**Settle a paper observation after full time**")
        with st.form("stage9_settlement_form"):
            index = st.selectbox("Pending observation", pending_indices,
                format_func=lambda i: f"#{i+1} · {st.session_state['paper_journal'][i]['Match']} · {st.session_state['paper_journal'][i]['Market']}")
            outcome = st.selectbox("Verified market outcome", ["Won", "Lost", "Void"])
            settle_note = st.text_input("Result source / settlement note")
            settle = st.form_submit_button("Save paper settlement")
        if settle:
            rec = st.session_state["paper_journal"][index]
            raw_price = float(rec["Observed odds"])
            fee = float(rec["Commission %"]) / 100
            rec["Status"] = "Settled"
            rec["Outcome"] = outcome
            rec["Net units"] = round((raw_price - 1) * (1 - fee), 4) if outcome == "Won" else (-1 if outcome == "Lost" else 0)
            rec["Notes"] = (str(rec.get("Notes") or "") + " | " + settle_note).strip(" |")
            st.success("Outcome recorded. Download the updated journal CSV.")
    settled = [r for r in st.session_state["paper_journal"] if r.get("Status") == "Settled" and r.get("Outcome") in ("Won", "Lost")]
    if settled:
        net = sum(float(r["Net units"]) for r in settled)
        st.metric("Paper return per 1-unit observation (not actual betting profit)", f"{net / len(settled) * 100:+.1f}%", f"{len(settled)} settled observations")
        st.caption("This is descriptive only: self-selected observations, missing prices, stale quotes and unverified settlement can bias results. "
                   "It is not a validated strategy ROI. One unit is assumed per recorded observation.")
else:
    st.info("No paper observations recorded yet. The form works even without live matches.")
st.caption("Stage 9 stores observations in your current browser/server session only. Export after adding or settling records; "
           "import the CSV next time. There is no background monitoring or automatic result fetching.")


# Stage 19B — halftime goal-distribution research model.
# Independent calculation METHOD, not independent data: both use HISTORY.
# Model is research-only; no changes to the automatic worker or Stage 18 journal.
st.subheader('Stage 19B · Halftime goal-distribution model (research)')
st.caption('A second way to estimate second-half outcomes, alongside historical matching. '
           'This is a smoothed Poisson approximation fitted to past second-half goal counts, '
           'NOT a validated betting signal. No bets are placed.')

import numpy as np

@st.cache_data(show_spinner=False)
def _goal19_pool():
    pool = HISTORY.copy()
    pool['g2h'] = pool['FTHG'] - pool['HTHG']
    pool['g2a'] = pool['FTAG'] - pool['HTAG']
    pool = pool[(pool['g2h'].between(0, 12)) & (pool['g2a'].between(0, 12))
                & (pool['fav'].between(1.01, 20))].copy()
    return pool


def _poisson19(lam, max_goals=12):
    values = np.arange(max_goals + 1)
    probs = np.empty(max_goals + 1, dtype=float)
    probs[0] = math.exp(-lam)
    for k in range(1, max_goals + 1):
        probs[k] = probs[k-1] * lam / k
    probs[-1] += max(0., 1. - probs.sum())  # upper-tail approximation
    return probs


def _goal19_estimate(train, ht_home, ht_away, favourite_odds, home_xg, away_xg):
    # Soft neighbour weighting: do not discard nearly all matches with hard bands.
    if len(train) < 100:
        return None
    weights = np.exp(-0.5 * (
        ((train['HTHG'].to_numpy(float) - ht_home) / 1.20)**2 +
        ((train['HTAG'].to_numpy(float) - ht_away) / 1.20)**2 +
        ((train['fav'].to_numpy(float) - favourite_odds) / 0.85)**2 +
        ((train[xg1].to_numpy(float) - home_xg) / 0.75)**2 +
        ((train[xg2].to_numpy(float) - away_xg) / 0.75)**2
    ))
    sw = float(weights.sum())
    if sw < 1e-6:
        return None
    neff = sw * sw / max(float(np.square(weights).sum()), 1e-12)
    # Shrink to broad training population, reducing instability in sparse scenarios.
    prior = 60.
    hmean = (float(np.dot(weights, train['g2h'].to_numpy(float))) +
             prior * float(train['g2h'].mean())) / (sw + prior)
    amean = (float(np.dot(weights, train['g2a'].to_numpy(float))) +
             prior * float(train['g2a'].mean())) / (sw + prior)
    return max(0.05, hmean), max(0.05, amean), neff, sw


def _goal19_probs(lh, la, halftime_home, halftime_away):
    homep, awayp = _poisson19(lh), _poisson19(la)
    joint = np.outer(homep, awayp)
    h2, a2 = np.indices(joint.shape)
    total = h2 + a2
    final_margin = halftime_home + h2 - halftime_away - a2
    return {
        'Home scores in 2H': float(joint[h2 >= 1].sum()),
        'Away scores in 2H': float(joint[a2 >= 1].sum()),
        'Home wins 2H': float(joint[h2 > a2].sum()),
        'Draw 2H': float(joint[h2 == a2].sum()),
        'Away wins 2H': float(joint[h2 < a2].sum()),
        'Over 0.5 goals 2H': float(joint[total >= 1].sum()),
        'Over 1.5 goals 2H': float(joint[total >= 2].sum()),
        'Over 2.5 goals 2H': float(joint[total >= 3].sum()),
        'Home full-time win': float(joint[final_margin > 0].sum()),
        'Draw full-time': float(joint[final_margin == 0].sum()),
        'Away full-time win': float(joint[final_margin < 0].sum()),
    }

_gpool19 = _goal19_pool()
if len(_gpool19) < 100:
    st.info('Not enough historical matches with complete halftime xG and results to fit the goal model.')
else:
    # Keep the most recent 20% out of the training pool for honest chronological checks.
    _dated19 = _gpool19.copy()
    _dated19['_date19'] = pd.to_datetime(_dated19['date'] if 'date' in _dated19
                                          else _dated19['Date'], errors='coerce', dayfirst=True)
    _dated19 = _dated19.dropna(subset=['_date19']).sort_values('_date19')
    if len(_dated19) < 200:
        st.warning('Insufficient dated history for chronological separation; model withheld.')
    else:
        _split19 = int(len(_dated19) * 0.8)
        _train19 = _dated19.iloc[:_split19]
        _test19 = _dated19.iloc[_split19:]
        _fit19 = _goal19_estimate(_train19, ht_h, ht_a, fav, xgh, xga)
        if _fit19 is None:
            st.info('No sufficiently comparable training data for these halftime inputs.')
        else:
            _lh19, _la19, _neff19, _sw19 = _fit19
            _prob19 = _goal19_probs(_lh19, _la19, ht_h, ht_a)
            _m1, _m2, _m3 = st.columns(3)
            _m1.metric('Expected home 2H goals', f'{_lh19:.2f}')
            _m2.metric('Expected away 2H goals', f'{_la19:.2f}')
            _m3.metric('Effective neighbours', f'{_neff19:.0f}')
            _comparison19 = comparable_matches(ht_h, ht_a, fav, xgh, xga, xg_width, odds_width)
            _outcomes19 = market_outcomes(_comparison19)
            _rows19 = []
            for _market19, _p19 in _prob19.items():
                _hist19 = (float(_outcomes19[_market19].mean())
                           if len(_comparison19) and _market19 in _outcomes19 else None)
                _rows19.append({
                    'Market': _market19,
                    'Goal-model probability %': round(100*_p19, 1),
                    'Goal-model fair odds': round(1/_p19, 2) if _p19 > 0 else None,
                    'Historical matching %': round(100*_hist19, 1) if _hist19 is not None else None,
                    'Difference (percentage points)': (round(100*(_p19-_hist19), 1)
                                                      if _hist19 is not None else None),
                })
            st.dataframe(pd.DataFrame(_rows19), hide_index=True, use_container_width=True)
            st.caption(f'Goal-model training: {len(_train19):,} older matches. '
                       f'Chronological holdout reserved: {len(_test19):,} later matches. '
                       f'Historical matching sample: {len(_comparison19):,}. '
                       'Both methods rely on overlapping historical data. '
                       'Fair odds exclude bookmaker margin and commission.')
            st.warning('This first goal model assumes independent Poisson second-half goal counts '
                       'and uses a fixed shrinkage rule. Reserving a holdout does NOT mean that '
                       'holdout accuracy or profitability has been verified. Do not interpret '
                       'differences or model agreement as a proven betting edge.')


# Stage 19C — genuine chronological holdout validation of both halftime models.
st.subheader('Stage 19C · Dual-model historical accuracy test')
st.caption('Compares predictions for the SAME later matches, using only earlier training matches. '
           'This measures predictive accuracy, not betting profit or an executable strategy.')

@st.cache_data(show_spinner='Testing both halftime models on unseen historical matches…')
def _validate19c(max_tests=500):
    pool = _goal19_pool().copy()
    pool['_date19c'] = pd.to_datetime(pool['date'] if 'date' in pool else pool['Date'],
                                     errors='coerce', dayfirst=True)
    pool = pool.dropna(subset=['_date19c']).sort_values('_date19c')
    if len(pool) < 1000:
        return None, 'Insufficient dated matches for chronological validation.'
    split = int(len(pool) * 0.8)
    cutoff = pool['_date19c'].iloc[split]
    train = pool[pool['_date19c'] < cutoff].copy()
    test = pool[pool['_date19c'] >= cutoff].copy()
    if len(train) < 500 or len(test) < 100:
        return None, 'Insufficient training/test data after excluding same-date overlap.'
    if len(test) > max_tests:
        test = test.iloc[np.linspace(0, len(test)-1, max_tests, dtype=int)].copy()
    features = ['HTHG','HTAG','fav',xg1,xg2]
    tr = train[features].to_numpy(float)
    te = test[features].to_numpy(float)
    tr_y = {k: np.asarray(v, dtype=float) for k,v in market_outcomes(train).items()}
    te_y = {k: np.asarray(v, dtype=float) for k,v in market_outcomes(test).items()}
    keys = list(_goal19_probs(1.,1.,0,0).keys())
    sums = {k:{'goal_sq':0.,'hist_sq':0.,'goal_abs':0.,'hist_abs':0.,
               'goal_sum':0.,'hist_sum':0.,'actual_sum':0.,'n':0} for k in keys}
    all_count = 0
    matched_count = 0
    for i, row in enumerate(te):
        h,a,fo,hx,ax = row
        fit = _goal19_estimate(train, int(h), int(a), fo, hx, ax)
        if fit is None: continue
        all_count += 1
        mask = ((tr[:,0] == h) & (tr[:,1] == a) &
                (np.abs(tr[:,2]-fo) <= 0.35) &
                (np.abs(tr[:,3]-hx) <= 0.40) &
                (np.abs(tr[:,4]-ax) <= 0.40))
        n = int(mask.sum())
        if n < 30: continue
        matched_count += 1
        gp = _goal19_probs(fit[0], fit[1], int(h), int(a))
        for k in keys:
            ph = (tr_y[k][mask].sum() + 1.)/(n+2.)
            pg = gp[k]
            y = te_y[k][i]
            z=sums[k]
            z['goal_sq'] += (pg-y)**2
            z['hist_sq'] += (ph-y)**2
            z['goal_abs'] += abs(pg-y)
            z['hist_abs'] += abs(ph-y)
            z['goal_sum'] += pg
            z['hist_sum'] += ph
            z['actual_sum'] += y
            z['n'] += 1
    rows=[]
    for k,z in sums.items():
        n=z['n']
        if not n:continue
        rows.append({'Market':k,'Test matches':n,
                     'Goal model Brier':round(z['goal_sq']/n,4),
                     'Historical Brier':round(z['hist_sq']/n,4),
                     'Better Brier': 'Goal model' if z['goal_sq'] < z['hist_sq'] else ('Historical' if z['hist_sq'] < z['goal_sq'] else 'Tie'),
                     'Goal forecast %':round(z['goal_sum']/n*100,1),
                     'Historical forecast %':round(z['hist_sum']/n*100,1),
                     'Actual %':round(z['actual_sum']/n*100,1)})
    return {'rows':rows,'train':len(train),'holdout':len(test),
            'goal_covered':all_count,'both_covered':matched_count,
            'cutoff':str(cutoff.date())}, None

with st.expander('Run Stage 19C holdout test', expanded=False):
    st.caption('Fixed, predeclared comparison: xG ±0.40, favourite odds ±0.35, exact HT score, '
               'minimum 30 historical neighbours; Laplace-smoothed historical estimates. '
               'Up to 500 evenly spaced later matches are tested. No test outcomes enter either model.')
    if st.button('Run historical dual-model comparison', key='run19c'):
        result19c, error19c = _validate19c()
        if error19c:
            st.warning(error19c)
        else:
            st.write(f"Training matches: {result19c['train']:,} | Later holdout sampled: {result19c['holdout']:,} "
                     f"| Both models comparable: {result19c['both_covered']:,} "
                     f"| Holdout begins: {result19c['cutoff']}")
            st.dataframe(pd.DataFrame(result19c['rows']), use_container_width=True, hide_index=True)
            st.download_button('Download Stage 19C accuracy CSV',
                data=pd.DataFrame(result19c['rows']).to_csv(index=False).encode('utf-8-sig'),
                file_name='stage19c_holdout_accuracy.csv', mime='text/csv')
            st.caption('Lower Brier is better. Historical method has limited coverage because of exact '
                       'matching. These are paired comparisons ONLY where both methods have enough '
                       'data. This test does not establish value, closing-line advantage or ROI. '
                       'A future independent time period is needed before selecting a winning method.')


# Stage 19D — weights selected on an earlier validation period, tested on a later holdout.
st.subheader('Stage 19D · Three-way halftime model comparison')
st.caption('Historical vs goal-distribution vs validation-selected blend. '
           'Only halftime inputs; no bet recommendations or assumed executable prices.')

@st.cache_data(show_spinner='Validating blend weights and testing later matches…')
def _validate19d(max_validation=350, max_holdout=350):
    pool = _goal19_pool().copy()
    pool['_date19d'] = pd.to_datetime(pool['date'] if 'date' in pool else pool['Date'],
                                     errors='coerce', dayfirst=True)
    pool = pool.dropna(subset=['_date19d']).sort_values('_date19d')
    if len(pool) < 1200:
        return None, 'Not enough dated history for three chronological periods.'
    first = pool['_date19d'].iloc[int(len(pool)*0.6)]
    second = pool['_date19d'].iloc[int(len(pool)*0.8)]
    train = pool[pool['_date19d'] < first].copy()
    validation = pool[(pool['_date19d'] >= first) & (pool['_date19d'] < second)].copy()
    holdout = pool[pool['_date19d'] >= second].copy()
    if min(len(train),len(validation),len(holdout)) < 100:
        return None, 'Insufficient matches after separating dates.'
    def sample(frame, cap):
        if len(frame) <= cap: return frame
        return frame.iloc[np.linspace(0,len(frame)-1,cap,dtype=int)].copy()
    validation = sample(validation,max_validation)
    holdout = sample(holdout,max_holdout)
    keys = list(_goal19_probs(1.,1.,0,0).keys())
    tr = train[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
    tr_y = {k: np.asarray(v,dtype=float) for k,v in market_outcomes(train).items()}
    def predict(frame):
        feats = frame[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
        outcomes = {k:np.asarray(v,dtype=float) for k,v in market_outcomes(frame).items()}
        out={k:{'hist':[],'goal':[],'actual':[]} for k in keys}
        for i,(h,a,fo,hx,ax) in enumerate(feats):
            fit=_goal19_estimate(train,int(h),int(a),fo,hx,ax)
            if fit is None: continue
            mask=((tr[:,0]==h)&(tr[:,1]==a)&
                  (np.abs(tr[:,2]-fo)<=0.35)&
                  (np.abs(tr[:,3]-hx)<=0.40)&
                  (np.abs(tr[:,4]-ax)<=0.40))
            n=int(mask.sum())
            if n<30: continue
            gp=_goal19_probs(fit[0],fit[1],int(h),int(a))
            for k in keys:
                out[k]['hist'].append((tr_y[k][mask].sum()+1.)/(n+2.))
                out[k]['goal'].append(gp[k])
                out[k]['actual'].append(outcomes[k][i])
        return out
    val=predict(validation)
    test=predict(holdout)
    grid=[0.,0.25,0.5,0.75,1.]
    rows=[]
    for k in keys:
        v=val[k]; t=test[k]
        if len(v['actual'])<30 or len(t['actual'])<30: continue
        vh=np.asarray(v['hist']);vg=np.asarray(v['goal']);vy=np.asarray(v['actual'])
        # The validation period ALONE selects the weight; no holdout outcomes enter selection.
        scores=[np.mean(((1-w)*vh+w*vg-vy)**2) for w in grid]
        w=grid[int(np.argmin(scores))]
        th=np.asarray(t['hist']);tg=np.asarray(t['goal']);ty=np.asarray(t['actual'])
        blend=(1-w)*th+w*tg
        rows.append({'Market':k,'Validation matches':len(vy),'Holdout matches':len(ty),
                     'Goal weight %':round(100*w),
                     'Historical Brier':round(float(np.mean((th-ty)**2)),4),
                     'Goal Brier':round(float(np.mean((tg-ty)**2)),4),
                     'Blend Brier':round(float(np.mean((blend-ty)**2)),4),
                     'Best on holdout':min({'Historical':np.mean((th-ty)**2),
                                           'Goal':np.mean((tg-ty)**2),
                                           'Blend':np.mean((blend-ty)**2)},
                                          key={'Historical':np.mean((th-ty)**2),
                                               'Goal':np.mean((tg-ty)**2),
                                               'Blend':np.mean((blend-ty)**2)}.get),
                     'Actual %':round(float(np.mean(ty)*100),1)})
    return {'rows':rows,'train':len(train),'validation':len(validation),
            'holdout':len(holdout),'validation_start':str(first.date()),
            'holdout_start':str(second.date())},None

with st.expander('Run Stage 19D three-way chronological test',expanded=False):
    st.caption('First 60% train, next 20% select blend weights, final 20% test. '
               'Dates at split boundaries stay together. Both models use the SAME training data; '
               'only matches with at least 30 exact-score historical neighbours qualify. '
               'Goal weight 0% means historical-only; 100% means goal-only.')
    if st.button('Run three-way halftime model test',key='run19d'):
        result19d,error19d=_validate19d()
        if error19d:
            st.warning(error19d)
        else:
            st.write(f"Training: {result19d['train']:,} | Validation sampled: {result19d['validation']:,} "
                     f"| Final holdout sampled: {result19d['holdout']:,} "
                     f"| Holdout begins: {result19d['holdout_start']}")
            df19d=pd.DataFrame(result19d['rows'])
            if len(df19d):
                st.dataframe(df19d,hide_index=True,use_container_width=True)
                st.download_button('Download Stage 19D comparison CSV',
                    data=df19d.to_csv(index=False).encode('utf-8-sig'),
                    file_name='stage19d_three_way_holdout.csv',mime='text/csv')
            else:
                st.warning('Too few paired predictions in validation or holdout.')
            st.caption('Lower Brier is better. Weights were chosen on validation data, not the '
                       'final holdout. Results are exploratory, subject to sample noise, and '
                       'do not prove profitability. Do not pick new weights from holdout results.')


# Stage 19E — expanding-window rolling evaluation (research only).
st.subheader('Stage 19E · Rolling halftime model validation')
st.caption('Four forward-only chronological tests. Each fold trains on older games, '
           'chooses a blend weight on the following period, and scores on the next period. '
           'This does not change live predictions, Stage 17, or Stage 18.')

@st.cache_data(show_spinner='Running forward-only historical folds…')
def _validate19e(max_per_period=100):
    pool = _goal19_pool().copy()
    pool['_rolling_date'] = pd.to_datetime(pool['date'] if 'date' in pool else pool['Date'],
                                           errors='coerce', dayfirst=True)
    pool = pool.dropna(subset=['_rolling_date']).sort_values('_rolling_date')
    if len(pool) < 1500:
        return None, 'Not enough dated halftime history for rolling validation.'
    # Boundaries at distinct calendar days: no same-day match crosses a split.
    dates = np.sort(pool['_rolling_date'].dt.normalize().unique())
    if len(dates) < 100:
        return None, 'Not enough distinct match dates.'
    # Fold 1: train 0-50%, validate 50-60%, test 60-70%; slide by 10%.
    boundaries = [dates[min(int(len(dates)*q),len(dates)-1)] for q in
                  [0.50,0.60,0.70,0.80,0.90,0.999999]]
    keys = list(_goal19_probs(1.,1.,0,0).keys())
    grid = [0.,0.25,0.5,0.75,1.]
    allrows=[]
    summary=[]
    calibration_rows=[]
    def cap(frame):
        if len(frame)<=max_per_period:return frame
        return frame.iloc[np.linspace(0,len(frame)-1,max_per_period,dtype=int)].copy()
    for fold in range(4):
        start_v,end_v,end_t=boundaries[fold:fold+3]
        train=pool[pool['_rolling_date']<start_v].copy()
        validation=cap(pool[(pool['_rolling_date']>=start_v)&(pool['_rolling_date']<end_v)])
        test=cap(pool[(pool['_rolling_date']>=end_v)&(pool['_rolling_date']<end_t)])
        if min(len(train),len(validation),len(test))<40:continue
        tr=train[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
        tr_y={k:np.asarray(v,dtype=float) for k,v in market_outcomes(train).items()}
        def predict(frame):
            feats=frame[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
            outcomes={k:np.asarray(v,dtype=float) for k,v in market_outcomes(frame).items()}
            result={k:{'h':[],'g':[],'y':[]} for k in keys}
            for i,(h,a,fo,hx,ax) in enumerate(feats):
                fit=_goal19_estimate(train,int(h),int(a),fo,hx,ax)
                if fit is None:continue
                mask=((tr[:,0]==h)&(tr[:,1]==a)&
                      (np.abs(tr[:,2]-fo)<=0.35)&
                      (np.abs(tr[:,3]-hx)<=0.40)&
                      (np.abs(tr[:,4]-ax)<=0.40))
                n=int(mask.sum())
                if n<30:continue
                gp=_goal19_probs(fit[0],fit[1],int(h),int(a))
                for k in keys:
                    result[k]['h'].append((tr_y[k][mask].sum()+1.)/(n+2.))
                    result[k]['g'].append(gp[k])
                    result[k]['y'].append(outcomes[k][i])
            return result
        v=predict(validation);t=predict(test)
        summary.append({'Fold':fold+1,'Training matches':len(train),
                        'Validation sampled':len(validation),'Test sampled':len(test),
                        'Validation from':str(pd.Timestamp(start_v).date()),
                        'Test from':str(pd.Timestamp(end_v).date())})
        for k in keys:
            if len(v[k]['y'])<15 or len(t[k]['y'])<15:continue
            vh=np.asarray(v[k]['h']);vg=np.asarray(v[k]['g']);vy=np.asarray(v[k]['y'])
            scores=[float(np.mean(((1-w)*vh+w*vg-vy)**2)) for w in grid]
            weight=grid[int(np.argmin(scores))]
            th=np.asarray(t[k]['h']);tg=np.asarray(t[k]['g']);ty=np.asarray(t[k]['y'])
            blend=(1-weight)*th+weight*tg
            for model_name, estimates in [('Historical',th),('Goal',tg),('Blend',blend)]:
                for predicted, observed in zip(estimates,ty):
                    calibration_rows.append({
                        'Fold':fold+1,'Market':k,'Model':model_name,
                        'Predicted probability':float(predicted),
                        'Outcome':int(observed)})
            allrows.append({'Fold':fold+1,'Market':k,'Validation matches':len(vy),
                            'Test matches':len(ty),'Goal weight %':int(weight*100),
                            'Historical Brier':float(np.mean((th-ty)**2)),
                            'Goal Brier':float(np.mean((tg-ty)**2)),
                            'Blend Brier':float(np.mean((blend-ty)**2)),
                            'Historical forecast %':float(th.mean()*100),
                            'Goal forecast %':float(tg.mean()*100),
                            'Blend forecast %':float(blend.mean()*100),
                            'Actual %':float(ty.mean()*100)})
    if not allrows:return None,'Too few comparable predictions in the rolling folds.'
    return {'rows':pd.DataFrame(allrows),'folds':pd.DataFrame(summary),
            'calibration':pd.DataFrame(calibration_rows)},None

with st.expander('Run Stage 19E rolling accuracy test',expanded=False):
    st.caption('Uses four expanding training windows. For each fold, the blend weight is chosen '
               'without seeing the following test outcomes. Up to 100 validation and 100 test '
               'fixtures per fold are sampled; only matches covered by both models are compared.')
    if st.button('Run four rolling historical tests',key='run19e'):
        result19e,error19e=_validate19e()
        if error19e:st.warning(error19e)
        else:st.session_state['stage19e_results']=result19e
    if 'stage19e_results' in st.session_state:
        result19e=st.session_state['stage19e_results']
        st.markdown('**Chronological folds**')
        st.dataframe(result19e['folds'],hide_index=True,use_container_width=True)
        raw=result19e['rows']
        st.markdown('**Brier scores by market and fold (lower is better)**')
        shown=raw.copy()
        for c in ['Historical Brier','Goal Brier','Blend Brier']:
            shown[c]=shown[c].round(4)
        for c in ['Historical forecast %','Goal forecast %','Blend forecast %','Actual %']:
            shown[c]=shown[c].round(1)
        st.dataframe(shown,hide_index=True,use_container_width=True)
        st.download_button('Download Stage 19E rolling CSV',
                           data=raw.to_csv(index=False).encode('utf-8-sig'),
                           file_name='stage19e_rolling_accuracy.csv',mime='text/csv',key='download19e')
        st.warning('Exploratory accuracy only, not proven betting value. Model tuning based on '
                   'these folds would require another later untouched test. Scores reflect only '
                   'fixtures covered by both models, not all live matches.')


# Stage 19F — out-of-sample probability calibration audit.
# Reuses forward-only Stage 19E predictions; does not alter live decisions.
st.subheader('Stage 19F · Halftime probability calibration audit')
st.caption('Are our 20%, 40%, or 60% predictions occurring that often? '
           'Uses only the held-out match predictions from the four forward-only '
           'Stage 19E folds. No bookmaker prices, betting signals or staking.')

with st.expander('Run Stage 19F calibration audit', expanded=False):
    st.caption('Run Stage 19E first if needed. Calibration is shown separately '
               'for each model and market. Small bins are noisy; the same match '
               'appears in multiple related markets, so counts must not be '
               'treated as independent betting opportunities.')
    if st.button('Run calibration audit', key='run19f'):
        results, error = _validate19e()
        if error:
            st.warning(error)
        else:
            st.session_state['stage19f_calibration'] = results['calibration']
    if 'stage19f_calibration' in st.session_state:
        cal = st.session_state['stage19f_calibration']
        if cal.empty:
            st.warning('No matched holdout predictions available.')
        else:
            markets = sorted(cal['Market'].unique().tolist())
            selected_market = st.selectbox('Market to inspect', markets, key='stage19f_market')
            subset = cal[cal['Market'] == selected_market].copy()
            subset['Probability band'] = pd.cut(
                subset['Predicted probability'],
                bins=[0,.2,.4,.6,.8,1.0000001],
                labels=['0–20%','20–40%','40–60%','60–80%','80–100%'],
                include_lowest=True)
            grouped = (subset.groupby(['Model','Probability band'],observed=True)
                       .agg(Observations=('Outcome','size'),
                            **{'Average predicted %':('Predicted probability',lambda x:100*x.mean()),
                               'Actual frequency %':('Outcome',lambda x:100*x.mean())})
                       .reset_index())
            grouped['Calibration gap (pp)'] = (
                grouped['Actual frequency %']-grouped['Average predicted %'])
            st.dataframe(grouped.round(2), hide_index=True, use_container_width=True)
            scores = (subset.assign(
                squared_error=(subset['Predicted probability']-subset['Outcome'])**2,
                absolute_error=(subset['Predicted probability']-subset['Outcome']).abs())
                .groupby('Model',as_index=False)
                .agg(Observations=('Outcome','size'),
                     **{'Brier':('squared_error','mean'),
                        'Mean predicted %':('Predicted probability',lambda x:100*x.mean()),
                        'Actual %':('Outcome',lambda x:100*x.mean())}))
            st.markdown('**Holdout accuracy and average calibration by model**')
            st.dataframe(scores.round(4), hide_index=True, use_container_width=True)
            st.download_button(
                'Download Stage 19F calibration CSV',
                data=grouped.to_csv(index=False).encode('utf-8-sig'),
                file_name='stage19f_calibration_bins.csv', mime='text/csv',
                key='stage19f_bins_export')
            st.download_button(
                'Download Stage 19F individual holdout predictions CSV',
                data=cal.to_csv(index=False).encode('utf-8-sig'),
                file_name='stage19f_holdout_predictions.csv', mime='text/csv',
                key='stage19f_predictions_export')
            st.warning('Calibration is exploratory: only covered holdout matches '
                       'are included. The 0–20% bin is too broad to validate '
                       'extreme longshots such as 41.00 odds. No model is '
                       'recalibrated or promoted to live betting by this test.')


# Stage 19G — all-market rolling calibration and longshot audit (read-only).
st.subheader('Stage 19G · All-market calibration and outsider audit')
st.caption('Audits all 11 halftime markets across the four forward-only holdout periods. '
           'Does not change live forecasts, betting selections, or staking.')
with st.expander('Run Stage 19G full audit', expanded=False):
    if st.button('Run all-market and outsider audit', key='run19g'):
        previous = st.session_state.get('stage19e_results')
        if isinstance(previous, dict) and 'calibration' in previous:
            audit_results, audit_error = previous, None
        else:
            audit_results, audit_error = _validate19e()
        if audit_error:
            st.warning(audit_error)
        else:
            st.session_state['stage19g_data'] = audit_results['calibration'].copy()
    if 'stage19g_data' in st.session_state:
        audit = st.session_state['stage19g_data'].copy()
        if audit.empty:
            st.warning('No holdout predictions passed the historical matching filters.')
        else:
            audit['Squared error'] = (audit['Predicted probability'] - audit['Outcome'])**2
            overview = (audit.groupby(['Market','Model'],as_index=False)
                .agg(Observations=('Outcome','size'),
                     Brier=('Squared error','mean'),
                     **{'Average predicted %':('Predicted probability',lambda v:100*v.mean()),
                        'Actual %':('Outcome',lambda v:100*v.mean())}))
            overview['Gap (pp)'] = overview['Average predicted %']-overview['Actual %']
            st.markdown('**All 11 markets: out-of-sample accuracy and average bias**')
            st.dataframe(overview.round(3),hide_index=True,use_container_width=True)
            st.download_button('Download all-market overview CSV',
                overview.to_csv(index=False).encode('utf-8-sig'),
                file_name='stage19g_all_markets.csv',mime='text/csv',key='dl19gall')

            cutoffs=[-0.0000001,.025,.05,.10,.20,.40,.60,.80,1.0000001]
            names=['0–2.5%','2.5–5%','5–10%','10–20%','20–40%',
                   '40–60%','60–80%','80–100%']
            audit['Probability band']=pd.cut(audit['Predicted probability'],
                bins=cutoffs,labels=names,include_lowest=True)
            bands=(audit.groupby(['Market','Model','Probability band'],
                observed=True,as_index=False)
                .agg(Observations=('Outcome','size'),
                     **{'Predicted %':('Predicted probability',lambda v:100*v.mean()),
                        'Actual %':('Outcome',lambda v:100*v.mean())}))
            bands['Overprediction (pp)']=bands['Predicted %']-bands['Actual %']
            bands['Small sample (<30)']=bands['Observations']<30
            st.markdown('**Probability bands (all markets, including outsiders)**')
            st.dataframe(bands.round(3),hide_index=True,use_container_width=True)
            st.download_button('Download all-market probability bands CSV',
                bands.to_csv(index=False).encode('utf-8-sig'),
                file_name='stage19g_probability_bands.csv',mime='text/csv',key='dl19gbands')

            by_fold=(audit.groupby(['Fold','Market','Model'],as_index=False)
                .agg(Observations=('Outcome','size'),Brier=('Squared error','mean'),
                     **{'Predicted %':('Predicted probability',lambda v:100*v.mean()),
                        'Actual %':('Outcome',lambda v:100*v.mean())}))
            by_fold['Overprediction (pp)']=by_fold['Predicted %']-by_fold['Actual %']
            st.markdown('**Four chronological periods: model performance**')
            st.dataframe(by_fold.round(3),hide_index=True,use_container_width=True)
            st.download_button('Download rolling-period audit CSV',
                by_fold.to_csv(index=False).encode('utf-8-sig'),
                file_name='stage19g_rolling_periods.csv',mime='text/csv',key='dl19gfolds')
            st.warning('A low-count probability band cannot establish mispricing. '
                       'The same fixtures contribute to related markets, so rows are '
                       'correlated. These are prediction tests, not historical odds '
                       'or evidence of betting profit. No automatic model changes.')


# Stage 19H — larger chronological holdout coverage (research only).
st.subheader('Stage 19H · Expanded forward-only holdout audit')
st.caption('Increase historical test coverage while keeping each prediction trained only on older games. '
           'No change to live forecasts, paper journal, odds, or betting decisions.')
with st.expander('Run Stage 19H expanded historical test', expanded=False):
    test_limit = st.selectbox('Maximum sampled fixtures per validation/test period',
                              options=[100,250,500,1000,2000], index=2, key='stage19h_limit')
    st.caption('The 30-match historical-neighbour requirement still applies. '
               'Many sampled fixtures may be excluded. Large runs can be slow or '
               'exceed Streamlit resource limits; start at 500.')
    if st.button('Run expanded rolling test', key='run19h'):
        with st.spinner('Evaluating forward-only holdout fixtures…'):
            expanded, expanded_error = _validate19e(max_per_period=test_limit)
        if expanded_error:
            st.warning(expanded_error)
        else:
            st.session_state['stage19h_results'] = expanded
            st.session_state['stage19h_limit_used'] = test_limit
    if 'stage19h_results' in st.session_state:
        r = st.session_state['stage19h_results']
        prediction_rows = r['calibration'].copy()
        fold_meta = r['folds'].copy()
        per_market = r['rows'].copy()
        # Count unique holdout fixtures, not 11 related outcomes per fixture.
        # All markets use the same matched set within each fold.
        # Robust count: each eligible market has one prediction per matched fixture.
        coverage = (prediction_rows[prediction_rows['Model']=='Goal']
                    .groupby(['Fold','Market']).size().reset_index(name='Matched fixtures')
                    .groupby('Fold',as_index=False)['Matched fixtures'].max())
        coverage = fold_meta.merge(coverage,on='Fold',how='left')
        coverage['Matched fixtures'] = coverage['Matched fixtures'].fillna(0).astype(int)
        coverage['Excluded test fixtures'] = coverage['Test sampled']-coverage['Matched fixtures']
        st.markdown('**Coverage: sampled fixtures versus model-qualified fixtures**')
        st.dataframe(coverage,hide_index=True,use_container_width=True)
        st.download_button('Download Stage 19H coverage CSV',
            coverage.to_csv(index=False).encode('utf-8-sig'),
            file_name='stage19h_coverage.csv',mime='text/csv',key='dl19hcoverage')
        st.markdown('**Chronological model accuracy by market and period**')
        st.dataframe(per_market.round(4),hide_index=True,use_container_width=True)
        st.download_button('Download Stage 19H model scores CSV',
            per_market.to_csv(index=False).encode('utf-8-sig'),
            file_name='stage19h_model_scores.csv',mime='text/csv',key='dl19hscores')
        st.download_button('Download Stage 19H individual predictions CSV',
            prediction_rows.to_csv(index=False).encode('utf-8-sig'),
            file_name='stage19h_holdout_predictions.csv',mime='text/csv',key='dl19hpredictions')
        st.warning('These are out-of-sample prediction checks, not betting returns. '
                   'They reuse the same historical source, and related markets '
                   'share fixtures. No bookmaker halftime odds are present. '
                   'Large sample size does not establish a profitable edge.')


# Stage 19I — market-level reliability and selection coverage (research only).
st.subheader('Stage 19I · Market reliability and selection coverage')
st.caption('Checks every market, model and rolling period. Reports calibration by '
           'probability range, sparse outsider bins, and historical match coverage. '
           'Does not change the live scanner or claim an edge over bookmaker odds.')
with st.expander('Run Stage 19I reliability audit', expanded=False):
    limit19i = st.selectbox('Sampled fixtures per period',
                           [250,500,1000,2000], index=1, key='limit19i')
    st.caption('A 500-fixture run is a good starting point. The historical neighbour '
               'filter excludes fixtures that lack 30 comparable earlier matches.')
    if st.button('Run Stage 19I audit', key='run19i'):
        with st.spinner('Checking historical predictions and coverage…'):
            result19i, err19i = _validate19e(max_per_period=limit19i)
        if err19i:
            st.warning(err19i)
        else:
            st.session_state['result19i'] = result19i
    if 'result19i' in st.session_state:
        result19i = st.session_state['result19i']
        p = result19i['calibration'].copy()
        folds = result19i['folds'].copy()
        if p.empty:
            st.warning('No eligible predictions were generated.')
        else:
            p['Probability band'] = pd.cut(
                p['Predicted probability'],
                bins=[0,.025,.05,.10,.20,.40,.60,.80,1.000001],
                labels=['0–2.5%','2.5–5%','5–10%','10–20%',
                        '20–40%','40–60%','60–80%','80–100%'],
                include_lowest=True)
            p['Squared error'] = (p['Predicted probability']-p['Outcome'])**2
            reliability = (p.groupby(['Market','Model','Probability band'],
                                     observed=True)
                           .agg(Observations=('Outcome','size'),
                                Mean_prediction=('Predicted probability','mean'),
                                Actual_rate=('Outcome','mean'),
                                Brier=('Squared error','mean'))
                           .reset_index())
            reliability['Predicted %'] = 100*reliability['Mean_prediction']
            reliability['Actual %'] = 100*reliability['Actual_rate']
            reliability['Gap (pp)'] = reliability['Actual %']-reliability['Predicted %']
            reliability['Low sample'] = reliability['Observations']<30
            reliability = reliability.drop(columns=['Mean_prediction','Actual_rate'])
            by_period = (p.groupby(['Fold','Market','Model'],as_index=False)
                         .agg(Observations=('Outcome','size'),
                              Brier=('Squared error','mean'),
                              Mean_prediction=('Predicted probability','mean'),
                              Actual_rate=('Outcome','mean')))
            by_period['Predicted %'] = 100*by_period.pop('Mean_prediction')
            by_period['Actual %'] = 100*by_period.pop('Actual_rate')
            by_period['Gap (pp)'] = by_period['Actual %']-by_period['Predicted %']
            matched = (p[p['Model']=='Goal']
                       .groupby(['Fold','Market']).size().reset_index(name='Matched')
                       .groupby('Fold',as_index=False)['Matched'].max())
            coverage = folds.merge(matched,on='Fold',how='left')
            coverage['Matched'] = coverage['Matched'].fillna(0).astype(int)
            coverage['Excluded'] = coverage['Test sampled']-coverage['Matched']
            coverage['Coverage %'] = (100*coverage['Matched']/
                                      coverage['Test sampled'].clip(lower=1))
            st.markdown('**Historical match coverage by test period**')
            st.dataframe(coverage.round(2),hide_index=True,use_container_width=True)
            st.download_button('Download Stage 19I coverage CSV',
                               coverage.to_csv(index=False).encode('utf-8-sig'),
                               file_name='stage19i_coverage.csv',
                               mime='text/csv',key='dl19icov')
            st.markdown('**Reliability by market, model and probability band**')
            st.dataframe(reliability.round(3),hide_index=True,use_container_width=True)
            st.download_button('Download Stage 19I reliability CSV',
                               reliability.to_csv(index=False).encode('utf-8-sig'),
                               file_name='stage19i_reliability.csv',
                               mime='text/csv',key='dl19irel')
            st.markdown('**Accuracy and calibration by rolling period**')
            st.dataframe(by_period.round(3),hide_index=True,use_container_width=True)
            st.download_button('Download Stage 19I rolling periods CSV',
                               by_period.to_csv(index=False).encode('utf-8-sig'),
                               file_name='stage19i_periods.csv',
                               mime='text/csv',key='dl19iperiods')
            st.warning('Low-count bins are not reliable. The historical exclusion '
                       'report gives coverage counts, not the reasons for every '
                       'excluded fixture. No historical halftime bookmaker prices '
                       'are available here, so profitability and actual value '
                       'cannot be established. These are correlated market '
                       'predictions from the same fixtures; do not count them '
                       'as independent bets.')


# Stage 19J — explain missing historical match coverage, without changing models.
@st.cache_data(show_spinner='Diagnosing historical coverage by chronological period…')
def _stage19j_diagnose(max_per_period=500):
    pool=_goal19_pool().copy()
    pool['_rolling_date']=pd.to_datetime(
        pool['date'] if 'date' in pool else pool['Date'],
        errors='coerce',dayfirst=True)
    pool=pool.dropna(subset=['_rolling_date']).sort_values('_rolling_date')
    if len(pool)<1500:
        return None,'Insufficient dated historical matches.'
    dates=np.sort(pool['_rolling_date'].dt.normalize().unique())
    if len(dates)<100:
        return None,'Insufficient distinct match dates.'
    bounds=[dates[min(int(len(dates)*q),len(dates)-1)]
            for q in [0.50,0.60,0.70,0.80,0.90,0.999999]]
    summary=[]; detail=[]
    for fold in range(4):
        train=pool[pool['_rolling_date']<bounds[fold]].copy()
        test=pool[(pool['_rolling_date']>=bounds[fold+1])&
                  (pool['_rolling_date']<bounds[fold+2])].copy()
        if len(test)>max_per_period:
            test=test.iloc[np.linspace(0,len(test)-1,max_per_period,dtype=int)].copy()
        tr=train[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
        for _,r in test.iterrows():
            try:
                h=int(r['HTHG']); a=int(r['HTAG'])
                fo=float(r['fav']); hx=float(r[xg1]); ax=float(r[xg2])
                mask=((tr[:,0]==h)&(tr[:,1]==a)&
                      (np.abs(tr[:,2]-fo)<=0.35)&
                      (np.abs(tr[:,3]-hx)<=0.40)&
                      (np.abs(tr[:,4]-ax)<=0.40))
                n=int(mask.sum())
                if n<30:
                    reason='Fewer than 30 comparable earlier matches'
                else:
                    fit=_goal19_estimate(train,h,a,fo,hx,ax)
                    reason='Eligible for both models' if fit is not None else 'Goal-model fit unavailable'
            except (TypeError,ValueError,KeyError,OverflowError):
                n=0; reason='Invalid or missing test features'
                h=r.get('HTHG');a=r.get('HTAG');fo=r.get('fav')
                hx=r.get(xg1);ax=r.get(xg2)
            detail.append({
                'Fold':fold+1,
                'Match date':str(pd.Timestamp(r['_rolling_date']).date()),
                'HT home goals':h,'HT away goals':a,
                'Favourite opening odds':fo,
                'Home HT xG':hx,'Away HT xG':ax,
                'Comparable earlier matches':n,
                'Coverage status':reason,
                'Odds band': ('<1.50' if pd.notna(fo) and fo<1.5 else
                              '1.50–1.99' if pd.notna(fo) and fo<2 else
                              '2.00–2.99' if pd.notna(fo) and fo<3 else
                              '3.00+' if pd.notna(fo) else 'Missing'),
                'HT score':f'{h}–{a}'})
        summary.append({'Fold':fold+1,'Training matches':len(train),
                        'Test sampled':len(test)})
    if not detail:return None,'No test fixtures available.'
    d=pd.DataFrame(detail)
    f=pd.DataFrame(summary)
    reasons=(d.groupby(['Fold','Coverage status'],dropna=False)
             .size().reset_index(name='Matches'))
    by_odds=(d.groupby(['Odds band','Coverage status'],dropna=False)
             .size().reset_index(name='Matches'))
    by_score=(d.groupby(['HT score','Coverage status'],dropna=False)
              .size().reset_index(name='Matches'))
    return {'detail':d,'folds':f,'reasons':reasons,
            'odds':by_odds,'scores':by_score},None

st.subheader('Stage 19J · Why historical fixtures are excluded')
st.caption('Audits the exact forward-only match criteria used in Stage 19E–19I. '
           'Explains exclusions by period, halftime score and prematch favourite '
           'odds. No change to live scanner, model weights or prediction journal.')
with st.expander('Run Stage 19J coverage diagnostics',expanded=False):
    cap19j=st.selectbox('Fixtures sampled per rolling period',
                       [250,500,1000,2000],index=1,key='cap19j')
    if st.button('Run Stage 19J diagnostics',key='run19j'):
        with st.spinner('Checking every sampled fixture against earlier history…'):
            diag19j,error19j=_stage19j_diagnose(cap19j)
        if error19j:
            st.warning(error19j)
        else:
            st.session_state['diag19j']=diag19j
    if 'diag19j' in st.session_state:
        d19j=st.session_state['diag19j']
        st.markdown('**Reasons for exclusion, by period**')
        st.dataframe(d19j['reasons'],hide_index=True,use_container_width=True)
        st.markdown('**Coverage by opening favourite odds**')
        st.dataframe(d19j['odds'],hide_index=True,use_container_width=True)
        st.markdown('**Coverage by halftime score**')
        st.dataframe(d19j['scores'],hide_index=True,use_container_width=True)
        st.markdown('**Individual fixture diagnostics**')
        st.dataframe(d19j['detail'],hide_index=True,use_container_width=True)
        for label,filename,key in [
            ('Full fixture diagnostics','stage19j_fixture_diagnostics.csv','detail'),
            ('Exclusion reasons','stage19j_exclusion_reasons.csv','reasons'),
            ('Coverage by odds','stage19j_odds_coverage.csv','odds'),
            ('Coverage by halftime score','stage19j_score_coverage.csv','scores')]:
            st.download_button(
                'Download '+label+' CSV',
                d19j[key].to_csv(index=False).encode('utf-8-sig'),
                file_name=filename,mime='text/csv',key='download19j_'+key)
        st.info('This is a diagnostic of the paired-comparison eligibility '
                'rule, not proof that the goal model cannot predict excluded '
                'fixtures. It cannot measure betting profitability without '
                'historical executable halftime prices.')


# Stage 19K — forward-only goal-model validation on previously excluded fixtures.
@st.cache_data(show_spinner='Testing the goal model on matched and excluded fixtures…')
def _stage19k_test(max_per_period=500):
    pool=_goal19_pool().copy()
    pool['_rolling_date']=pd.to_datetime(
        pool['date'] if 'date' in pool else pool['Date'],
        errors='coerce',dayfirst=True)
    pool=pool.dropna(subset=['_rolling_date']).sort_values('_rolling_date')
    if len(pool)<1500:return None,'Insufficient historical data.'
    dates=np.sort(pool['_rolling_date'].dt.normalize().unique())
    if len(dates)<100:return None,'Insufficient distinct match dates.'
    bounds=[dates[min(int(len(dates)*q),len(dates)-1)]
            for q in [0.50,0.60,0.70,0.80,0.90,0.999999]]
    allrows=[];coverage=[]
    for fold in range(4):
        train=pool[pool['_rolling_date']<bounds[fold]].copy()
        test=pool[(pool['_rolling_date']>=bounds[fold+1])&
                  (pool['_rolling_date']<bounds[fold+2])].copy()
        if len(test)>max_per_period:
            test=test.iloc[np.linspace(0,len(test)-1,max_per_period,dtype=int)].copy()
        tr=train[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
        actuals={k:np.asarray(v,dtype=float)
                 for k,v in market_outcomes(test).items()}
        counts={'Matched (30+ neighbours)':0,
                'Excluded (<30 neighbours)':0,'Goal fit unavailable':0}
        for i,(_,r) in enumerate(test.iterrows()):
            try:
                h=int(r['HTHG']);a=int(r['HTAG'])
                fo=float(r['fav']);hx=float(r[xg1]);ax=float(r[xg2])
                n=int(((tr[:,0]==h)&(tr[:,1]==a)&
                       (np.abs(tr[:,2]-fo)<=0.35)&
                       (np.abs(tr[:,3]-hx)<=0.40)&
                       (np.abs(tr[:,4]-ax)<=0.40)).sum())
                group=('Matched (30+ neighbours)' if n>=30
                       else 'Excluded (<30 neighbours)')
                fit=_goal19_estimate(train,h,a,fo,hx,ax)
                if fit is None:
                    counts['Goal fit unavailable']+=1
                    continue
                counts[group]+=1
                probs=_goal19_probs(fit[0],fit[1],h,a)
                for market,pred in probs.items():
                    y=actuals[market][i]
                    if not np.isfinite(y):continue
                    allrows.append({
                        'Fold':fold+1,'Coverage group':group,
                        'Market':market,'Prediction':float(pred),
                        'Outcome':int(y),'Squared error':float((pred-y)**2),
                        'Comparable earlier matches':n,
                        'Effective neighbours (goal)':float(fit[2]),
                        'Favourite opening odds':fo,
                        'HT score':f'{h}–{a}'})
            except (KeyError,ValueError,TypeError,OverflowError):
                counts['Goal fit unavailable']+=1
        for group,n in counts.items():
            coverage.append({'Fold':fold+1,'Group':group,'Fixtures':n,
                             'Sampled':len(test)})
    if not allrows:return None,'No usable predictions.'
    p=pd.DataFrame(allrows)
    p['Probability band']=pd.cut(
        p['Prediction'],
        bins=[0,.025,.05,.10,.20,.40,.60,.80,1.000001],
        labels=['0–2.5%','2.5–5%','5–10%','10–20%',
                '20–40%','40–60%','60–80%','80–100%'],
        include_lowest=True)
    scores=(p.groupby(['Coverage group','Market'],as_index=False)
            .agg(Fixtures=('Outcome','size'),
                 Brier=('Squared error','mean'),
                 **{'Predicted %':('Prediction',lambda v:100*v.mean()),
                    'Actual %':('Outcome',lambda v:100*v.mean())}))
    scores['Gap (pp)']=scores['Actual %']-scores['Predicted %']
    by_fold=(p.groupby(['Fold','Coverage group','Market'],as_index=False)
             .agg(Fixtures=('Outcome','size'),
                  Brier=('Squared error','mean'),
                  **{'Predicted %':('Prediction',lambda v:100*v.mean()),
                     'Actual %':('Outcome',lambda v:100*v.mean())}))
    bands=(p.groupby(['Coverage group','Market','Probability band'],
                     observed=True,as_index=False)
           .agg(Fixtures=('Outcome','size'),
                **{'Predicted %':('Prediction',lambda v:100*v.mean()),
                   'Actual %':('Outcome',lambda v:100*v.mean())}))
    bands['Gap (pp)']=bands['Actual %']-bands['Predicted %']
    bands['Small sample (<30)']=bands['Fixtures']<30
    return {'coverage':pd.DataFrame(coverage),'scores':scores,
            'periods':by_fold,'bands':bands},None

st.subheader('Stage 19K · Can the goal model cover excluded matches?')
st.caption('Forward-only holdout test of the goal model on both matched and '
           'previously excluded fixtures, with identical time periods. '
           'No changes to live predictions or betting selections.')
with st.expander('Run Stage 19K excluded-fixture test',expanded=False):
    limit19k=st.selectbox('Sampled fixtures per period',
                         [250,500,1000,2000],index=1,key='limit19k')
    if st.button('Run Stage 19K test',key='run19k'):
        with st.spinner('Evaluating holdout fixtures…'):
            result19k,error19k=_stage19k_test(limit19k)
        if error19k:st.warning(error19k)
        else:st.session_state['result19k']=result19k
    if 'result19k' in st.session_state:
        result19k=st.session_state['result19k']
        for title,key,filename in [
            ('Fixture coverage','coverage','stage19k_coverage.csv'),
            ('Model accuracy by market and coverage','scores','stage19k_scores.csv'),
            ('Accuracy by rolling period','periods','stage19k_periods.csv'),
            ('Probability calibration bands','bands','stage19k_bands.csv')]:
            st.markdown('**'+title+'**')
            st.dataframe(result19k[key].round(4),hide_index=True,
                         use_container_width=True)
            st.download_button(
                'Download '+title+' CSV',
                result19k[key].to_csv(index=False).encode('utf-8-sig'),
                file_name=filename,mime='text/csv',key='stage19k_dl_'+key)
        st.warning('Excluded and matched fixtures have different difficulty '
                   'and event frequencies. Compare Brier scores alongside '
                   'calibration, sample sizes and each period; a lower score '
                   'does not prove profitable betting. Historical bookmaker '
                   'halftime prices are not available for this test.')


# Stage 19L — prospective-style, forward-only hybrid policy comparison.
@st.cache_data(show_spinner='Evaluating goal-only versus historical fallback policy…')
def _stage19l_test(max_per_period=500):
    pool=_goal19_pool().copy()
    pool['_rolling_date']=pd.to_datetime(
        pool['date'] if 'date' in pool else pool['Date'],
        errors='coerce',dayfirst=True)
    pool=pool.dropna(subset=['_rolling_date']).sort_values('_rolling_date')
    if len(pool)<1500:return None,'Insufficient historical data.'
    dates=np.sort(pool['_rolling_date'].dt.normalize().unique())
    if len(dates)<100:return None,'Insufficient distinct match dates.'
    bounds=[dates[min(int(len(dates)*q),len(dates)-1)]
            for q in [0.50,0.60,0.70,0.80,0.90,0.999999]]
    keys=list(_goal19_probs(1.,1.,0,0).keys())
    weights=[0.,.25,.5,.75,1.]
    detail=[];chosen=[];coverage=[]
    def cap(frame):
        if len(frame)<=max_per_period:return frame
        return frame.iloc[np.linspace(0,len(frame)-1,max_per_period,dtype=int)].copy()
    for fold in range(4):
        start_v,end_v,end_t=bounds[fold:fold+3]
        train=pool[pool['_rolling_date']<start_v].copy()
        validation=cap(pool[(pool['_rolling_date']>=start_v)&
                            (pool['_rolling_date']<end_v)].copy())
        test=cap(pool[(pool['_rolling_date']>=end_v)&
                      (pool['_rolling_date']<end_t)].copy())
        if min(len(train),len(validation),len(test))<40:continue
        tr=train[['HTHG','HTAG','fav',xg1,xg2]].to_numpy(float)
        train_y={k:np.asarray(v,dtype=float)
                 for k,v in market_outcomes(train).items()}
        def forecasts(frame):
            outcomes={k:np.asarray(v,dtype=float)
                      for k,v in market_outcomes(frame).items()}
            rows=[]
            for i,(_,r) in enumerate(frame.iterrows()):
                try:
                    h=int(r['HTHG']);a=int(r['HTAG'])
                    fo=float(r['fav']);hx=float(r[xg1]);ax=float(r[xg2])
                    fit=_goal19_estimate(train,h,a,fo,hx,ax)
                    if fit is None:continue
                    mask=((tr[:,0]==h)&(tr[:,1]==a)&
                          (np.abs(tr[:,2]-fo)<=0.35)&
                          (np.abs(tr[:,3]-hx)<=0.40)&
                          (np.abs(tr[:,4]-ax)<=0.40))
                    n=int(mask.sum())
                    goal=_goal19_probs(fit[0],fit[1],h,a)
                    for market in keys:
                        outcome=float(outcomes[market][i])
                        if not np.isfinite(outcome):continue
                        hist=((train_y[market][mask].sum()+1.)/(n+2.)
                              if n>=30 else np.nan)
                        rows.append({'Market':market,'Outcome':int(outcome),
                                     'Goal':float(goal[market]),
                                     'Historical':float(hist),
                                     'Coverage':('Matched' if n>=30 else 'Excluded'),
                                     'Neighbours':n})
                except (KeyError,ValueError,TypeError,OverflowError):
                    continue
            return pd.DataFrame(rows)
        v=forecasts(validation);t=forecasts(test)
        if v.empty or t.empty:continue
        for market in keys:
            vm=v[(v['Market']==market)&(v['Coverage']=='Matched')]
            tm=t[t['Market']==market]
            if tm.empty:continue
            if len(vm)>=15:
                briers=[np.mean(((1-w)*vm['Historical'].to_numpy()+
                                  w*vm['Goal'].to_numpy()-
                                  vm['Outcome'].to_numpy())**2)
                        for w in weights]
                w=weights[int(np.argmin(briers))]
            else:
                w=1.  # safe fallback when insufficient validation
            chosen.append({'Fold':fold+1,'Market':market,
                           'Validation matched':len(vm),'Goal weight':w,
                           'Test fixtures':len(tm)})
            for _,r in tm.iterrows():
                goal=float(r['Goal'])
                hybrid=(goal if r['Coverage']=='Excluded'
                        else (1-w)*float(r['Historical'])+w*goal)
                y=int(r['Outcome'])
                detail.append({'Fold':fold+1,'Market':market,
                               'Coverage':r['Coverage'],'Neighbours':int(r['Neighbours']),
                               'Outcome':y,'Goal only':goal,'Hybrid':hybrid,
                               'Goal squared error':(goal-y)**2,
                               'Hybrid squared error':(hybrid-y)**2})
        coverage.append({'Fold':fold+1,'Training':len(train),
                         'Validation sampled':len(validation),
                         'Test sampled':len(test)})
    if not detail:return None,'No holdout predictions available.'
    d=pd.DataFrame(detail)
    scores=(d.groupby(['Market','Coverage'],as_index=False)
            .agg(Fixtures=('Outcome','size'),
                 **{'Goal Brier':('Goal squared error','mean'),
                    'Hybrid Brier':('Hybrid squared error','mean')}))
    scores['Hybrid minus goal']=scores['Hybrid Brier']-scores['Goal Brier']
    byfold=(d.groupby(['Fold','Coverage'],as_index=False)
            .agg(Fixtures=('Outcome','size'),
                 **{'Goal Brier':('Goal squared error','mean'),
                    'Hybrid Brier':('Hybrid squared error','mean')}))
    byfold['Hybrid minus goal']=byfold['Hybrid Brier']-byfold['Goal Brier']
    return {'scores':scores,'periods':byfold,
            'weights':pd.DataFrame(chosen),'coverage':pd.DataFrame(coverage),
            'predictions':d},None

st.subheader('Stage 19L · Goal-only versus hybrid fallback')
st.caption('Tests a fixed rule: use the goal model on fixtures with fewer than '
           '30 historical neighbours; on covered fixtures, use a blend weight '
           'selected on earlier validation fixtures. The same holdout fixtures '
           'are scored under both policies. Live scanner remains unchanged.')
with st.expander('Run Stage 19L hybrid policy test',expanded=False):
    limit19l=st.selectbox('Sampled fixtures per period',
                         [250,500,1000,2000],index=1,key='limit19l')
    if st.button('Run Stage 19L test',key='run19l'):
        with st.spinner('Training, validating and evaluating rolling holdouts…'):
            result19l,error19l=_stage19l_test(limit19l)
        if error19l:st.warning(error19l)
        else:st.session_state['result19l']=result19l
    if 'result19l' in st.session_state:
        result19l=st.session_state['result19l']
        for label,key,name in [
            ('Accuracy by market and coverage','scores','stage19l_market_scores.csv'),
            ('Accuracy by period','periods','stage19l_period_scores.csv'),
            ('Validation-selected blend weights','weights','stage19l_weights.csv'),
            ('Sample coverage','coverage','stage19l_coverage.csv'),
            ('Individual holdout predictions','predictions','stage19l_predictions.csv')]:
            st.markdown('**'+label+'**')
            st.dataframe(result19l[key].round(5),hide_index=True,
                         use_container_width=True)
            st.download_button('Download '+label+' CSV',
                result19l[key].to_csv(index=False).encode('utf-8-sig'),
                file_name=name,mime='text/csv',key='dl19l_'+key)
        st.warning('Repeatedly inspecting these historical folds can lead to '
                   'overfitting. The hybrid rule is research-only and has not '
                   'been promoted to live predictions. Neither model has been '
                   'verified against executable historical halftime bookmaker '
                   'prices; Brier improvements do not prove betting profit.')


# Stage 20 — prospective quote-backed, deduplicated paper-value audit.
st.subheader('Stage 20 · Real-quote paper-value validation')
st.caption('Audits only prices already captured at halftime by Stage 18. '
           'One quote per match/market/bookmaker/time/price, not one per model. '
           'No orders are placed; live model forecasts are unchanged.')
if not _stage18_rows:
    st.info('No captured halftime bookmaker prices yet. Wait for future '
            'Stage 18 snapshots; never reconstruct historic prices.')
else:
    audit20=pd.DataFrame(_stage18_rows).copy()
    keys20=['Match','Captured UTC','Odds captured UTC','Market',
            'Bookmaker','Observed odds']
    # Do not mix settled and pending records for the same quote.
    audit20['Model probability %']=pd.to_numeric(
        audit20['Model probability %'],errors='coerce')
    audit20['Expected ROI % (model)']=pd.to_numeric(
        audit20['Expected ROI % (model)'],errors='coerce')
    audit20['Paper P/L per £1']=pd.to_numeric(
        audit20['Paper P/L per £1'],errors='coerce')
    audit20['Observed odds']=pd.to_numeric(
        audit20['Observed odds'],errors='coerce')
    audit20=audit20.dropna(subset=['Observed odds','Model probability %'])
    quotes20=(audit20.groupby(keys20,dropna=False,sort=False)
              .agg(Models=('Method',lambda x:', '.join(sorted(set(map(str,x))))),
                   Model_count=('Method','nunique'),
                   Min_model_probability_pct=('Model probability %','min'),
                   Max_model_probability_pct=('Model probability %','max'),
                   Min_model_EV_pct=('Expected ROI % (model)','min'),
                   Max_model_EV_pct=('Expected ROI % (model)','max'),
                   Result=('Result','first'),
                   Paper_PL_per_1=('Paper P/L per £1','first'),
                   Available_back_size=('Available back size','first'))
              .reset_index())
    quotes20['Positive by any model']=quotes20['Max_model_EV_pct']>0
    quotes20['Positive by all models']=quotes20['Min_model_EV_pct']>0
    quotes20['Longshot (odds 10+)']=quotes20['Observed odds']>=10
    quotes20['Timestamp recorded']=quotes20['Odds captured UTC'].notna() & (
        quotes20['Odds captured UTC'].astype(str).str.strip().ne(''))
    quotes20['Settled']=quotes20['Result'].isin(['Won','Lost'])
    quotes20['Candidate rule']=quotes20['Positive by all models']
    quote20_count=len(quotes20)
    settled20=quotes20[quotes20['Settled']]
    eligible20=quotes20[quotes20['Candidate rule']]
    eligible_settled20=eligible20[eligible20['Settled']]
    c20a,c20b,c20c,c20d=st.columns(4)
    c20a.metric('Unique recorded quotes',quote20_count)
    c20b.metric('Distinct matches',quotes20['Match'].nunique())
    c20c.metric('All-model-positive quotes',len(eligible20))
    c20d.metric('Settled candidates',len(eligible_settled20))
    st.caption('The default candidate rule requires positive expected value '
               'under EVERY recorded model for a quote. This is a conservative '
               'research filter, not a validated or executable betting strategy.')
    def _roi20(frame):
        return (100*frame['Paper_PL_per_1'].mean()
                if len(frame) else float('nan'))
    summary20=pd.DataFrame([
        {'Group':'All unique quotes','Quotes':len(quotes20),
         'Settled':len(settled20),'Wins':int((settled20['Result']=='Won').sum()),
         'Paper ROI %':_roi20(settled20)},
        {'Group':'Positive by any model','Quotes':int(quotes20['Positive by any model'].sum()),
         'Settled':int((settled20['Positive by any model']).sum()),
         'Wins':int(((settled20['Positive by any model'])&
                     (settled20['Result']=='Won')).sum()),
         'Paper ROI %':_roi20(settled20[settled20['Positive by any model']])},
        {'Group':'Positive by all models','Quotes':len(eligible20),
         'Settled':len(eligible_settled20),
         'Wins':int((eligible_settled20['Result']=='Won').sum()),
         'Paper ROI %':_roi20(eligible_settled20)},
        {'Group':'All-model-positive, odds <10','Quotes':int(
            (eligible20['Observed odds']<10).sum()),
         'Settled':int((eligible_settled20['Observed odds']<10).sum()),
         'Wins':int(((eligible_settled20['Observed odds']<10)&
                     (eligible_settled20['Result']=='Won')).sum()),
         'Paper ROI %':_roi20(eligible_settled20[
             eligible_settled20['Observed odds']<10])},
        {'Group':'All-model-positive, odds 10+','Quotes':int(
            (eligible20['Observed odds']>=10).sum()),
         'Settled':int((eligible_settled20['Observed odds']>=10).sum()),
         'Wins':int(((eligible_settled20['Observed odds']>=10)&
                     (eligible_settled20['Result']=='Won')).sum()),
         'Paper ROI %':_roi20(eligible_settled20[
             eligible_settled20['Observed odds']>=10])},
    ])
    st.markdown('**Deduplicated paper-return summary**')
    st.dataframe(summary20.round(2),hide_index=True,use_container_width=True)
    st.markdown('**All recorded quote details**')
    st.dataframe(quotes20.iloc[::-1],hide_index=True,use_container_width=True)
    market20=(eligible_settled20.groupby('Market',as_index=False)
              .agg(Unique_settled_quotes=('Paper_PL_per_1','size'),
                   Paper_PL_per_1_total=('Paper_PL_per_1','sum'),
                   Paper_ROI_pct=('Paper_PL_per_1',lambda x:100*x.mean()))
              if len(eligible_settled20)
              else pd.DataFrame(columns=['Market','Unique_settled_quotes',
                                         'Paper_PL_per_1_total','Paper_ROI_pct']))
    st.markdown('**All-model-positive settled results by market**')
    st.dataframe(market20.round(2),hide_index=True,use_container_width=True)
    for label,key,data20,name in [
        ('unique quotes','quotes',quotes20,'stage20_unique_quotes.csv'),
        ('summary','summary',summary20,'stage20_summary.csv'),
        ('market results','markets',market20,'stage20_market_results.csv')]:
        st.download_button('Download Stage 20 '+label+' CSV',
            data20.to_csv(index=False).encode('utf-8-sig'),
            file_name=name,mime='text/csv',key='stage20_download_'+key)
    st.warning('Important: a recorded quote is not proof of an executable '
               'price or available stake. Quotes can be delayed. The dataset '
               'is small and may contain repeated observations of the same '
               'fixture; different markets are correlated. Commission uses '
               'the sidebar setting. Model-positive expected value is not '
               'an independently verified edge. Future genuinely captured '
               'quotes and settled results are required.')


# Stage 20A — disagreement audit, using actual captured prices only.
st.subheader('Stage 20A · Model disagreement and value quality')
st.caption('Research-only review of disagreements at the same captured bookmaker '
           'quote. Preserves each model probability and expected return, '
           'rather than treating duplicate predictions as independent bets.')
if not _stage18_rows:
    st.info('No genuine priced snapshots available yet. The audit will populate '
            'when Stage 18 records bookmaker quotes.')
else:
    raw20a=pd.DataFrame(_stage18_rows).copy()
    numeric20a=['Observed odds','Model probability %',
                'Expected ROI % (model)','Paper P/L per £1']
    for col20a in numeric20a:
        raw20a[col20a]=pd.to_numeric(raw20a[col20a],errors='coerce')
    raw20a=raw20a.dropna(subset=['Observed odds','Model probability %'])
    quote_keys20a=['Match','Captured UTC','Odds captured UTC','Market',
                   'Bookmaker','Observed odds']
    # Explicitly keep model-specific values; never average model predictions.
    models20a=(raw20a.groupby(quote_keys20a+['Method'],dropna=False,as_index=False)
               .agg(**{'Model probability %':('Model probability %','first'),
                        'Model EV %':('Expected ROI % (model)','first'),
                        'Result':('Result','first'),
                        'Paper P/L per £1':('Paper P/L per £1','first')}))
    unique20a=(models20a.groupby(quote_keys20a,dropna=False,as_index=False)
               .agg(Models=('Method','nunique'),
                    Min_probability_pct=('Model probability %','min'),
                    Max_probability_pct=('Model probability %','max'),
                    Min_EV_pct=('Model EV %','min'),
                    Max_EV_pct=('Model EV %','max'),
                    Result=('Result','first'),
                    Paper_PL_per_1=('Paper P/L per £1','first')))
    unique20a['Probability spread (pp)']=(
        unique20a['Max_probability_pct']-unique20a['Min_probability_pct'])
    unique20a['EV spread (pp)']=(
        unique20a['Max_EV_pct']-unique20a['Min_EV_pct'])
    unique20a['Any model positive']=unique20a['Max_EV_pct']>0
    unique20a['All recorded models positive']=unique20a['Min_EV_pct']>0
    unique20a['Models disagree on EV sign']=(
        (unique20a['Min_EV_pct']<=0)&(unique20a['Max_EV_pct']>0))
    unique20a['Odds band']=pd.cut(
        unique20a['Observed odds'],
        bins=[1,2,3,5,10,25,float('inf')],
        labels=['1.01–2.00','2.01–3.00','3.01–5.00',
                '5.01–10.00','10.01–25.00','Over 25'],
        include_lowest=True)
    unique20a['Review category']=np.select(
        [unique20a['Models disagree on EV sign'],
         unique20a['All recorded models positive']],
        ['Conflicting value estimates','All recorded models positive'],
        default='No recorded model positive')
    # This flags only disagreement, never labels a selection safe/profitable.
    st.metric('Distinct quoted selections',len(unique20a))
    st.metric('Quotes with disagreement on value',int(
        unique20a['Models disagree on EV sign'].sum()))
    st.markdown('**Selection-level disagreement (largest first)**')
    st.dataframe(unique20a.sort_values('EV spread (pp)',ascending=False)
                 .round(3),hide_index=True,use_container_width=True)
    st.markdown('**Model-specific probability and expected value**')
    st.dataframe(models20a.round(3),hide_index=True,use_container_width=True)
    by_market20a=(unique20a.groupby('Market',as_index=False)
                  .agg(Unique_quotes=('Observed odds','size'),
                       Disagreements=('Models disagree on EV sign','sum'),
                       Mean_probability_spread_pp=('Probability spread (pp)','mean'),
                       Mean_EV_spread_pp=('EV spread (pp)','mean')))
    st.markdown('**Disagreement by market**')
    st.dataframe(by_market20a.round(3),hide_index=True,
                 use_container_width=True)
    by_odds20a=(unique20a.groupby('Odds band',observed=True,as_index=False)
                .agg(Unique_quotes=('Observed odds','size'),
                     Disagreements=('Models disagree on EV sign','sum'),
                     Mean_EV_spread_pp=('EV spread (pp)','mean')))
    st.markdown('**Disagreement by price band**')
    st.dataframe(by_odds20a.round(3),hide_index=True,
                 use_container_width=True)
    for label20a,data20a,name20a in [
        ('unique quote audit',unique20a,'stage20a_unique_quotes.csv'),
        ('model-level probabilities',models20a,'stage20a_model_details.csv'),
        ('market summary',by_market20a,'stage20a_market_summary.csv'),
        ('odds-band summary',by_odds20a,'stage20a_odds_bands.csv')]:
        st.download_button('Download Stage 20A '+label20a+' CSV',
            data=data20a.to_csv(index=False).encode('utf-8-sig'),
            file_name=name20a,mime='text/csv',
            key='stage20a_'+name20a)
    st.warning('Only two distinct fixtures were recorded in the original '
               'Stage 20 sample. A positive estimate from all recorded '
               'models is not independent confirmation: models can share '
               'training data and errors. The quotes may not be executable, '
               'and multiple markets within a match are correlated. '
               'This audit does not establish profitable betting or '
               'change the live scanner.')


# Stage 20B — retrospective goal-model comparison against actual stored quotes.
# The goal-model estimate is computed now, NOT a saved at-capture prediction.
st.subheader('Stage 20B · Goal model versus captured halftime prices')
st.caption('Retrospective diagnostic only. Recomputes the Stage 19B goal model for '
           'recorded halftime inputs, using historical matches dated strictly before '
           'each quote capture. These probabilities were NOT recorded when the quotes '
           'were captured and must not be counted as prospective predictions.')
if not _records17:
    st.info('No Stage 17 snapshots yet. Future recorded quotes will appear here.')
else:
    _b20_pool = _goal19_pool().copy()
    _b20_pool['_date20b'] = pd.to_datetime(
        _b20_pool['date'] if 'date' in _b20_pool else _b20_pool['Date'],
        errors='coerce', dayfirst=True, utc=True)
    _b20_pool = _b20_pool.dropna(subset=['_date20b'])
    _b20_rows = []
    _b20_skips = []
    for _r20b in _records17:
        _preds20b = _r20b.get('predictions') or []
        _priced20b = []
        for _p20b in _preds20b:
            try:
                _od20b = float(_p20b.get('live_odds'))
            except (TypeError, ValueError):
                continue
            if math.isfinite(_od20b) and _od20b > 1:
                _priced20b.append((_p20b, _od20b))
        if not _priced20b:
            continue
        _match20b = str(_r20b.get('match', 'Unknown match'))
        try:
            _cut20b = pd.to_datetime(_r20b['captured_utc'], utc=True)
            _hh20b = int(_r20b['ht_home'])
            _ha20b = int(_r20b['ht_away'])
            _fav20b = float(_r20b['favourite_odds'])
            _hx20b = float(_r20b['xg_home'])
            _ax20b = float(_r20b['xg_away'])
            if not all(math.isfinite(v) for v in (_fav20b, _hx20b, _ax20b)):
                raise ValueError('Non-finite inputs')
        except (ValueError, TypeError, KeyError, OverflowError):
            _b20_skips.append({'Match': _match20b, 'Reason': 'Missing or invalid recorded halftime inputs'})
            continue
        # Exclude same-day matches, to avoid accidentally training on results
        # that were not yet known at halftime.
        _train20b = _b20_pool[_b20_pool['_date20b'] < _cut20b.normalize()]
        _fit20b = _goal19_estimate(_train20b, _hh20b, _ha20b,
                                   _fav20b, _hx20b, _ax20b)
        if _fit20b is None:
            _b20_skips.append({'Match': _match20b, 'Reason': 'Insufficient earlier training data'})
            continue
        _pmap20b = _goal19_probs(_fit20b[0], _fit20b[1], _hh20b, _ha20b)
        for _pr20b, _od20b in _priced20b:
            _market20b = _pr20b.get('market')
            if _market20b not in _pmap20b:
                _b20_skips.append({'Match': _match20b, 'Reason': 'Unsupported market: ' + str(_market20b)})
                continue
            _book20b = str(_pr20b.get('live_bookmaker') or 'Unknown')
            _gp20b = _pmap20b[_market20b]
            _net20b = (_od20b - 1) * (1 - commission if _book20b == 'Betfair Exchange' else 1)
            _oldp20b = _pr20b.get('probability')
            try:
                _oldp20b = float(_oldp20b)
            except (ValueError, TypeError):
                _oldp20b = float('nan')
            _settled20b = (_r20b.get('status') == 'settled' and
                           _r20b.get('ft_home') is not None and
                           _r20b.get('ft_away') is not None)
            _result20b = 'Pending'
            _pl20b = None
            if _settled20b:
                _fh20b, _fa20b = int(_r20b['ft_home']), int(_r20b['ft_away'])
                _dh20b, _da20b = _fh20b - _hh20b, _fa20b - _ha20b
                _truth20b = {
                    'Home full-time win': _fh20b > _fa20b,
                    'Draw full-time': _fh20b == _fa20b,
                    'Away full-time win': _fh20b < _fa20b,
                    'Home scores in 2H': _dh20b >= 1,
                    'Away scores in 2H': _da20b >= 1,
                    'Home wins 2H': _dh20b > _da20b,
                    'Draw 2H': _dh20b == _da20b,
                    'Away wins 2H': _dh20b < _da20b,
                    'Over 0.5 goals 2H': _dh20b + _da20b >= 1,
                    'Over 1.5 goals 2H': _dh20b + _da20b >= 2,
                    'Over 2.5 goals 2H': _dh20b + _da20b >= 3,
                }
                if _market20b in _truth20b:
                    _won20b = _truth20b[_market20b]
                    _result20b = 'Won' if _won20b else 'Lost'
                    _pl20b = _net20b if _won20b else -1.0
            _b20_rows.append({
                'Match': _match20b, 'Captured UTC': _r20b.get('captured_utc'),
                'Odds captured UTC': _r20b.get('live_odds_captured_utc'),
                'Market': _market20b, 'Bookmaker': _book20b,
                'Observed odds': _od20b, 'Recorded method': _pr20b.get('method'),
                'Recorded probability %': round(_oldp20b * 100, 3),
                'Retrospective goal probability %': round(_gp20b * 100, 3),
                'Recorded model EV %': round(100 * (_oldp20b * (1 + _net20b) - 1), 2),
                'Retrospective goal EV %': round(100 * (_gp20b * (1 + _net20b) - 1), 2),
                'Goal model positive EV': _gp20b * (1 + _net20b) > 1,
                'Recorded model positive EV': _oldp20b * (1 + _net20b) > 1,
                'Goal-model effective neighbours': round(_fit20b[2], 1),
                'Earlier training matches': len(_train20b),
                'Result': _result20b, 'Paper P/L per £1': _pl20b,
                'Assessment type': 'Retrospective; not captured at halftime',
            })
    if not _b20_rows:
        st.info('No eligible recorded quotes could be compared with the goal model.')
    else:
        _b20_df = pd.DataFrame(_b20_rows)
        _b20_keys = ['Match', 'Captured UTC', 'Odds captured UTC', 'Market',
                     'Bookmaker', 'Observed odds']
        _b20_unique = (_b20_df.groupby(_b20_keys, dropna=False, as_index=False)
                       .agg(Goal_probability_pct=('Retrospective goal probability %', 'first'),
                            Goal_EV_pct=('Retrospective goal EV %', 'first'),
                            Goal_positive=('Goal model positive EV', 'first'),
                            Recorded_any_positive=('Recorded model positive EV', 'any'),
                            Recorded_all_positive=('Recorded model positive EV', 'all'),
                            Recorded_models=('Recorded method', 'nunique'),
                            Result=('Result', 'first'),
                            Paper_PL_per_1=('Paper P/L per £1', 'first')))
        _b20_unique['Goal versus recorded any disagreement'] = (
            _b20_unique['Goal_positive'] != _b20_unique['Recorded_any_positive'])
        _b20_unique['Goal versus recorded all disagreement'] = (
            _b20_unique['Goal_positive'] != _b20_unique['Recorded_all_positive'])
        _c20b1, _c20b2, _c20b3 = st.columns(3)
        _c20b1.metric('Unique compared quotes', len(_b20_unique))
        _c20b2.metric('Goal-model positive EV', int(_b20_unique['Goal_positive'].sum()))
        _c20b3.metric('Disagree with recorded all-model rule',
                       int(_b20_unique['Goal versus recorded all disagreement'].sum()))
        st.markdown('**One row per actual bookmaker quote**')
        st.dataframe(_b20_unique, hide_index=True, use_container_width=True)
        st.markdown('**Goal model compared with each recorded model**')
        st.dataframe(_b20_df, hide_index=True, use_container_width=True)
        st.download_button('Download Stage 20B unique quote CSV',
            _b20_unique.to_csv(index=False).encode('utf-8-sig'),
            file_name='stage20b_unique_quotes.csv', mime='text/csv', key='dl20b_unique')
        st.download_button('Download Stage 20B model comparison CSV',
            _b20_df.to_csv(index=False).encode('utf-8-sig'),
            file_name='stage20b_model_comparison.csv', mime='text/csv', key='dl20b_models')
    if _b20_skips:
        st.caption(f'{len(_b20_skips)} snapshot/market exclusions; inspect the exclusions CSV.')
        st.download_button('Download Stage 20B exclusions CSV',
            pd.DataFrame(_b20_skips).to_csv(index=False).encode('utf-8-sig'),
            file_name='stage20b_exclusions.csv', mime='text/csv', key='dl20b_exclusions')
    st.warning('Stage 20B is a retrospective diagnostic, NOT an out-of-sample '
               'prospective quote test. It does not modify the GitHub worker, '
               'historical journal, live scanner, model selections or betting. '
               'Recorded prices may be delayed or non-executable. Two matches '
               'cannot establish a profitable strategy. For a genuine forward '
               'test, the worker must save the goal-model probability at halftime.')


# Stage 20C — only predictions saved by the scheduled worker at halftime.
st.subheader('Stage 20C · Prospective goal-model and recorded quote validation')
st.caption('Only predictions timestamped and saved at halftime by the Stage 20C worker are included. '
           'Earlier Stage 17/18/20B matches are never backfilled. Odds may be delayed or unexecutable.')
_c20_rows = []
for _rec20c in _records17:
    _ps20c = _rec20c.get('predictions') or []
    _goal20c = [p for p in _ps20c if p.get('method') == 'Goal model (prospective)'
                and p.get('model_version') == '20C-v1']
    if not _goal20c:
        continue
    _is_settled20c = (_rec20c.get('status') == 'settled' and
                      _rec20c.get('ft_home') is not None and _rec20c.get('ft_away') is not None)
    if _is_settled20c:
        _fh20c, _fa20c = int(_rec20c['ft_home']), int(_rec20c['ft_away'])
        _sh20c = _fh20c - int(_rec20c['ht_home'])
        _sa20c = _fa20c - int(_rec20c['ht_away'])
        _truth20c = {'Home full-time win': _fh20c > _fa20c,
                     'Away full-time win': _fh20c < _fa20c,
                     'Home scores in 2H': _sh20c >= 1,
                     'Away scores in 2H': _sa20c >= 1,
                     'Home wins 2H': _sh20c > _sa20c,
                     'Away wins 2H': _sh20c < _sa20c}
    else:
        _truth20c = {}
    for _p20c in _goal20c:
        _market20c = _p20c.get('market')
        _prob20c = float(_p20c['probability'])
        _odds20c = _p20c.get('live_odds')
        try:
            _odds20c = float(_odds20c)
            if not math.isfinite(_odds20c) or _odds20c <= 1:
                _odds20c = None
        except (ValueError, TypeError):
            _odds20c = None
        _book20c = str(_p20c.get('live_bookmaker') or '')
        _net20c = ((_odds20c - 1) * (1 - commission if _book20c == 'Betfair Exchange' else 1)
                   if _odds20c is not None else None)
        _won20c = _truth20c.get(_market20c)
        _pl20c = ((_net20c if _won20c else -1.) if _won20c is not None and _net20c is not None else None)
        _c20_rows.append({'Match ID': _rec20c.get('match_id'), 'Match': _rec20c.get('match'),
            'Captured UTC': _rec20c.get('captured_utc'),
            'Odds captured UTC': _rec20c.get('live_odds_captured_utc'),
            'Market': _market20c, 'Method': 'Goal model (prospective)',
            'Probability %': round(100 * _prob20c, 3),
            'Bookmaker': _book20c, 'Observed odds': _odds20c,
            'Expected ROI %': round(100 * (_prob20c * (1 + _net20c) - 1), 2) if _net20c is not None else None,
            'Positive estimated value': (_prob20c * (1 + _net20c) > 1) if _net20c is not None else None,
            'Status': 'Settled' if _is_settled20c else 'Pending',
            'Result': ('Won' if _won20c else 'Lost') if _won20c is not None else 'Pending',
            'Paper P/L per £1': _pl20c,
            'Training cutoff exclusive UTC': _p20c.get('training_cutoff_exclusive_utc'),
            'Model version': _p20c.get('model_version')})
if not _c20_rows:
    st.info('No Stage 20C prospective goal predictions recorded yet. The updated GitHub Actions worker '
            'must capture new halftime fixtures before results appear here.')
else:
    _c20_df = pd.DataFrame(_c20_rows)
    _c20_priced = _c20_df[_c20_df['Observed odds'].notna()].copy()
    _c20_settled = _c20_priced[_c20_priced['Paper P/L per £1'].notna()].copy()
    _c20_pos = _c20_settled[_c20_settled['Positive estimated value'] == True]
    _ca20, _cb20, _cc20 = st.columns(3)
    _ca20.metric('Prospective fixtures', _c20_df['Match ID'].nunique())
    _cb20.metric('Priced predictions', len(_c20_priced))
    _cc20.metric('Settled positive-value quotes', len(_c20_pos))
    if len(_c20_pos):
        st.metric('Positive-value paper ROI (flat £1)',
                  f"{100 * _c20_pos['Paper P/L per £1'].mean():.1f}%")
    st.dataframe(_c20_df.sort_values('Captured UTC', ascending=False),
                 hide_index=True, use_container_width=True)
    st.download_button('Download Stage 20C prospective prediction CSV',
                       _c20_df.to_csv(index=False).encode('utf-8-sig'),
                       'stage20c_prospective_predictions.csv', 'text/csv', key='stage20c_predictions')
    if not _c20_priced.empty:
        st.download_button('Download Stage 20C genuine recorded quote CSV',
                           _c20_priced.to_csv(index=False).encode('utf-8-sig'),
                           'stage20c_priced_predictions.csv', 'text/csv', key='stage20c_priced')
    st.caption('These are paper observations, not executable fills. Compare identical markets and fixtures '
               'across models; a positive expected return is not a verified betting edge.')


# Stage 20D: point-in-time verification of the exact Stage 20C worker goal model.
st.subheader('Stage 20D · Historical verification of prospective goal model')
st.caption('Runs the same goal-model function used by the Stage 20C GitHub worker on later, already-finished matches. '
           'Training uses strictly earlier calendar dates. This is a historical accuracy test, not prospective evidence or a bookmaker-profit test.')

@st.cache_data(show_spinner=False)
def _stage20d_verify(test_limit):
    from stage17_worker import prospective_goal_predictions
    from stage17_core import load_history
    history = load_history(DATA)
    date_col = 'date' if 'date' in history.columns else 'Date' if 'Date' in history.columns else None
    if date_col is None:
        return None, None, 'No date/Date column found in historical data.'
    history = history.copy()
    history['_audit_date'] = pd.to_datetime(history[date_col], errors='coerce', dayfirst=True, utc=True)
    history = history[history['_audit_date'].notna() & history['fav'].between(1.01,20)].copy()
    history = history.sort_values('_audit_date', kind='stable').reset_index(drop=True)
    if len(history) < 500:
        return None, None, 'Insufficient dated historical matches.'
    # Only evaluate the latest 20% of the dated sample; no random future data.
    split = int(len(history) * .80)
    test = history.iloc[split:].copy()
    if len(test) > test_limit:
        # Evenly spaced deterministic sample across the later period.
        import numpy as np
        test = test.iloc[np.linspace(0,len(test)-1,test_limit,dtype=int)].copy()
    rows = []
    for ix, match in test.iterrows():
        match_day = match['_audit_date'].normalize()
        try:
            forecasts = prospective_goal_predictions(history, match_day.isoformat(),
                int(match['HTHG']), int(match['HTAG']), float(match['fav']),
                float(match['ht_xg_home_final']), float(match['ht_xg_away_final']))
        except (ValueError,TypeError,KeyError,OverflowError,ZeroDivisionError):
            continue
        h2 = int(match['FTHG'] - match['HTHG'])
        a2 = int(match['FTAG'] - match['HTAG'])
        actual = {
            'Home full-time win': int(match['FTHG'] > match['FTAG']),
            'Away full-time win': int(match['FTHG'] < match['FTAG']),
            'Home scores in 2H': int(h2 >= 1),
            'Away scores in 2H': int(a2 >= 1),
            'Home wins 2H': int(h2 > a2),
            'Away wins 2H': int(h2 < a2),
        }
        for f in forecasts:
            p = float(f['probability'])
            y = actual[f['market']]
            rows.append({'Fixture row': int(ix), 'Fixture date UTC': match_day.date().isoformat(),
                'HT score': f"{int(match['HTHG'])}-{int(match['HTAG'])}",
                'FT score': f"{int(match['FTHG'])}-{int(match['FTAG'])}",
                'Market': f['market'], 'Goal probability': p, 'Actual': y,
                'Brier': (p-y)**2, 'Log loss': -(y*math.log(max(p,1e-12)) + (1-y)*math.log(max(1-p,1e-12))),
                'Training matches': f['sample'], 'Effective neighbours': f['ess'],
                'Training cutoff exclusive UTC': f['training_cutoff_exclusive_utc'],
                'Model version': f['model_version']})
    if not rows:
        return None,None,'No historical predictions generated by the Stage 20C model.'
    detail = pd.DataFrame(rows)
    # A constant-prior baseline learned from the earlier 80% only.
    train = history.iloc[:split]
    sh = train['FTHG'] - train['HTHG']; sa = train['FTAG'] - train['HTAG']
    base = {'Home full-time win': float((train['FTHG']>train['FTAG']).mean()),
            'Away full-time win': float((train['FTHG']<train['FTAG']).mean()),
            'Home scores in 2H': float((sh>=1).mean()),
            'Away scores in 2H': float((sa>=1).mean()),
            'Home wins 2H': float((sh>sa).mean()),
            'Away wins 2H': float((sh<sa).mean())}
    detail['Baseline probability'] = detail['Market'].map(base)
    detail['Baseline Brier'] = (detail['Baseline probability']-detail['Actual'])**2
    summary = detail.groupby('Market',as_index=False).agg(
        Predictions=('Actual','size'), Actual_rate=('Actual','mean'),
        Mean_forecast=('Goal probability','mean'), Goal_Brier=('Brier','mean'),
        Baseline_Brier=('Baseline Brier','mean'), Goal_log_loss=('Log loss','mean'))
    summary['Brier improvement vs baseline'] = summary['Baseline_Brier']-summary['Goal_Brier']
    return detail,summary,None

st.caption('This experiment is deliberately capped for Streamlit performance. A run is cached for repeat viewing.')
_stage20d_limit = st.select_slider('Historical fixtures to verify', options=[100,250,500,1000], value=500, key='stage20d_limit')
if st.button('Run Stage 20D chronological verification', key='stage20d_run'):
    with st.spinner('Replaying historical halftime scenarios with strictly earlier training dates…'):
        _d20_detail, _d20_summary, _d20_error = _stage20d_verify(_stage20d_limit)
    if _d20_error:
        st.warning(_d20_error)
    else:
        _n20 = _d20_detail['Fixture row'].nunique()
        _b20 = _d20_detail['Brier'].mean()
        _baseline20 = _d20_detail['Baseline Brier'].mean()
        _m1,_m2,_m3 = st.columns(3)
        _m1.metric('Historical fixtures tested',f'{_n20:,}')
        _m2.metric('Goal-model Brier (lower better)',f'{_b20:.4f}')
        _m3.metric('Earlier-period baseline Brier',f'{_baseline20:.4f}')
        st.dataframe(_d20_summary.round(4), hide_index=True, use_container_width=True)
        st.download_button('Download Stage 20D market accuracy CSV',
            _d20_summary.to_csv(index=False).encode('utf-8-sig'),
            'stage20d_market_accuracy.csv','text/csv',key='stage20d_summary_dl')
        st.download_button('Download Stage 20D individual predictions CSV',
            _d20_detail.to_csv(index=False).encode('utf-8-sig'),
            'stage20d_historical_predictions.csv','text/csv',key='stage20d_detail_dl')
        st.caption('The earlier-period constant-rate baseline is deliberately simple, not a bookmaker or advanced-model benchmark. '
                   'The worker goal model itself is reused without refitting to future results. '
                   'The historical CSV contains finalized halftime xG and historical opening odds, which may not exactly match what was available live. '
                   'These limitations prevent treating the result as verified betting profitability.')
