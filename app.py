import math
from pathlib import Path
import pandas as pd
import streamlit as st

import requests
st.set_page_config(page_title='Football Value Scanner',layout='wide')
st.title('Football Value Scanner · Research prototype')
st.caption('Historical comparison only. No live feeds, executable bets or verified real-time odds. Prices are entered manually.')
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
d=d.dropna(subset=['HTHG','HTAG','FTHG','FTAG','B365H','B365A',xg1,xg2]).copy()
d['fav']=d[['B365H','B365A']].min(axis=1)
d=d[(d.HTHG==ht_h)&(d.HTAG==ht_a)&d.fav.between(max(1.01,fav-odds_width),fav+odds_width)&d[xg1].between(max(0,xgh-xg_width),xgh+xg_width)&d[xg2].between(max(0,xga-xg_width),xga+xg_width)]
sh=d.FTHG-d.HTHG;sa=d.FTAG-d.HTAG;total=d.FTHG+d.FTAG
markets={
 'Home full-time win':d.FTHG>d.FTAG,
 'Draw full-time':d.FTHG==d.FTAG,
 'Away full-time win':d.FTHG<d.FTAG,
 'Home scores in 2H':sh>=1,
 'Away scores in 2H':sa>=1,
 'Over 0.5 goals 2H':sh+sa>=1,
 'Over 1.5 goals 2H':sh+sa>=2,
 'Over 2.5 goals 2H':sh+sa>=3,
 'Home wins 2H':sh>sa,
 'Draw 2H':sh==sa,
 'Away wins 2H':sh<sa,
 'BTTS Yes FT':(d.FTHG>=1)&(d.FTAG>=1),
 'Over 1.5 goals FT':total>=2,
 'Under 1.5 goals FT':total<=1,
 'Over 2.5 goals FT':total>=3,
 'Under 2.5 goals FT':total<=2,
 'Over 3.5 goals FT':total>=4,
 'Under 3.5 goals FT':total<=3,
}
st.subheader(f'{home} v {away} · HT {ht_h}–{ht_a}')
a,b,c=st.columns(3)
a.metric('Comparable matches',f'{len(d):,}')
b.metric('Historical data', '32,653 matches')
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





# TheStatsAPI connection test
st.subheader("⚽ TheStatsAPI Connection Test")

if st.button("Test TheStatsAPI"):
    import requests

    url = "https://api.thestatsapi.com/api/football/matches"

    headers = {
        "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
    }

    params = {
        "status": "scheduled",
        "per_page": 5
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=20
        )

        st.write("HTTP status:", response.status_code)

        if response.ok:
            st.success("Connection successful!")
            st.json(response.json())
        else:
            st.error("API request failed")
            st.write(response.text[:1000])

    except requests.RequestException as e:
        st.error(f"Connection error: {e}")


# THESTATSAPI LIVE MATCH DASHBOARD
st.divider()
st.header("⚽ Live Football Dashboard")

if st.button("Refresh Live Matches"):
    try:
        url = "https://api.thestatsapi.com/api/football/matches"

        headers = {
            "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
        }

        response = requests.get(
            url,
            headers=headers,
            params={"status": "live", "per_page": 100},
            timeout=20
        )
        response.raise_for_status()

        payload = response.json()
        matches = payload.get("data", [])

        if not isinstance(matches, list):
            st.error("Unexpected API response format.")

        elif not matches:
            st.info("No live matches found.")

        else:
            st.success(f"Found {len(matches)} live matches")

            for match in matches:
                home = match.get("home_team") or {}
                away = match.get("away_team") or {}
                score = match.get("score") or {}
                live = match.get("live") or {}

                home_name = home.get("name", "Home")
                away_name = away.get("name", "Away")

                home_goals = score.get("home")
                away_goals = score.get("away")

                home_goals = "-" if home_goals is None else home_goals
                away_goals = "-" if away_goals is None else away_goals

                minute = live.get("elapsed_minutes")
                minute_text = f"{minute}'" if minute is not None else "—"

                with st.container(border=True):
                    st.subheader(f"{home_name} v {away_name}")
                    st.write(
                        f"**{home_goals} – {away_goals}** "
                        f"· {minute_text}"
                    )

                    if match.get("xg_available"):
                        st.success("xG available")

                        match_id = match.get("id")

                        if match_id:
                            stats_url = (
                                "https://api.thestatsapi.com"
                                f"/api/football/matches/{match_id}/live-stats"
                            )

                            try:
                                stats_response = requests.get(
                                    stats_url,
                                    headers=headers,
                                    timeout=20
                                )

                                st.write(
                                    "Live stats HTTP:",
                                    stats_response.status_code
                                )

                                if stats_response.ok:
                                    st.json(stats_response.json())
                                else:
                                    st.write(stats_response.text[:500])

                            except requests.RequestException as e:
                                st.error(f"Live stats error: {e}")

                    else:
                        st.caption("xG not available for this match")

    except requests.RequestException as e:
        st.error(f"Unable to load live matches: {e}")

    except (KeyError, ValueError, TypeError) as e:
        st.error(f"Unable to process match data: {e}")


