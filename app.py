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



# LIVE BOOKMAKER ODDS COMPARISON AND BETFAIR MONITOR

st.divider()
st.header("💷 Live Odds & Betfair Market Monitor")
st.caption(
    "Research only. API quotes may be delayed, stale or suspended. "
    "Displayed liquidity is not guaranteed to be executable."
)

ODDS_BASE = "https://api.thestatsapi.com/api/football/matches"

if "odds_matches" not in st.session_state:
    st.session_state.odds_matches = []

if "odds_payload" not in st.session_state:
    st.session_state.odds_payload = None

if "odds_match_id" not in st.session_state:
    st.session_state.odds_match_id = None


def get_odds_headers():
    return {
        "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
    }


def flatten_market_prices(node, path, bookmaker, rows):
    if not isinstance(node, dict):
        return

    if "live" in node:
        try:
            price = float(node["live"])
        except (TypeError, ValueError):
            return

        if price > 1:
            rows.append({
                "Market": " / ".join(path),
                "Bookmaker": bookmaker,
                "Back price": price
            })
        return

    for key, value in node.items():
        flatten_market_prices(
            value,
            path + [str(key)],
            bookmaker,
            rows
        )


def flatten_betfair(node, path, rows):
    if not isinstance(node, dict):
        return

    if (
        "available_to_back" in node
        or "available_to_lay" in node
    ):
        backs = node.get("available_to_back") or []
        lays = node.get("available_to_lay") or []

        def best_offer(offers, reverse):
            valid = []

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                try:
                    price = float(offer.get("price"))
                    size = float(offer.get("size"))
                except (TypeError, ValueError):
                    continue

                if price > 1 and size > 0:
                    valid.append((price, size))

            if not valid:
                return None, None

            valid.sort(
                key=lambda item: item[0],
                reverse=reverse
            )
            return valid[0]

        back, back_size = best_offer(backs, True)
        lay, lay_size = best_offer(lays, False)

        spread = (
            round(lay - back, 3)
            if back is not None and lay is not None
            else None
        )

        rows.append({
            "Market": " / ".join(path),
            "Best back": back,
            "Back liquidity": back_size,
            "Best lay": lay,
            "Lay liquidity": lay_size,
            "Spread": spread
        })
        return

    for key, value in node.items():
        flatten_betfair(
            value,
            path + [str(key)],
            rows
        )


