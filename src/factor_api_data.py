from pathlib import Path
import json
import pandas as pd
import baostock as bs
from api_market_data import LOCK
import socket
from app_paths import WORK
CACHE=WORK/'因子API缓存';CACHE.mkdir(parents=True,exist_ok=True)
def fetch(key,fn,empty=False):
    path=CACHE/(key+'.json')
    if path.exists(): return pd.read_json(path,orient='table')
    r=fn()
    if r.error_code!='0': raise RuntimeError(r.error_msg)
    d=r.get_data()
    if r.error_code!='0': raise RuntimeError(r.error_msg)
    if d.empty and not empty: raise ValueError('API返回空数据: '+key)
    tmp=path.with_suffix('.tmp');d.to_json(tmp,orient='table',force_ascii=False);tmp.replace(path)
    return d

def load_factor_data(start,end,progress=lambda s:None):
    start=pd.Timestamp(start);end=pd.Timestamp(end)
    if start>=end or end>pd.Timestamp.today().normalize(): raise ValueError('日期范围无效或结束日期在未来')
    begin=(start-pd.Timedelta(days=100)).strftime('%Y-%m-%d');stop=end.strftime('%Y-%m-%d')
    with LOCK:
        socket.setdefaulttimeout(25);r=bs.login()
        if r.error_code!='0':raise RuntimeError(r.error_msg)
        try:
            cal=fetch('calendar_'+begin+'_'+stop,lambda:bs.query_trade_dates(start_date=begin,end_date=stop))
            days=pd.to_datetime(cal.loc[cal.is_trading_day.astype(str)=='1','calendar_date']).tolist()
            relevant=[d for d in days if d>=start]
            if not relevant:raise ValueError('没有交易日')
            first=max(0,days.index(relevant[0])-30);days=days[first:]
            frames=[]
            for i,day in enumerate(days):
                ds=day.strftime('%Y-%m-%d');progress('全市场日线 %d/%d · %s'%(i+1,len(days),ds))
                d=fetch('daily_'+ds,lambda:bs.query_daily_history_k_AStock(ds))
                d=d[d.code.str.startswith(('sh.60','sz.00'))].copy();frames.append(d)
            x=pd.concat(frames,ignore_index=True).rename(columns={'date':'trade_date','code':'security_id'})
            x['trade_date']=pd.to_datetime(x.trade_date)
            if x.duplicated(['security_id','trade_date']).any():raise ValueError('API行情重复')
            for col in x.columns:
                if col not in ('trade_date','security_id'):x[col]=pd.to_numeric(x[col],errors='coerce')
            pieces=[];groups=list(x.groupby('security_id',sort=True))
            for i,(code,d) in enumerate(groups):
                progress('历史复权 %d/%d · %s'%(i+1,len(groups),code))
                f=fetch('adjust_'+code+'_'+stop,lambda:bs.query_adjust_factor(code=code,start_date='1990-01-01',end_date=stop),empty=True)
                d=d.sort_values('trade_date')
                if f.empty:d['back_factor']=1.0
                else:
                    f=f.rename(columns={'dividOperateDate':'ex_date','backAdjustFactor':'back_factor'})
                    f['ex_date']=pd.to_datetime(f.ex_date);f['back_factor']=pd.to_numeric(f.back_factor,errors='raise')
                    d=pd.merge_asof(d,f[['ex_date','back_factor']].sort_values('ex_date'),left_on='trade_date',right_on='ex_date',direction='backward')
                    d['back_factor']=d.back_factor.fillna(1.0)
                if (d.back_factor<=0).any():raise ValueError('复权因子无效: '+code)
                pieces.append(d)
            progress('行情准备完成，正在计算因子及收益')
            return pd.concat(pieces,ignore_index=True),days
        finally:bs.logout()
