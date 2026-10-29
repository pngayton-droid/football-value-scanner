import math
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
st.caption("Checks first-page live matches for halftime, xG, opening prices and bookmaker coverage. No automatic betting signals.")
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
    data = api_get(params={"status": "live", "per_page": 100}).get("data") or []
    if not isinstance(data, list):
        raise ValueError("Unexpected live match list")
    return [m for m in data if isinstance(m, dict) and m.get("id")]


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


if st.button("🔍 Run Complete Halftime Scan", key="clean_ht_scan"):
    try:
        matches = live_matches()
        halftime = [m for m in matches if is_halftime(m)]
        st.write(f"Live matches returned: {len(matches)}")
        st.write(f"Halftime matches detected: {len(halftime)}")
        if len(matches) == 100:
            st.warning("Only the first 100 live matches were checked; additional pages may exist.")
        if not halftime:
            st.info("No halftime matches detected in the returned page. Try again during live fixtures.")
            with st.expander("Inspect status labels"):
                for m in matches[:15]:
                    st.write({"Match": match_name(m), "live": m.get("live")})
        else:
            rows = []
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
                    books = bookmaker_names(api_get(f"/{match_id}/odds/live"))
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
                rows.append({
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
                    if item['Comparable matches'] < min_n:
                        st.warning('Insufficient historical sample for the selected minimum.')
                    st.dataframe(estimates, hide_index=True, use_container_width=True)
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
        st.session_state["clean_live_matches"] = live_matches()
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
