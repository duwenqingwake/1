from pathlib import Path
import socket, threading
import pandas as pd
import baostock as bs
LOCK=threading.Lock()
def load_api(code,start,end,slow):
    market='sh.' if code.startswith('6') else 'sz.'
    if not code.startswith(('6','0','3')): raise ValueError('当前支持沪深 A 股代码')
    begin=(pd.Timestamp(start)-pd.Timedelta(days=max(400,slow*3))).strftime('%Y-%m-%d')
    def query(symbol,fields,first,flag):
        r=bs.query_history_k_data_plus(symbol,fields,start_date=first,end_date=end,frequency='d',adjustflag=flag)
        if r.error_code!='0': raise RuntimeError(r.error_msg)
        d=r.get_data()
        if r.error_code!='0' or d.empty: raise ValueError('API 无有效数据: '+symbol+' '+r.error_msg)
        d=d.rename(columns={'date':'trade_date'});d['trade_date']=pd.to_datetime(d.trade_date)
        if d.trade_date.duplicated().any(): raise ValueError('API 返回重复日期')
        for c in d.columns:
            if c not in ['trade_date','code']: d[c]=pd.to_numeric(d[c],errors='coerce')
        return d
    with LOCK:
        socket.setdefaulttimeout(25)
        login=bs.login()
        if login.error_code!='0': raise RuntimeError('BaoStock 登录失败: '+login.error_msg)
        try:
            bars=query(market+code,'date,open,high,low,close,preclose,volume,tradestatus,isST',begin,'3')
            adj=query(market+code,'date,close',begin,'1').rename(columns={'close':'adjusted_close'})
            bars=bars.merge(adj,on='trade_date',how='left',validate='one_to_one')
            bars['back_factor']=bars.adjusted_close/bars.close
            if bars.back_factor.isna().any() or (bars.back_factor<=0).any(): raise ValueError('复权数据缺失或无效')
            bench=query('sh.000300','date,close',start,'3')
            if bars.trade_date.max()<bench.trade_date.max(): raise ValueError('股票行情未覆盖基准结束日期')
            return bars,bench,code
        finally: bs.logout()