if st.button("Find Live Matches", key="find_odds_matches"):
    try:
        response = requests.get(
            ODDS_BASE,
            headers=get_odds_headers(),
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
            st.session_state.odds_payload = None
            st.session_state.odds_match_id = None

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
        home_name = (
            match.get("home_team") or {}
        ).get("name", "Home")

        away_name = (
            match.get("away_team") or {}
        ).get("name", "Away")

        match_id = str(match["id"])

        label = (
            f"{home_name} v {away_name} [{match_id}]"
        )

        match_options[label] = match

    selected_label = st.selectbox(
        "Choose a live match",
        list(match_options.keys()),
        key="odds_match_selection"
    )

    selected_match = match_options[selected_label]
    selected_id = str(selected_match["id"])

    st.write(
        "Live odds available:",
        selected_match.get("live_odds_available")
    )

    if st.button("Load Bookmaker Odds", key="load_bookmaker_odds"):
        try:
            response = requests.get(
                f"{ODDS_BASE}/{selected_id}/odds/live",
                headers=get_odds_headers(),
                timeout=20
            )

            st.write("Odds HTTP:", response.status_code)

            if response.ok:
                st.session_state.odds_payload = response.json()
                st.session_state.odds_match_id = selected_id
            else:
                st.session_state.odds_payload = None
                st.session_state.odds_match_id = None
                st.warning("Odds unavailable for this match.")
                st.code(response.text[:1000])

        except (requests.RequestException, ValueError) as e:
            st.session_state.odds_payload = None
            st.session_state.odds_match_id = None
            st.error(f"Odds request failed: {e}")

    payload = st.session_state.odds_payload

    if (
        payload is not None
        and st.session_state.odds_match_id == selected_id
    ):
        data = payload.get("data") or {}
        bookmakers = data.get("bookmakers") or []

        if not isinstance(bookmakers, list):
            st.error("Unexpected bookmaker response format.")

        elif not bookmakers:
            st.info("No bookmaker prices returned.")

        else:
            names = [
                str(b.get("bookmaker", "Unknown"))
                for b in bookmakers
                if isinstance(b, dict)
            ]

            st.success(
                f"Bookmakers returned: {', '.join(names)}"
            )

            all_rows = []
            betfair_rows = []

            for bookmaker in bookmakers:
                if not isinstance(bookmaker, dict):
                    continue

                name = str(
                    bookmaker.get("bookmaker", "Unknown")
                )
                markets = bookmaker.get("markets") or {}

                flatten_market_prices(
                    markets,
                    [],
                    name,
                    all_rows
                )

                if "betfair exchange" in name.lower():
                    flatten_betfair(
                        markets,
                        [],
                        betfair_rows
                    )

            if all_rows:
                all_df = pd.DataFrame(all_rows)

                best_idx = all_df.groupby(
                    "Market"
                )["Back price"].idxmax()

                best_df = all_df.loc[best_idx].copy()
                best_df = best_df.sort_values("Market")

                st.subheader("🏆 Best Bookmaker Prices")
                st.dataframe(
                    best_df,
                    hide_index=True,
                    use_container_width=True
                )

                with st.expander("All Bookmaker Prices"):
                    st.dataframe(
                        all_df,
                        hide_index=True,
                        use_container_width=True
                    )

            st.divider()
            st.subheader("🟠 Betfair Exchange Monitor")

            if betfair_rows:
                betfair_df = pd.DataFrame(betfair_rows)

                st.success(
                    f"Found {len(betfair_df)} Betfair selections"
                )

                st.dataframe(
                    betfair_df,
                    hide_index=True,
                    use_container_width=True
                )

                st.download_button(
                    "Download Betfair Market Data",
                    betfair_df.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="betfair_market_monitor.csv",
                    mime="text/csv"
                )

                st.caption(
                    "Back and lay prices are separate. "
                    "Liquidity is the size at the displayed quote. "
                    "A missing lay price means no lay offer was "
                    "returned for that selection."
                )

            else:
                st.warning(
                    "No Betfair Exchange order-book data "
                    "returned for this match."
                )

            with st.expander("View Original API Response"):
                st.json(payload)



# AUTOMATIC HALFTIME SCANNER - STAGE 1

st.divider()
st.header("🔎 Automatic Halftime Scanner")

st.caption(
    "Checks live matches for halftime data and bookmaker "
    "coverage. No betting signals are issued until all "
    "required inputs and market definitions are verified."
)

AUTO_BASE = "https://api.thestatsapi.com/api/football/matches"


def auto_headers():
    return {
        "Authorization": f"Bearer {st.secrets['STATS_API_KEY']}"
    }


def auto_get(url, params=None):
    response = requests.get(
        url,
        headers=auto_headers(),
        params=params,
        timeout=20
    )
    response.raise_for_status()
    return response.json()



def auto_halftime(match):
    """
    Detect halftime using the match-list status
    fields confirmed in TheStatsAPI responses.
    """

    live = match.get("live") or {}

    if not isinstance(live, dict):
        live = {}

    values = [
        match.get("status"),
        match.get("status_short"),
        match.get("match_status"),
        live.get("match_status"),
        live.get("status"),
        live.get("status_short"),
        live.get("period"),
        live.get("phase")
    ]

    halftime_statuses = {
        "ht",
        "halftime",
        "half_time",
        "half-time",
        "half time",
        "half_time_break",
        "half-time break"
    }

    return any(
        str(value).strip().lower() in halftime_statuses
        for value in values
        if value is not None
    )




def auto_first_half_xg(payload):
    """
    Extract first-half xG from TheStatsAPI.

    For live cumulative xG, only accept figures
    when the API confirms the match is at halftime.
    """

    data = payload.get("data") or payload

    if not isinstance(data, dict):
        return None, None

    meta = data.get("meta") or {}

    status = str(
        meta.get("match_status")
        or meta.get("period")
        or ""
    ).strip().lower()

    halftime_statuses = {
        "ht",
        "halftime",
        "half_time",
        "half-time",
        "half time"
    }

    # LIVE STATS FORMAT:
    # data.stats.expected_goals.all
    #
    # At halftime, cumulative xG is the
    # first-half total.

    if status in halftime_statuses:
        stats = data.get("stats") or {}

        xg = stats.get("expected_goals") or {}

        all_xg = xg.get("all") or {}

        if isinstance(all_xg, dict):
            try:
                home = float(all_xg["home"])
                away = float(all_xg["away"])

                if (
                    math.isfinite(home)
                    and math.isfinite(away)
                    and home >= 0
                    and away >= 0
                ):
                    return home, away

            except (
                KeyError,
                ValueError,
                TypeError
            ):
                pass

    # ALTERNATIVE FORMAT:
    # Some responses explicitly contain
    # first-half xG.

    candidates = [
        data.get("overview"),
        data.get("statistics"),
        data.get("stats"),
        data
    ]

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        xg = candidate.get("expected_goals")

        if not isinstance(xg, dict):
            continue

        first_half = xg.get("first_half")

        if not isinstance(first_half, dict):
            continue

        try:
            home = float(first_half["home"])
            away = float(first_half["away"])

            if (
                math.isfinite(home)
                and math.isfinite(away)
                and home >= 0
                and away >= 0
            ):
                return home, away

        except (
            KeyError,
            ValueError,
            TypeError
        ):
            continue

    return None, None



def auto_find_xg(match_id):
    errors = []

    for endpoint in ("live-stats", "stats"):
        try:
            payload = auto_get(
                f"{AUTO_BASE}/{match_id}/{endpoint}"
            )

            home_xg, away_xg = auto_first_half_xg(
                payload
            )

            if home_xg is not None:
                return home_xg, away_xg, endpoint

        except (
            requests.RequestException,
            ValueError,
            TypeError
        ) as e:
            errors.append(str(e))

    return None, None, "Unavailable"


def auto_bookmaker_summary(payload):
    data = payload.get("data") or {}
    bookmakers = data.get("bookmakers") or []

    if not isinstance(bookmakers, list):
        return [], 0

    names = []
    selections = 0

    for bookmaker in bookmakers:
        if not isinstance(bookmaker, dict):
            continue

        name = str(
            bookmaker.get("bookmaker", "Unknown")
        )
        names.append(name)

        markets = bookmaker.get("markets") or {}

        if isinstance(markets, dict):
            selections += len(markets)

    return names, selections


if st.button(
    "🔍 Scan All Live Matches",
    key="automatic_halftime_scan"
):
    try:
        payload = auto_get(
            AUTO_BASE,
            params={
                "status": "live",
                "per_page": 100
            }
        )

        matches = payload.get("data") or []

        if not isinstance(matches, list):
            st.error("Unexpected live match response.")

        else:
            st.write(
                f"Live matches returned: {len(matches)}"
            )

            halftime_matches = [
                match for match in matches
                if isinstance(match, dict)
                and match.get("id")
                and auto_halftime(match)
            ]

            st.write(
                f"Halftime matches detected: "
                f"{len(halftime_matches)}"
            )

            if not halftime_matches:
                st.info(
                    "No matches were identified as being "
                    "at halftime. The API may use a different "
                    "status label, so this is not yet proof "
                    "that no matches are at halftime."
                )

                with st.expander(
                    "Inspect live status labels"
                ):
                    for match in matches[:20]:
                        st.write({
                            "match_id": match.get("id"),
                            "status": match.get("status"),
                            "status_short": match.get(
                                "status_short"
                            ),
                            "live": match.get("live")
                        })

            else:
                results = []

                progress = st.progress(0)

                for index, match in enumerate(
                    halftime_matches
                ):
                    match_id = str(match["id"])

                    home = (
                        match.get("home_team") or {}
                    ).get("name", "Home")

                    away = (
                        match.get("away_team") or {}
                    ).get("name", "Away")

                    score = match.get("score") or {}

                    home_goals = score.get("home")
                    away_goals = score.get("away")

                    home_xg, away_xg, xg_source = (
                        auto_find_xg(match_id)
                    )

                    bookmaker_names = []
                    odds_status = "Unavailable"

                    if match.get("live_odds_available"):
                        try:
                            odds_payload = auto_get(
                                f"{AUTO_BASE}/{match_id}"
                                "/odds/live"
                            )

                            bookmaker_names, count = (
                                auto_bookmaker_summary(
                                    odds_payload
                                )
                            )

                            odds_status = (
                                f"{len(bookmaker_names)} "
                                "bookmakers"
                            )

                        except (
                            requests.RequestException,
                            ValueError,
                            TypeError
                        ):
                            odds_status = "Request failed"

                    xg_ready = (
                        home_xg is not None
                        and away_xg is not None
                    )

                    results.append({
                        "Match": f"{home} v {away}",
                        "HT score": (
                            f"{home_goals}-{away_goals}"
                        ),
                        "Home HT xG": home_xg,
                        "Away HT xG": away_xg,
                        "xG source": xg_source,
                        "Odds": odds_status,
                        "Betfair": any(
                            "betfair exchange" in n.lower()
                            for n in bookmaker_names
                        ),
                        "Data status": (
                            "xG and odds found"
                            if xg_ready and bookmaker_names
                            else "Incomplete"
                        )
                    })

                    progress.progress(
                        (index + 1)
                        / len(halftime_matches)
                    )

                report = pd.DataFrame(results)

                st.subheader("Halftime Scan Results")

                st.dataframe(
                    report,
                    hide_index=True,
                    use_container_width=True
                )

                st.download_button(
                    "Download Halftime Scan",
                    report.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="halftime_scan.csv",
                    mime="text/csv"
                )

                st.warning(
                    "Data readiness is not a value signal. "
                    "We still need verified pre-match "
                    "favourite odds, exact halftime scores "
                    "and confirmed bookmaker market "
                    "definitions before running the "
                    "historical value calculations."
                )

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError
    ) as e:
        st.error(f"Automatic scan failed: {e}")

