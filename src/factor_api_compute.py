from pathlib import Path
import json, uuid
from factor_api_data import load_factor_data
import numpy as np
import pandas as pd

from app_paths import WORK
OUT=WORK/'因子结果'
COMMISSION=0.0000854
STAMP=0.001

def compute(start='2023-01-01',end='2026-09-24',period=5,selection='Alpha191 五因子组合',progress=lambda s:None):
    start=pd.Timestamp(start);end=pd.Timestamp(end)
    if start>=end or start<pd.Timestamp('2011-01-01') or end>pd.Timestamp('2026-09-24') or not 1<=period<=60:raise ValueError('日期或调仓周期无效。')
    x,days=load_factor_data(start,end,progress)
    eligible=[i for i,d in enumerate(days) if d>=start and i>=30]
    indices=[i for i in eligible[::period] if i+period+1<len(days)]
    if not indices:raise ValueError('区间不足一个完整调仓周期')
    benchmark=pd.DataFrame()
    x=x.sort_values(['security_id','trade_date']).reset_index(drop=True)
    x['trade_date']=pd.to_datetime(x.trade_date);x['ok']=(x.tradestatus==1)&(x.volume>0)&(x.isST==0)&(x.back_factor>0)
    for col in ['open','high','low','close']:x[col]=x[col]*x.back_factor
    x['vwap']=x.amount/x.volume.replace(0,np.nan)*x.back_factor
    for col in ['open','high','low','close','volume','vwap']:x.loc[~x.ok,col]=np.nan
    def rolling(col,n,method='mean'):
        return x.groupby('security_id',sort=False)[col].transform(lambda s:getattr(s.rolling(n,min_periods=n),method)())
    def rank(col): return x.groupby('trade_date',sort=False)[col].rank(pct=True)
    def corr(a,b,n):
        x['_a']=a;x['_b']=b;x['_ab']=a*b;x['_a2']=a*a;x['_b2']=b*b
        ma=rolling('_a',n);mb=rolling('_b',n);den=np.sqrt((rolling('_a2',n)-ma*ma).clip(lower=0)*(rolling('_b2',n)-mb*mb).clip(lower=0))
        return ((rolling('_ab',n)-ma*mb)/den.replace(0,np.nan)).clip(-1,1)
    g=x.groupby('security_id',sort=False)
    x['logvol']=np.log(x.volume);x['dv1']=g.logvol.diff();x['intraday']=(x.close-x.open)/x.open
    x['alpha1']=-corr(rank('dv1'),rank('intraday'),6)
    # Time-series rank: most recent observation's rank in each 5-day window.
    for col in ['volume','high']:
        x['ts_'+col]=x.groupby('security_id',sort=False)[col].transform(lambda s:s.rolling(5,min_periods=5).apply(lambda z:((z<z[-1]).sum()+((z==z[-1]).sum()+1)/2)/len(z),raw=True))
    x['corr5']=corr(x.ts_volume,x.ts_high,5);x['alpha5']=-rolling('corr5',3,'max')
    x['spread']=x.vwap-x.close;x['spreadmax']=rolling('spread',3,'max');x['spreadmin']=rolling('spread',3,'min');x['dv3']=g.volume.diff(3)
    x['alpha7']=(rank('spreadmax')+rank('spreadmin'))*rank('dv3')
    x['rangevol']=((2*x.close-x.low-x.high)/(x.high-x.low).replace(0,np.nan))*x.volume;x['alpha11']=rolling('rangevol',6,'sum')
    x['vwma10']=rolling('vwap',10);x['gapopen']=x.open-x.vwma10;x['gapclose']=(x.close-x.vwap).abs()
    x['alpha12']=rank('gapopen')*(-rank('gapclose'))
    names=['alpha1','alpha5','alpha7','alpha11','alpha12']
    if selection=='20日动量':
        x['momentum20']=x.close/x.groupby('security_id').close.shift(20)-1
        names=['momentum20']
    # Winsorize at 1/99% and z-score cross-section for each signal date.
    x=x[x.trade_date.isin([days[i] for i in indices]+[days[i+1] for i in indices]+[days[i+period+1] for i in indices])].copy()
    signals=[];sample=[]
    for i in indices:
        dt,buyday,sellday=days[i],days[i+1],days[i+period+1]
        z=x[(x.trade_date==dt)&x.ok].set_index('security_id').copy().dropna(subset=names)
        if len(z)<50:continue
        for k in names:
            v=z[k].clip(z[k].quantile(.01),z[k].quantile(.99));sd=v.std(ddof=0);z[k+'_z']=(v-v.mean())/sd if sd>0 else np.nan
        z['factor']=z[[k+'_z' for k in names]].mean(axis=1,skipna=False);z=z.dropna(subset=['factor']);z['group']=pd.qcut(z.factor.rank(method='first'),5,labels=False)+1
        for day,prefix in [(buyday,'buy'),(sellday,'sell')]:
            t=x[x.trade_date==day].set_index('security_id');z=z.join(t[['open','high','low','ok']].rename(columns={v:prefix+'_'+v for v in ['open','high','low','ok']}))
        available=(z.buy_ok==True)&(z.sell_ok==True)&(z.buy_open>0)&(z.sell_open>0)&(z.buy_high>z.buy_low)&(z.sell_high>z.sell_low)
        z['ret']=np.where(available,z.sell_open/z.buy_open*(1-.003)/(1+.003)-1,np.nan)
        v=z.dropna(subset=['ret']);row={'信号日':dt.strftime('%Y-%m-%d'),'买入日':buyday.strftime('%Y-%m-%d'),'卖出日':sellday.strftime('%Y-%m-%d'),'信号股票数':len(z),'可计算股票数':len(v),'RankIC':v.factor.rank().corr(v.ret.rank()) if len(v)>5 else np.nan}
        for name in names:row[name+'_RankIC']=v[name].rank().corr(v.ret.rank()) if len(v)>5 else np.nan
        for k in range(1,6):row['第%d组'%k]=v.loc[v.group==k,'ret'].mean()
        top=z[z.factor.rank(pct=True)>0.9];topvalid=top.dropna(subset=['ret'])
        raw=topvalid.sell_open/topvalid.buy_open
        row['前10%比赛成本代理收益']=(raw*(1-.003)/(1+.003)-1).mean()
        row['前10%可计算数']=len(topvalid);row['前10%信号数']=len(top)
        if len(benchmark):
            bm=benchmark.set_index(pd.to_datetime(benchmark.trade_date))['open'];row['中证全指收益']=float(bm.loc[sellday]/bm.loc[buyday]-1) if buyday in bm.index and sellday in bm.index else np.nan
        signals.append(row);sample.append({'信号日':row['信号日'],'剔除数':len(z)-len(v),'覆盖率':len(v)/len(z)})
    df=pd.DataFrame(signals)
    if df.empty:raise ValueError('没有可计算的因子截面，请检查数据范围。')
    OUT.mkdir(parents=True,exist_ok=True);folder=OUT/(pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);folder.mkdir()
    df.to_csv(folder/'每期分组和IC.csv',index=False,encoding='utf-8-sig');pd.DataFrame(sample).to_csv(folder/'缺失统计.csv',index=False,encoding='utf-8-sig')
    stats=[]
    for col,name in [('RankIC','等权组合')]+[(k+'_RankIC',k) for k in names]:
        r=df[col].dropna();std=r.std(ddof=1);stats.append({'因子':name,'有效期数':len(r),'平均RankIC':r.mean(),'IC标准差':std,'ICIR（未年化）':r.mean()/std if std>0 else np.nan,'IC正比例':(r>0).mean() if len(r) else np.nan})
    pd.DataFrame(stats).to_csv(folder/'因子IC统计.csv',index=False,encoding='utf-8-sig')
    combo=stats[0]
    m={'因子':('20日动量' if selection=='20日动量' else 'Alpha191 1、5、7、11、12 等权'),'数据源':'BaoStock API独立缓存，不读旧数据库','开始':str(start.date()),'结束':str(end.date()),'周期':period,'期数':len(df),'平均RankIC':float(df.RankIC.mean()),'ICIR':combo['ICIR（未年化）'],'IC正比例':float((df.RankIC.dropna()>0).mean()),'覆盖率':float(df.可计算股票数.sum()/df.信号股票数.sum()),'单边成本':0.003,'股票池':'沪深主板 非ST','比赛代理成本':'买卖单边各0.3%，每期视为全部换手','备注':'五组均为可计算样本等权，非真实组合。缺失、停牌及一字板样本事后剔除，存在选择偏差；比赛代理收益采用全额换手，非真实调仓。数据库无中证全指时不生成基准。'}
    (folder/'摘要.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8');return folder

if __name__=='__main__':print(compute())