# Test live xG for a specific match
st.subheader("⚽ Live xG Test")

if st.button("Test Live xG"):
    import requests

    match_id = "mt_156097404"
    url = (
        "https://api.thestatsapi.com"
        f"/api/football/matches/{match_id}"
    )

    headers = {
        "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
    }

    try:
        response = requests.get(
            url, headers=headers, timeout=20
        )

        st.write("HTTP status:", response.status_code)

        if response.ok:
            st.json(response.json())
        else:
            st.write(response.text[:1000])

    except requests.RequestException as e:
        st.error(str(e))



st.subheader("Live xG Endpoint Test")

if st.button("Test Live xG", key="live_xg_endpoint_test"):
    match_id = "mt_156097404"
    url = f"https://api.thestatsapi.com/api/football/matches/{match_id}/live-stats"

    headers = {
        "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        st.write("HTTP status:", response.status_code)

        if response.ok:
            st.json(response.json())
        else:
            st.write(response.text[:1000])

    except requests.RequestException as e:
        st.error(str(e))

st.subheader("Historical xG Test")

if st.button("Test Historical xG", key="historical_xg_test"):
    match_id = "mt_156097404"

    url = (
        "https://api.thestatsapi.com"
        f"/api/football/matches/{match_id}/stats"
    )

    headers = {
        "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        st.write("HTTP status:", response.status_code)

        if response.ok:
            st.json(response.json())
        else:
            st.write(response.text[:1000])

    except requests.RequestException as e:
        st.error(f"Historical xG test failed: {e}")



# HISTORICAL STATISTICS COVERAGE TEST

st.divider()
st.header("⚽ Historical Data Coverage Test")

if st.button("Check Historical Data Coverage"):
    import pandas as pd

    base_url = "https://api.thestatsapi.com/api/football/matches"
    headers = {
        "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
    }

    def show_value(value):
        if value is None:
            return "Not available"
        if isinstance(value, dict):
            return str(value)
        return value

    try:
        response = requests.get(
            base_url,
            headers=headers,
            params={
                "status": "finished",
                "per_page": 10
            },
            timeout=20
        )

        st.write("Match search HTTP:", response.status_code)

        if not response.ok:
            st.write(response.text[:1000])

        else:
            matches = response.json().get("data", [])
            results = []

            for match in matches[:10]:
                match_id = match.get("id")

                if not match_id:
                    continue

                home = (match.get("home_team") or {}).get(
                    "name", "Home"
                )
                away = (match.get("away_team") or {}).get(
                    "name", "Away"
                )

                stats_url = f"{base_url}/{match_id}/stats"

                try:
                    stats_response = requests.get(
                        stats_url,
                        headers=headers,
                        timeout=20
                    )

                    if not stats_response.ok:
                        results.append({
                            "Match": f"{home} v {away}",
                            "HTTP": stats_response.status_code,
                            "xG": "Unavailable",
                            "First-half xG": "Unavailable"
                        })
                        continue

                    data = stats_response.json().get("data") or {}
                    overview = data.get("overview") or {}

                    xg = overview.get("expected_goals")

                    first_half_xg = None

                    if isinstance(xg, dict):
                        first_half_xg = xg.get("first_half")

                    results.append({
                        "Match": f"{home} v {away}",
                        "HTTP": stats_response.status_code,
                        "xG": show_value(xg),
                        "First-half xG": show_value(first_half_xg)
                    })

                except requests.RequestException as e:
                    st.warning(f"{match_id}: {e}")

            if results:
                st.dataframe(
                    pd.DataFrame(results),
                    use_container_width=True,
                    hide_index=True
                )

    except requests.RequestException as e:
        st.error(f"Coverage test failed: {e}")


# LIVE BOOKMAKER ODDS COMPARISON

st.divider()
st.header("💷 Live Bookmaker Odds Comparison")
st.caption(
    "API bookmaker quotes may be delayed or unavailable. "
    "Prices are not verified as currently executable."
)

ODDS_BASE = "https://api.thestatsapi.com/api/football/matches"

def odds_headers():
    return {
        "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
    }

if "odds_matches" not in st.session_state:
    st.session_state.odds_matches = []

if st.button("Find Live Matches", key="find_odds_matches"):
    try:
        response = requests.get(
            ODDS_BASE,
            headers=odds_headers(),
            params={"status": "live", "per_page": 100},
            timeout=20
        )
        response.raise_for_status()

        matches = response.json().get("data", [])

        if isinstance(matches, list):
            st.session_state.odds_matches = [
                m for m in matches
                if isinstance(m, dict) and m.get("id")
            ]
            st.success(
                f"Found {len(st.session_state.odds_matches)} live matches"
            )
        else:
            st.error("Unexpected match list format.")

    except (requests.RequestException, ValueError, KeyError) as e:
        st.error(f"Match search failed: {e}")

matches = st.session_state.odds_matches

if matches:
    match_options = {}

    for match in matches:
        home = (match.get("home_team") or {}).get(
            "name", "Home"
        )
        away = (match.get("away_team") or {}).get(
            "name", "Away"
        )
        match_id = str(match["id"])

        label = f"{home} v {away} [{match_id}]"
        match_options[label] = match

    selected_label = st.selectbox(
        "Choose a live match",
        list(match_options.keys()),
        key="odds_match_selection"
    )

    selected_match = match_options[selected_label]
    selected_id = selected_match["id"]

    st.write(
        "Live odds flag:",
        selected_match.get("live_odds_available")
    )

    if st.button("Compare Bookmaker Odds", key="compare_odds"):
        odds_url = f"{ODDS_BASE}/{selected_id}/odds/live"

        try:
            response = requests.get(
                odds_url,
                headers=odds_headers(),
                timeout=20
            )

            st.write("Odds HTTP:", response.status_code)

            if not response.ok:
                st.warning("No live odds returned for this match.")
                st.code(response.text[:1000])

            else:
                payload = response.json()
                data = payload.get("data") or {}
                bookmakers = data.get("bookmakers") or []

                if not isinstance(bookmakers, list):
                    st.error("Unexpected bookmaker response format.")

                elif not bookmakers:
                    st.info("No bookmakers returned.")

                else:
                    names = [
                        str(b.get("bookmaker", "Unknown"))
                        for b in bookmakers
                        if isinstance(b, dict)
                    ]

                    st.success(
                        f"Found {len(names)} bookmaker entries"
                    )
                    st.write("Bookmakers:", ", ".join(names))

                    betfair_entries = [
                        name for name in names
                        if "betfair" in name.lower()
                    ]

                    if betfair_entries:
                        st.success(
                            "Betfair found: "
                            + ", ".join(betfair_entries)
                        )
                    else:
                        st.warning(
                            "Betfair was not returned for this match."
                        )

                    rows = []

                    def collect_prices(node, path, bookmaker):
                        if not isinstance(node, dict):
                            return

                        if "live" in node:
                            try:
                                price = float(node["live"])
                            except (ValueError, TypeError):
                                price = 0

                            if price > 1:
                                rows.append({
                                    "Market / selection": " / ".join(path),
                                    "Bookmaker": bookmaker,
                                    "Price": price
                                })
                            return

                        for key, value in node.items():
                            collect_prices(
                                value,
                                path + [str(key)],
                                bookmaker
                            )

                    for bookmaker_data in bookmakers:
                        if not isinstance(bookmaker_data, dict):
                            continue

                        bookmaker_name = str(
                            bookmaker_data.get(
                                "bookmaker", "Unknown"
                            )
                        )

                        markets_data = (
                            bookmaker_data.get("markets") or {}
                        )

                        collect_prices(
                            markets_data,
                            [],
                            bookmaker_name
                        )

                    if rows:
                        odds_df = pd.DataFrame(rows)

                        st.subheader("All Available Prices")
                        st.dataframe(
                            odds_df,
                            hide_index=True,
                            use_container_width=True
                        )

                        best_idx = odds_df.groupby(
                            "Market / selection"
                        )["Price"].idxmax()

                        best_df = odds_df.loc[best_idx].copy()
                        best_df = best_df.sort_values(
                            "Market / selection"
                        )

                        st.subheader("🏆 Best Bookmaker Prices")
                        st.dataframe(
                            best_df,
                            hide_index=True,
                            use_container_width=True
                        )

                        st.download_button(
                            "Download Best Prices CSV",
                            best_df.to_csv(
                                index=False
                            ).encode("utf-8"),
                            file_name="best_live_odds.csv",
                            mime="text/csv"
                        )

                    else:
                        st.info(
                            "Bookmakers were returned, "
                            "but no valid live prices were found."
                        )

                    with st.expander("View Original API Response"):
                        st.json(payload)

        except (requests.RequestException, ValueError) as e:
            st.error(f"Odds comparison failed: {e}")

    if st.button(
        "Test Betfair Exchange Specifically",
        key="test_betfair_exchange"
    ):
        odds_url = f"{ODDS_BASE}/{selected_id}/odds/live"

        try:
            response = requests.get(
                odds_url,
                headers=odds_headers(),
                params={"bookmaker": "betfair-exchange"},
                timeout=20
            )

            st.write(
                "Betfair-specific HTTP:",
                response.status_code
            )

            if response.ok:
                payload = response.json()
                data = payload.get("data") or {}
                bookmaker_list = data.get("bookmakers") or []

                names = [
                    str(b.get("bookmaker", "Unknown"))
                    for b in bookmaker_list
                    if isinstance(b, dict)
                ]

                st.write("Returned bookmakers:", names)

                if any("betfair" in n.lower() for n in names):
                    st.success("Betfair data returned.")
                else:
                    st.warning(
                        "No Betfair bookmaker identified. "
                        "The API may have ignored the filter."
                    )

                st.json(payload)

            else:
                st.warning(
                    "Betfair-specific request did not succeed."
                )
                st.code(response.text[:1000])

        except (requests.RequestException, ValueError) as e:
            st.error(f"Betfair test failed: {e}")