# LIVE XG DIAGNOSTIC TOOL

st.divider()
st.header("🔬 Live xG Diagnostic")

st.caption(
    "Inspect actual live-statistics responses to determine "
    "whether xG is missing or stored in a different format."
)

XG_BASE = "https://api.thestatsapi.com/api/football/matches"

if "xg_diag_matches" not in st.session_state:
    st.session_state.xg_diag_matches = []

if st.button("Find Matches for xG Test", key="xg_diag_find"):
    try:
        response = requests.get(
            XG_BASE,
            headers={
                "Authorization": (
                    f"Bearer {st.secrets['STATS_API_KEY']}"
                )
            },
            params={
                "status": "live",
                "per_page": 100
            },
            timeout=20
        )

        response.raise_for_status()

        matches = response.json().get("data", [])

        if isinstance(matches, list):
            st.session_state.xg_diag_matches = [
                m for m in matches
                if isinstance(m, dict) and m.get("id")
            ]

            st.success(
                f"Found {len(st.session_state.xg_diag_matches)} "
                "live matches"
            )
        else:
            st.error("Unexpected match response.")

    except (requests.RequestException, ValueError) as e:
        st.error(f"Match search failed: {e}")


diag_matches = st.session_state.xg_diag_matches

if diag_matches:
    options = {}

    for match in diag_matches:
        home = (
            match.get("home_team") or {}
        ).get("name", "Home")

        away = (
            match.get("away_team") or {}
        ).get("name", "Away")

        match_id = str(match["id"])

        label = f"{home} v {away} [{match_id}]"
        options[label] = match

    selected_label = st.selectbox(
        "Choose match to inspect",
        list(options.keys()),
        key="xg_diag_selection"
    )

    selected_match = options[selected_label]
    selected_id = str(selected_match["id"])

    st.write(
        "xG available flag:",
        selected_match.get("xg_available")
    )

    st.write(
        "Live match status:",
        selected_match.get("live")
    )

    if st.button(
        "Inspect Live Statistics",
        key="xg_diag_inspect"
    ):
        headers = {
            "Authorization": (
                f"Bearer {st.secrets['STATS_API_KEY']}"
            )
        }

        for endpoint in ("live-stats", "stats"):
            st.subheader(f"Endpoint: {endpoint}")

            try:
                response = requests.get(
                    f"{XG_BASE}/{selected_id}/{endpoint}",
                    headers=headers,
                    timeout=20
                )

                st.write(
                    "HTTP status:",
                    response.status_code
                )

                if response.ok:
                    payload = response.json()

                    home_xg, away_xg = auto_first_half_xg(
                        payload
                    )

                    if home_xg is not None:
                        st.success(
                            f"First-half xG found: "
                            f"Home {home_xg:.2f} | "
                            f"Away {away_xg:.2f}"
                        )
                    else:
                        st.warning(
                            "Our current extractor did not "
                            "find first-half xG."
                        )

                    st.json(payload)

                else:
                    st.code(response.text[:1000])

            except (
                requests.RequestException,
                ValueError,
                TypeError
            ) as e:
                st.error(f"{endpoint} failed: {e}")

