import math
from pathlib import Path
import pandas as pd
import streamlit as st

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
# LIVE FOOTBALL FIXTURES
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

st.divider()
st.header("⚽ Today's Football Fixtures")

@st.cache_data(ttl=900)
def get_live_fixtures(api_key, match_date):
    response = requests.get(
        "https://v3.football.api-sports.io/fixtures",
        headers={"x-apisports-key": api_key},
        params={"date": match_date, "timezone": "Europe/London"},
        timeout=15
    )
    response.raise_for_status()
    return response.json()

if "API_FOOTBALL_KEY" in st.secrets:
    try:
        today = datetime.now(
            ZoneInfo("Europe/London")
        ).date().isoformat()

        data = get_live_fixtures(
            st.secrets["API_FOOTBALL_KEY"], today
        )

        if data.get("errors"):
            st.error(f"API error: {data['errors']}")
        elif data.get("response"):
            for match in data["response"]:
                home = match["teams"]["home"]["name"]
                away = match["teams"]["away"]["name"]
                goals = match["goals"]
                status = match["fixture"]["status"]["short"]

                home_goals = goals["home"]
                away_goals = goals["away"]

                if home_goals is None:
                    home_goals = "-"
                if away_goals is None:
                    away_goals = "-"

                st.write(
                    f"{home} {home_goals} - "
                    f"{away_goals} {away} ({status})"
                )
        else:
            st.info("No fixtures returned for today.")

    except Exception as e:
        st.error(f"Unable to load fixtures: {e}")
else:
    st.warning("API-Football key not configured.")
