import math
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
            "Match": item["Match"], "HT score": item["HT score"],
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