# 18-MARKET LIVE ODDS MAPPING TEST

st.divider()
st.header("🎯 18-Market Odds Mapping Test")

st.caption(
    "Checks which historical betting markets can be matched "
    "to actual live bookmaker market definitions. "
    "No value signals are generated here."
)

MAP_BASE = "https://api.thestatsapi.com/api/football/matches"

HISTORICAL_MARKETS_18 = {
    "Home full-time win": ("match_odds", "home"),
    "Draw full-time": ("match_odds", "draw"),
    "Away full-time win": ("match_odds", "away"),
    "Home scores in 2H": (None, None),
    "Away scores in 2H": (None, None),
    "Over 0.5 goals 2H": (None, None),
    "Over 1.5 goals 2H": (None, None),
    "Over 2.5 goals 2H": (None, None),
    "Home wins 2H": ("second_half_result", "home"),
    "Draw 2H": ("second_half_result", "draw"),
    "Away wins 2H": ("second_half_result", "away"),
    "BTTS Yes FT": ("btts", "yes"),
    "Over 1.5 goals FT": ("total_goals", "over_1.5"),
    "Under 1.5 goals FT": ("total_goals", "under_1.5"),
    "Over 2.5 goals FT": ("total_goals", "over_2.5"),
    "Under 2.5 goals FT": ("total_goals", "under_2.5"),
    "Over 3.5 goals FT": ("total_goals", "over_3.5"),
    "Under 3.5 goals FT": ("total_goals", "under_3.5"),
}

def map_request(url, params=None):
    response = requests.get(
        url,
        headers={
            "Authorization": (
                f"Bearer {st.secrets['STATS_API_KEY']}"
            )
        },
        params=params,
        timeout=25
    )
    response.raise_for_status()
    return response.json()


