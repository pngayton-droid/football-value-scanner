"""Stage 17 research predictions. No Streamlit dependency or betting execution."""
import math
import numpy as np
import pandas as pd

MARKETS = ['Home full-time win','Away full-time win','Home scores in 2H','Away scores in 2H','Home wins 2H','Away wins 2H']
XH='ht_xg_home_final'; XA='ht_xg_away_final'

def load_history(path):
    d=pd.read_csv(path,low_memory=False,encoding='utf-8-sig')
    cols=['HTHG','HTAG','FTHG','FTAG','B365H','B365A',XH,XA]
    for c in cols: d[c]=pd.to_numeric(d[c],errors='coerce')
    d=d.dropna(subset=cols).copy()
    d['fav']=d[['B365H','B365A']].min(axis=1)
    return d

def outcomes(df):
    sh=df.FTHG-df.HTHG; sa=df.FTAG-df.HTAG
    return {'Home full-time win':df.FTHG>df.FTAG,'Away full-time win':df.FTHG<df.FTAG,
            'Home scores in 2H':sh>=1,'Away scores in 2H':sa>=1,
            'Home wins 2H':sh>sa,'Away wins 2H':sh<sa}

def predict(history,ht_h,ht_a,odds,xgh,xga,side,k=150):
    """Return per-market method probabilities and evidence; missing methods remain missing."""
    if side not in ('Home','Away'): return []
    pool=history[(history.HTHG==ht_h)&(history.HTAG==ht_a)]
    same=pool[pool.B365H<pool.B365A] if side=='Home' else pool[pool.B365A<pool.B365H]
    methods={}
    for name,src,xw,ow in [('Original',pool,.40,.35),('Same-side fixed',same,.40,.35)]:
        s=src[src.fav.between(max(1.01,odds-ow),odds+ow)&src[XH].between(max(0,xgh-xw),xgh+xw)&src[XA].between(max(0,xga-xw),xga+xw)]
        if len(s)>=30:
            y=outcomes(s); methods[name]=(len(s),float(len(s)),{m:(float(y[m].sum())+1)/(len(s)+2) for m in MARKETS})
    if not same.empty:
        dist=((same.fav.to_numpy(float)-odds)/.35)**2+((same[XH].to_numpy(float)-xgh)/.35)**2+((same[XA].to_numpy(float)-xga)/.35)**2
        ix=np.argsort(dist,kind='stable')[:k]; weights=np.exp(-.5*dist[ix]); sw=weights.sum()
        ess=float(sw**2/(weights@weights)) if sw>0 else 0
        if ess>=30:
            selected=same.iloc[ix]; y=outcomes(selected)
            methods['Weighted same-side']=(len(selected),ess,{m:float(np.average(y[m].to_numpy(float),weights=weights)) for m in MARKETS})
    return [{'method':name,'market':m,'probability':round(probs[m],8),'sample':n,'ess':round(ess,3)}
            for name,(n,ess,probs) in methods.items() for m in MARKETS]
