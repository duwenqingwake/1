from pathlib import Path
import json, math, threading, traceback, uuid
import tkinter as tk
from tkinter import ttk, messagebox
import sys
from app_paths import WORK
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib

ROOT = WORK
DB = WORK / 'unused.duckdb'
RUNS = ROOT / 'API回测结果'
RUNS.mkdir(parents=True, exist_ok=True)
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei']
matplotlib.rcParams['axes.unicode_minus'] = False

def backtest(code, start, end, capital, strategy, fast, slow, fee, slippage):
    code = code.strip()
    if len(code) != 6 or not code.isdigit(): raise ValueError('股票代码必须是 6 位数字。')
    if start > end or start < '2010-01-04' or end > '2026-09-24': raise ValueError('日期必须在 2010-01-04 至 2026-09-24 内，且开始日期不晚于结束日期。')
    if capital < 1000 or not 1 <= fast < slow <= 250: raise ValueError('资金至少 1000 元，周期须满足 1 ≤ 短周期 < 长周期 ≤ 250。')
    if not 0 <= fee <= .02 or not 0 <= slippage <= .02: raise ValueError('费率和滑点须在 0% 至 2% 之间。')
    from api_market_data import load_api
    bars, bench, name = load_api(code,start,end,slow)
    for x in ['open','high','low','close']: bars['adj_'+x]=bars[x]*bars.back_factor
    valid = (bars.tradestatus == 1) & (bars.volume > 0) & (bars.close > 0)
    close = bars.adj_close.where(valid)
    if strategy == '均线趋势':
        a = close.rolling(fast,min_periods=fast).mean(); b = close.rolling(slow,min_periods=slow).mean()
        bars['enter'] = (a>b)&(a.shift(1)<=b.shift(1))
        bars['exit'] = (a<b)&(a.shift(1)>=b.shift(1))
    else:
        high = bars.adj_high.where(valid).shift(1).rolling(slow,min_periods=slow).max()
        bars['enter'] = (close>high)&(bars.volume>bars.volume.shift(1).rolling(slow,min_periods=slow).mean()*1.5)
        bars['exit'] = close < close.rolling(fast,min_periods=fast).mean()
    bars=bars[bars.trade_date.between(pd.Timestamp(start),pd.Timestamp(end))].copy()
    if bars.empty: raise ValueError('区间内没有可用的复权日线。')
    if pd.Timestamp(bench.trade_date.max()) > bars.trade_date.max():
        raise ValueError('股票数据早于回测结束日就已终止，可能退市或数据缺失；本版本不能可靠处理，请缩短区间。')
    cash=float(capital); units=0.; pending=None; entry=None; rows=[]; trades=[]; notes=[]; last_close=None
    for row in bars.itertuples(index=False):
        date=row.trade_date; day=date.strftime('%Y-%m-%d'); active=row.tradestatus==1 and row.volume>0 and row.open>0 and row.close>0
        factor=float(row.back_factor)
        if active and pending:
            # Only detect completely locked boards; other intraday fills cannot be inferred from daily bars.
            lim=.198 if (code.startswith(('300','301')) and day>='2020-08-24') or code.startswith('688') else .098
            if row.isST==1: lim=.048
            change = row.open / row.preclose - 1 if row.preclose and row.preclose>0 else 0
            locked = abs(row.high-row.low)<1e-8 and ((pending=='buy' and change>=lim) or (pending=='sell' and change<=-lim))
            if pending=='buy' and row.isST==1:
                notes.append([day,'买入取消：当日 ST']); pending=None
            elif locked:
                notes.append([day, '一字涨跌停，委托未成交：'+pending])
                if pending=='buy': pending=None
            elif pending=='buy' and units==0:
                raw=row.open*(1+slippage); quantity=int(cash/(raw*100))*100
                while quantity>0 and quantity*raw+quantity*raw*fee>cash: quantity-=100
                if quantity:
                    value=quantity*raw; cost=value*fee; cash-=value+cost; units=quantity/factor
                    entry={'买入日期':day,'股票':code,'买入价':raw,'买入股数':quantity,'买入金额':value,'买入费用':cost}
                else: notes.append([day,'资金不足一手'])
                pending=None
            elif pending=='sell' and units>0:
                raw=row.open*(1-slippage); shares=units*factor; value=shares*raw; cost=value*fee+value*(.0005 if day>='2023-08-28' else .001)
                cash+=value-cost; profit=(value-cost-entry['买入金额']-entry['买入费用'])/(entry['买入金额']+entry['买入费用'])
                trades.append(dict(entry,卖出日期=day,卖出价=raw,卖出金额=value,卖出费用=cost,收益率=profit)); units=0.;entry=None;pending=None
        if active:
            last_close=float(row.adj_close)
            if units and bool(row.exit): pending='sell'
            elif not units and bool(row.enter): pending='buy'
        value=cash+(units*last_close if units and last_close is not None else 0.)
        rows.append({'日期':day,'净值':value/capital,'资产':value,'现金':cash,'持仓市值':value-cash})
    nav=pd.DataFrame(rows); bench['日期']=pd.to_datetime(bench.trade_date).dt.strftime('%Y-%m-%d')
    nav=nav.merge(bench[['日期','close']],on='日期',how='left')
    if nav.close.isna().any(): raise ValueError('基准日期缺失，无法可靠计算指标。')
    nav['基准']=nav.close/nav.close.iloc[0]; nav['回撤']=nav['净值']/nav['净值'].cummax().clip(lower=1)-1
    r=nav['净值'].pct_change().fillna(nav['净值'].iloc[0]-1); b=nav['基准'].pct_change().fillna(0)
    beta=r.cov(b)/b.var() if b.var()>0 else float('nan'); sd=r.std()
    t=pd.DataFrame(trades); rr=t['收益率'] if len(t) else pd.Series(dtype=float)
    summary={'股票':code+' '+name,'策略':strategy,'区间':str(bars.trade_date.min().date())+' 至 '+str(bars.trade_date.max().date()),'初始资金':capital,'数据源':'BaoStock API（本次联网获取；不读旧库）',
      '策略收益':nav['净值'].iloc[-1]-1,'年化收益':nav['净值'].iloc[-1]**(252/len(nav))-1,
      '基准收益':nav['基准'].iloc[-1]-1,'相对基准':nav['净值'].iloc[-1]/nav['基准'].iloc[-1]-1,
      '最大回撤':-nav['回撤'].min(),'夏普比率':r.mean()/sd*np.sqrt(252) if sd>0 else float('nan'),
      'Alpha':(r.mean()-beta*b.mean())*252 if np.isfinite(beta) else float('nan'),'Beta':beta,
      '交易胜率':float((rr>0).mean()) if len(rr) else float('nan'),'已平仓次数':len(rr),'期末持仓':bool(units)}
    folder=RUNS/(pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);folder.mkdir()
    nav.to_csv(folder/'每日净值.csv',index=False,encoding='utf-8-sig');t.to_csv(folder/'已平仓交易.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(notes,columns=['日期','说明']).to_csv(folder/'执行说明.csv',index=False,encoding='utf-8-sig')
    summary['参数']={'短周期':fast,'长周期':slow,'单边佣金':fee,'单边滑点':slippage,'卖出印花税':'2023-08-28前0.1%，之后0.05%'}
    (folder/'摘要.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return folder

def app(parent=None):
    standalone = parent is None
    if standalone:
        w=tk.Tk();w.title('股票本地回测');w.geometry('1400x900');w.minsize(1100,700)
    else:
        w=ttk.Frame(parent);w.pack(fill='both',expand=True)
    outer=ttk.Panedwindow(w,orient='horizontal');outer.pack(fill='both',expand=True)
    left=ttk.Frame(outer,padding=14);right=ttk.Frame(outer,padding=14);outer.add(left,weight=0);outer.add(right,weight=1)
    ttk.Label(left,text='股票本地回测',font=('Microsoft YaHei',17,'bold')).pack(anchor='w')
    ttk.Label(left,text='BaoStock API · 实时请求日线，不读旧库',foreground='#666').pack(anchor='w',pady=(3,15))
    form=ttk.LabelFrame(left,text='下次回测设置',padding=10);form.pack(fill='x')
    variables={}
    field_labels={}
    fields=[('股票代码','600000'),('开始日期','2023-01-01'),('结束日期','2026-09-24'),('初始资金','100000'),('短周期','5'),('长周期','20'),('单边佣金 %','0.00854'),('单边滑点 %','0.10')]
    for i,(label,default) in enumerate(fields):
        field_labels[label]=ttk.Label(form,text=label);field_labels[label].grid(row=i,column=0,sticky='w',pady=4);v=tk.StringVar(value=default);variables[label]=v;ttk.Entry(form,textvariable=v,width=16).grid(row=i,column=1,padx=6,pady=4)
    ttk.Label(form,text='策略').grid(row=8,column=0,sticky='w');choice=tk.StringVar(value='均线趋势');ttk.Combobox(form,textvariable=choice,values=['均线趋势','放量突破'],state='readonly',width=14).grid(row=8,column=1,pady=4)
    status=tk.StringVar(value='输入股票代码，运行回测。')
    button=ttk.Button(form,text='运行回测');button.grid(row=9,column=0,columnspan=2,sticky='ew',pady=(10,0))
    explanation=ttk.LabelFrame(left,text='所选策略简介',padding=8);explanation.pack(fill='x',pady=(8,0))
    strategy_text=tk.StringVar();ttk.Label(explanation,textvariable=strategy_text,wraplength=220,justify='left').pack(anchor='w')
    def explain(*_):
        fast=variables['短周期'].get().strip() or '短';slow=variables['长周期'].get().strip() or '长'
        if choice.get()=='均线趋势':
            field_labels['短周期'].config(text='短均线（交易日）');field_labels['长周期'].config(text='长均线（交易日）')
            strategy_text.set(f'{fast}日均线上穿{slow}日均线买入，下穿卖出；收盘确认，次日开盘执行。')
        else:
            field_labels['短周期'].config(text='卖出均线（交易日）');field_labels['长周期'].config(text='突破观察（交易日）')
            strategy_text.set(f'收盘突破前{slow}日最高价且成交量超过前{slow}日均量1.5倍买入；收盘跌破{fast}日均线卖出，均在次日开盘执行。')
    choice.trace_add('write',explain);variables['短周期'].trace_add('write',explain);variables['长周期'].trace_add('write',explain);explain()
    ttk.Label(left,text='已保存的回测',font=('Microsoft YaHei',11,'bold')).pack(anchor='w',pady=(16,6))
    listing=tk.Listbox(left,width=29,height=15,exportselection=False);listing.pack(fill='both',expand=True)
    ttk.Label(left,textvariable=status,wraplength=220,foreground='#555').pack(anchor='w',pady=10)
    title=ttk.Label(right,text='选择或运行一项回测',font=('Microsoft YaHei',16,'bold'));title.pack(anchor='w')
    result_info=tk.StringVar(value='当前显示已保存的历史结果；左侧设置用于下次运行。')
    ttk.Label(right,textvariable=result_info,foreground='#666',wraplength=950).pack(anchor='w',pady=4)
    stat=ttk.Frame(right);stat.pack(fill='x',pady=8);labels={}
    keys=['策略收益','年化收益','基准收益','相对基准','最大回撤','夏普比率','Alpha','Beta','交易胜率','已平仓次数']
    for i,k in enumerate(keys):
        box=ttk.Frame(stat,padding=5);box.grid(row=i//5,column=i%5,sticky='w',padx=(0,18));ttk.Label(box,text=k,foreground='#777').pack(anchor='w');v=ttk.Label(box,text='—',font=('Microsoft YaHei',12,'bold'));v.pack(anchor='w');labels[k]=v
    fig=Figure(figsize=(9,4),dpi=100);ax=fig.add_subplot(211);dd=fig.add_subplot(212);canvas=FigureCanvasTkAgg(fig,master=right);canvas.get_tk_widget().pack(fill='both',expand=True)
    ttk.Label(right,text='已平仓交易（完整数据保存在结果目录）',font=('Microsoft YaHei',10,'bold')).pack(anchor='w')
    cols=['买入日期','股票','买入价','买入股数','卖出日期','卖出价','收益率'];tree=ttk.Treeview(right,columns=cols,show='headings',height=6)
    for col in cols:tree.heading(col,text=col);tree.column(col,width=105,anchor='center')
    tree.pack(fill='x')
    ttk.Label(right,text='复权价格模拟公司行为；非真实分红股数账本。一字板仅按日线估计，佣金无最低收费，卖出印花税按2023-08-28分段；滑点、税费为固定假设；期末持仓按收盘估值。',foreground='#666',wraplength=950).pack(anchor='w',pady=5)
    folders=[]
    def refresh():
        folders[:]=sorted([p for p in RUNS.iterdir() if p.is_dir() and (p/'摘要.json').exists()],reverse=True);listing.delete(0,'end')
        for p in folders:
            try:
                s=json.loads((p/'摘要.json').read_text(encoding='utf-8'));listing.insert('end',p.name[:15]+' '+s['股票']+' '+s['策略'])
            except Exception: listing.insert('end',p.name)
    def show(event=None):
        if not listing.curselection():return
        p=folders[listing.curselection()[0]];s=json.loads((p/'摘要.json').read_text(encoding='utf-8'));n=pd.read_csv(p/'每日净值.csv',parse_dates=['日期'])
        title.config(text=s['股票']+' · '+s['策略']+'   '+s['区间'])
        par=s.get('参数',{});fast=par.get('短周期','未知');slow=par.get('长周期','未知')
        result_info.set(f'当前图表：BaoStock API 回测 · {s["策略"]} · 短周期 {fast} 个交易日 / 长周期 {slow} 个交易日 · 蓝线为策略净值，灰线为沪深300；左侧为下次运行设置。')
        for k,v in labels.items():
            val=s.get(k); v.config(text=('—' if val is None or not np.isfinite(val) else (f'{val*100:.2f}%' if k in ['策略收益','年化收益','基准收益','相对基准','最大回撤','交易胜率'] else f'{val:.3f}' if k!='已平仓次数' else str(val))))
        ax.clear();dd.clear();ax.plot(n['日期'],n['净值'],color='#1d5fbf',label='策略');ax.plot(n['日期'],n['基准'],color='#888',label='沪深300');ax.legend();ax.set_ylabel('净值');ax.grid(alpha=.15)
        dd.fill_between(n['日期'],n['回撤']*100,0,color='#b7c8de');dd.set_ylabel('回撤 %');dd.grid(alpha=.15);fig.tight_layout();canvas.draw()
        tree.delete(*tree.get_children())
        try:
            t=pd.read_csv(p/'已平仓交易.csv');
            for _,row in t.tail(200).iterrows():tree.insert('', 'end',values=[row.get(k,'') if k not in ['买入价','卖出价','收益率'] else ('%.2f%%'%(row[k]*100) if k=='收益率' else '%.2f'%row[k]) for k in cols])
        except pd.errors.EmptyDataError:pass
        status.set('结果保存在：'+str(p))
    def run():
        try:
            args=(variables['股票代码'].get(),variables['开始日期'].get(),variables['结束日期'].get(),float(variables['初始资金'].get()),choice.get(),int(variables['短周期'].get()),int(variables['长周期'].get()),float(variables['单边佣金 %'].get())/100,float(variables['单边滑点 %'].get())/100)
            pd.Timestamp(args[1]);pd.Timestamp(args[2])
        except Exception as e:messagebox.showerror('参数错误',str(e));return
        button.config(state='disabled');status.set('正在请求 BaoStock API（股票、复权、基准），请稍候……')
        def work():
            try:
                p=backtest(*args)
                def done():
                    refresh();listing.selection_clear(0,'end');listing.selection_set(folders.index(p));show();button.config(state='normal')
                w.after(0,done)
            except Exception as e:
                msg=str(e);w.after(0,lambda:(button.config(state='normal'),status.set('回测失败'),messagebox.showerror('回测失败',msg)))
        threading.Thread(target=work,daemon=True).start()
    button.config(command=run);listing.bind('<<ListboxSelect>>',show);refresh()
    if folders:listing.selection_set(0);show()
    if standalone: w.mainloop()
    return w

if __name__=='__main__':app()