def map_normalize(value):
    return (
        str(value)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
        .strip("_")
    )


def map_find_nodes(obj, path=()):
    """
    Walk through the actual odds response without
    assuming every bookmaker uses the same nesting.
    """
    if isinstance(obj, dict):
        if (
            "available_to_back" in obj
            or "available_to_lay" in obj
            or "live" in obj
        ):
            yield path, obj

        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                yield from map_find_nodes(
                    value, path + (str(key),)
                )

    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from map_find_nodes(
                value, path + (str(index),)
            )


def map_best_back(node):
    offers = node.get("available_to_back") or []

    valid = []

    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue

            try:
                price = float(offer["price"])
                size = float(offer.get("size", 0))

                if (
                    math.isfinite(price)
                    and math.isfinite(size)
                    and price > 1
                    and size > 0
                ):
                    valid.append((price, size))

            except (TypeError, ValueError, KeyError):
                pass

    if valid:
        return max(valid, key=lambda item: item[0])

    return None, None


if "market_map_matches" not in st.session_state:
    st.session_state.market_map_matches = []


if st.button(
    "Find Live Matches for Market Test",
    key="market_map_find"
):
    try:
        payload = map_request(
            MAP_BASE,
            params={"status": "live", "per_page": 100}
        )

        matches = payload.get("data") or []

        if not isinstance(matches, list):
            st.error("Unexpected match list.")
        else:
            st.session_state.market_map_matches = [
                m for m in matches
                if isinstance(m, dict) and m.get("id")
            ]

            st.success(
                f"Found {len(st.session_state.market_map_matches)} "
                "live matches."
            )

    except (
        requests.RequestException,
        ValueError,
        TypeError
    ) as error:
        st.error(f"Could not find matches: {error}")


map_matches = st.session_state.market_map_matches

if map_matches:
    choices = {}

    for match in map_matches:
        home = (
            match.get("home_team") or {}
        ).get("name", "Home")

        away = (
            match.get("away_team") or {}
        ).get("name", "Away")

        match_id = str(match["id"])

        choices[f"{home} v {away} [{match_id}]"] = match

    chosen = st.selectbox(
        "Select a live match",
        list(choices),
        key="market_map_match"
    )

    selected_match = choices[chosen]
    selected_id = str(selected_match["id"])

    if st.button(
        "Check All 18 Markets",
        key="market_map_check"
    ):
        try:
            payload = map_request(
                f"{MAP_BASE}/{selected_id}/odds/live"
            )

            data = payload.get("data") or {}
            bookmakers = data.get("bookmakers") or []

            if not isinstance(bookmakers, list):
                bookmakers = []

            st.write(
                f"Bookmakers returned: {len(bookmakers)}"
            )

            all_rows = []

            for bookmaker in bookmakers:
                if not isinstance(bookmaker, dict):
                    continue

                bookmaker_name = str(
                    bookmaker.get("bookmaker", "Unknown")
                )

                markets = bookmaker.get("markets") or {}

                for path, node in map_find_nodes(markets):
                    if not path:
                        continue

                    market_key = map_normalize(path[0])
                    selection_path = tuple(
                        map_normalize(part)
                        for part in path[1:]
                    )

                    back_price, back_size = map_best_back(node)

                    all_rows.append({
                        "Bookmaker": bookmaker_name,
                        "Market key": market_key,
                        "Selection path": "/".join(
                            selection_path
                        ),
                        "Back price": back_price,
                        "Back size": back_size,
                        "Raw node": node
                    })

            odds_df = pd.DataFrame(all_rows)

            if odds_df.empty:
                st.warning(
                    "No recognisable odds nodes were found. "
                    "Inspect the raw response below."
                )
            else:
                st.subheader("Market Mapping Results")

                results = []

                for historical_name, mapping in (
                    HISTORICAL_MARKETS_18.items()
                ):
                    target_market, target_selection = mapping

                    if target_market is None:
                        results.append({
                            "Historical market": historical_name,
                            "Status": "Needs mapping",
                            "Matching nodes": 0,
                            "Betfair back": None,
                            "Back size": None
                        })
                        continue

                    candidates = odds_df[
                        odds_df["Market key"].eq(
                            target_market
                        )
                    ].copy()

                    candidates = candidates[
                        candidates["Selection path"].eq(
                            target_selection
                        )
                    ]

                    betfair = candidates[
                        candidates["Bookmaker"]
                        .str.lower()
                        .str.contains(
                            "betfair exchange",
                            regex=False,
                            na=False
                        )
                    ]

                    betfair = betfair.dropna(
                        subset=["Back price"]
                    )

                    if not betfair.empty:
                        best = betfair.sort_values(
                            "Back price",
                            ascending=False
                        ).iloc[0]

                        price = best["Back price"]
                        size = best["Back size"]

                    else:
                        price = None
                        size = None

                    results.append({
                        "Historical market": historical_name,
                        "Status": (
                            "Candidate found - verify"
                            if not candidates.empty
                            else "Not found"
                        ),
                        "Matching nodes": len(candidates),
                        "Betfair back": price,
                        "Back size": size
                    })

                result_df = pd.DataFrame(results)

                st.dataframe(
                    result_df,
                    hide_index=True,
                    use_container_width=True
                )

                st.download_button(
                    "Download 18-Market Mapping",
                    result_df.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="18_market_mapping.csv",
                    mime="text/csv",
                    key="market_map_download"
                )

                st.subheader("Available Market Names")

                market_summary = (
                    odds_df.groupby(
                        "Market key",
                        as_index=False
                    )
                    .agg(
                        Selections=("Selection path", "nunique"),
                        Bookmakers=("Bookmaker", "nunique")
                    )
                    .sort_values("Market key")
                )

                st.dataframe(
                    market_summary,
                    hide_index=True,
                    use_container_width=True
                )

                with st.expander(
                    "Inspect all selection paths"
                ):
                    st.dataframe(
                        odds_df[
                            [
                                "Bookmaker",
                                "Market key",
                                "Selection path",
                                "Back price",
                                "Back size"
                            ]
                        ],
                        hide_index=True,
                        use_container_width=True
                    )

                st.download_button(
                    "Download All Odds Paths",
                    odds_df.drop(
                        columns=["Raw node"]
                    ).to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="live_market_paths.csv",
                    mime="text/csv",
                    key="market_paths_download"
                )

            with st.expander(
                "Inspect original API odds response"
            ):
                st.json(payload)

            st.info(
                "These are candidate mappings, not "
                "verified market definitions. "
                "No betting value has been calculated."
            )

        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError
        ) as error:
            st.error(f"Market mapping failed: {error}")

# ALL-BOOKMAKER PRICE COMPARISON - STAGE 1

st.divider()
st.header("🏆 All-Bookmaker Price Comparison")
st.caption(
    "Compares available back prices across bookmakers. "
    "Market mappings are provisional, not betting signals."
)

COMPARE_BASE = "https://api.thestatsapi.com/api/football/matches"

COMPARE_MARKETS = {
    "Home full-time win": ("match_odds", "home"),
    "Draw full-time": ("match_odds", "draw"),
    "Away full-time win": ("match_odds", "away"),
    "Home scores in 2H": (None, None),
    "Away scores in 2H": (None, None),
    "Over 0.5 goals 2H": (None, None),
    "Over 1.5 goals 2H": (None, None),
    "Over 2.5 goals 2H": (None, None),
    "Home wins 2H": ("second_half_result", "home"),
    "Draw 2H": ("second_half_result", "draw"),
    "Away wins 2H": ("second_half_result", "away"),
    "BTTS Yes FT": ("btts", "yes"),
    "Over 1.5 goals FT": ("total_goals", "over_1_5"),
    "Under 1.5 goals FT": ("total_goals", "under_1_5"),
    "Over 2.5 goals FT": ("total_goals", "over_2_5"),
    "Under 2.5 goals FT": ("total_goals", "under_2_5"),
    "Over 3.5 goals FT": ("total_goals", "over_3_5"),
    "Under 3.5 goals FT": ("total_goals", "under_3_5"),
}

def compare_api(url, params=None):
    response = requests.get(
        url,
        headers={
            "Authorization": (
                f"Bearer {st.secrets['STATS_API_KEY']}"
            )
        },
        params=params,
        timeout=25
    )
    response.raise_for_status()
    return response.json()


def compare_normalize(value):
    import re
    return re.sub(
        r"[^a-z0-9]+", "_", str(value).lower()
    ).strip("_")


def compare_number(value):
    try:
        number = float(value)
        if math.isfinite(number) and number > 1:
            return number
    except (ValueError, TypeError):
        pass
    return None


def compare_walk(obj, path=()):
    if isinstance(obj, dict):
        # A selection node may contain live prices
        # and/or Exchange order-book offers.
        if any(
            key in obj
            for key in (
                "live",
                "available_to_back",
                "available_to_lay"
            )
        ):
            yield path, obj

        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                yield from compare_walk(
                    value, path + (str(key),)
                )

    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from compare_walk(
                value, path + (str(index),)
            )


def compare_prices(node, exchange):
    if exchange:
        offers = node.get("available_to_back") or []
        valid = []

        if isinstance(offers, list):
            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                price = compare_number(
                    offer.get("price")
                )

                try:
                    size = float(offer.get("size", 0))
                except (ValueError, TypeError):
                    size = 0

                if (
                    price is not None
                    and math.isfinite(size)
                    and size > 0
                ):
                    valid.append((price, size))

        if valid:
            return max(valid, key=lambda x: x[0])

        # Never substitute a generic live quote
        # for a verified Exchange back offer.
        return None, None

    return compare_number(node.get("live")), None


def compare_collect(payload, commission):
    data = payload.get("data") or {}
    bookmakers = data.get("bookmakers") or []
    rows = []

    for bookmaker in bookmakers:
        if not isinstance(bookmaker, dict):
            continue

        name = str(
            bookmaker.get("bookmaker", "Unknown")
        )
        exchange = "betfair exchange" in name.lower()
        markets = bookmaker.get("markets") or {}

        if not isinstance(markets, dict):
            continue

        for path, node in compare_walk(markets):
            if len(path) < 2:
                continue

            market = compare_normalize(path[0])
            selection = "/".join(
                compare_normalize(p) for p in path[1:]
            )

            price, size = compare_prices(
                node, exchange
            )

            effective = None
            if price is not None:
                effective = (
                    1 + (price - 1) * (1 - commission)
                    if exchange else price
                )

            rows.append({
                "Bookmaker": name,
                "Market": market,
                "Selection": selection,
                "Odds": price,
                "Effective odds": effective,
                "Back size": size,
                "Exchange": exchange
            })

    return pd.DataFrame(rows)


if "compare_matches" not in st.session_state:
    st.session_state.compare_matches = []

if st.button(
    "Find Live Matches",
    key="compare_find_matches"
):
    try:
        payload = compare_api(
            COMPARE_BASE,
            {"status": "live", "per_page": 100}
        )

        matches = payload.get("data") or []

        if isinstance(matches, list):
            st.session_state.compare_matches = [
                m for m in matches
                if isinstance(m, dict) and m.get("id")
            ]
            st.success(
                f"Found {len(st.session_state.compare_matches)} "
                "live matches"
            )
        else:
            st.error("Unexpected match response.")

    except (requests.RequestException, ValueError) as e:
        st.error(f"Match search failed: {e}")


compare_matches = st.session_state.compare_matches

if compare_matches:
    options = {}

    for match in compare_matches:
        home = (
            match.get("home_team") or {}
        ).get("name", "Home")
        away = (
            match.get("away_team") or {}
        ).get("name", "Away")
        match_id = str(match["id"])

        options[f"{home} v {away} [{match_id}]"] = match

    selected_label = st.selectbox(
        "Choose match",
        list(options),
        key="compare_match_select"
    )

    selected_id = str(
        options[selected_label]["id"]
    )

    commission_pct = st.number_input(
        "Betfair Exchange commission (%)",
        min_value=0.0,
        max_value=20.0,
        value=2.0,
        step=0.5,
        key="compare_commission"
    )

    betfair_only = st.checkbox(
        "Show Betfair Exchange only",
        value=False,
        key="compare_betfair_only"
    )

    if st.button(
        "Compare All 18 Markets",
        key="compare_run"
    ):
        try:
            payload = compare_api(
                f"{COMPARE_BASE}/{selected_id}/odds/live"
            )

            odds = compare_collect(
                payload,
                commission_pct / 100
            )

            if odds.empty:
                st.warning(
                    "No price selections were found."
                )

            else:
                st.write(
                    "Bookmakers:",
                    ", ".join(
                        sorted(
                            odds["Bookmaker"].unique()
                        )
                    )
                )

                if betfair_only:
                    odds = odds[
                        odds["Exchange"]
                    ].copy()

                results = []

                for name, mapping in (
                    COMPARE_MARKETS.items()
                ):
                    market, selection = mapping

                    if market is None:
                        results.append({
                            "Historical market": name,
                            "Status": "Needs mapping",
                            "Best bookmaker": None,
                            "Odds": None,
                            "Effective odds": None,
                            "Betfair odds": None,
                            "Back size": None
                        })
                        continue

                    matches = odds[
                        (odds["Market"] == market)
                        & (
                            odds["Selection"]
                            == selection
                        )
                    ].copy()

                    priced = matches.dropna(
                        subset=["Effective odds"]
                    )

                    if priced.empty:
                        results.append({
                            "Historical market": name,
                            "Status": (
                                "Selection found, no back price"
                                if not matches.empty
                                else "No exact match"
                            ),
                            "Best bookmaker": None,
                            "Odds": None,
                            "Effective odds": None,
                            "Betfair odds": None,
                            "Back size": None
                        })
                        continue

                    best = priced.sort_values(
                        "Effective odds",
                        ascending=False
                    ).iloc[0]

                    bf = priced[
                        priced["Exchange"]
                    ]

                    if not bf.empty:
                        bf_best = bf.sort_values(
                            "Effective odds",
                            ascending=False
                        ).iloc[0]
                        bf_odds = bf_best["Odds"]
                        bf_size = bf_best["Back size"]
                    else:
                        bf_odds = None
                        bf_size = None

                    results.append({
                        "Historical market": name,
                        "Status": "Candidate - verify",
                        "Best bookmaker": best["Bookmaker"],
                        "Odds": best["Odds"],
                        "Effective odds": best["Effective odds"],
                        "Betfair odds": bf_odds,
                        "Back size": bf_size
                    })

                result_df = pd.DataFrame(results)

                st.subheader(
                    "18-Market Price Comparison"
                )

                st.dataframe(
                    result_df,
                    hide_index=True,
                    use_container_width=True
                )

                st.download_button(
                    "Download Comparison",
                    result_df.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="bookmaker_comparison.csv",
                    mime="text/csv",
                    key="compare_download"
                )

                st.subheader(
                    "All Available Selection Paths"
                )

                st.dataframe(
                    odds.drop(
                        columns=["Exchange"]
                    ),
                    hide_index=True,
                    use_container_width=True
                )

                st.download_button(
                    "Download Selection Paths",
                    odds.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="bookmaker_paths.csv",
                    mime="text/csv",
                    key="compare_paths_download"
                )

                with st.expander(
                    "Inspect raw bookmaker response"
                ):
                    st.json(payload)

                st.warning(
                    "Candidate mappings are unverified. "
                    "Effective odds assume commission "
                    "only on Exchange winnings. "
                    "Prices may be stale or unavailable "
                    "when placing a bet. No value "
                    "signals are generated."
                )

        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError
        ) as e:
            st.error(
                f"Comparison failed: {e}"
            )

# PRE-MATCH ODDS AVAILABILITY DIAGNOSTIC

st.divider()
st.header("🕒 Pre-Match Odds Diagnostic")

st.caption(
    "Tests whether original pre-kickoff odds can "
    "be retrieved for matches already underway. "
    "Does not treat live odds as pre-match odds."
)

PRE_BASE = "https://api.thestatsapi.com/api/football/matches"

if "prematch_test_matches" not in st.session_state:
    st.session_state.prematch_test_matches = []

if st.button(
    "Find Matches for Pre-Match Test",
    key="prematch_find"
):
    try:
        response = requests.get(
            PRE_BASE,
            headers={
                "Authorization":
                f"Bearer {st.secrets['STATS_API_KEY']}"
            },
            params={
                "status": "live",
                "per_page": 100
            },
            timeout=20
        )

        response.raise_for_status()
        payload = response.json()
        matches = payload.get("data") or []

        if not isinstance(matches, list):
            st.error("Unexpected match response.")
        else:
            st.session_state.prematch_test_matches = [
                m for m in matches
                if isinstance(m, dict) and m.get("id")
            ]

            st.success(
                f"Found {len(st.session_state.prematch_test_matches)} "
                "live matches."
            )

    except (requests.RequestException, ValueError) as e:
        st.error(f"Match search failed: {e}")


pre_matches = st.session_state.prematch_test_matches

if pre_matches:
    pre_options = {}

    for match in pre_matches:
        home = (
            match.get("home_team") or {}
        ).get("name", "Home")

        away = (
            match.get("away_team") or {}
        ).get("name", "Away")

        match_id = str(match["id"])

        label = f"{home} v {away} [{match_id}]"
        pre_options[label] = match

    chosen = st.selectbox(
        "Choose live match",
        list(pre_options),
        key="prematch_choose"
    )

    selected = pre_options[chosen]
    selected_id = str(selected["id"])

    st.write(
        "Current match status:",
        selected.get("live")
    )

    if st.button(
        "Investigate Original Odds",
        key="prematch_investigate"
    ):
        headers = {
            "Authorization":
            f"Bearer {st.secrets['STATS_API_KEY']}"
        }

        # The following endpoints are exploratory.
        # Their availability is not yet confirmed.
        endpoints = [
            ("Match details", f"{PRE_BASE}/{selected_id}"),
            (
                "Possible pre-match odds endpoint",
                f"{PRE_BASE}/{selected_id}/odds/prematch"
            ),
            (
                "Possible general odds endpoint",
                f"{PRE_BASE}/{selected_id}/odds"
            )
        ]

        for label, url in endpoints:
            st.subheader(label)

            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=20
                )

                st.write(
                    "HTTP status:",
                    response.status_code
                )

                if response.ok:
                    try:
                        payload = response.json()
                        st.json(payload)
                    except ValueError:
                        st.code(response.text[:2000])
                else:
                    st.code(response.text[:1000])

            except requests.RequestException as e:
                st.error(f"Request failed: {e}")

        st.warning(
            "These tests do not establish whether "
            "an odds quote is pre-match or in-play. "
            "We must confirm the endpoint definition, "
            "timestamp and market before using it."
        )
