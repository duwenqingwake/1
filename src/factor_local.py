from pathlib import Path
import json, threading, uuid
import queue
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from app_paths import WORK
OUT=WORK/'因子结果'; OUT.mkdir(parents=True,exist_ok=True)

def panel(parent):
    root=ttk.Frame(parent,padding=14);root.pack(fill='both',expand=True)
    left=ttk.Frame(root,width=260);left.pack(side='left',fill='y',padx=(0,18));right=ttk.Frame(root);right.pack(side='left',fill='both',expand=True)
    ttk.Label(left,text='因子测试',font=('Microsoft YaHei',16,'bold')).pack(anchor='w')
    ttk.Label(left,text='演示结果 + BaoStock API · 沪深主板',foreground='#666').pack(anchor='w',pady=5)
    ttk.Label(left,text='测试因子').pack(anchor='w');selected=tk.StringVar(value='Alpha191 五因子组合')
    ttk.Combobox(left,textvariable=selected,values=['Alpha191 五因子组合','20日动量'],state='readonly',width=25).pack(fill='x')
    values={}
    for label,default in [('开始日期','2023-01-01'),('结束日期','2026-09-24'),('分组周期（交易日）','5')]:
        ttk.Label(left,text=label).pack(anchor='w',pady=(9,0));v=tk.StringVar(value=default);values[label]=v;ttk.Entry(left,textvariable=v).pack(fill='x')
    button=ttk.Button(left,text='运行因子测试');button.pack(fill='x',pady=12)
    ttk.Label(left,text='历史因子测试',font=('Microsoft YaHei',11,'bold')).pack(anchor='w');listing=tk.Listbox(left,width=27,exportselection=False);listing.pack(fill='both',expand=True,pady=5)
    status=tk.StringVar(value='因子分组用于研究，不等同实际交易。');ttk.Label(left,textvariable=status,wraplength=210,foreground='#666').pack(anchor='w')
    title=ttk.Label(right,text='查看因子分组',font=('Microsoft YaHei',15,'bold'));title.pack(anchor='w')
    info=tk.StringVar(value='等待测试');ttk.Label(right,textvariable=info,foreground='#555').pack(anchor='w',pady=8)
    fig=Figure(figsize=(8,5),dpi=100);ax=fig.add_subplot(211);ax2=fig.add_subplot(212);canvas=FigureCanvasTkAgg(fig,master=right);canvas.get_tk_widget().pack(fill='both',expand=True)
    ictext=tk.StringVar(value='');ttk.Label(right,textvariable=ictext,wraplength=950).pack(anchor='w')
    ttk.Label(right,text='组合使用原始因子方向，按1% / 99%缩尾、标准化、等权；比赛成本单边0.3%。前10%为每期全换手代理：未来无法计算样本被事后剔除，存在偏差；缺中证全指基准和月度计分，不能视作正式比赛回测。',wraplength=900,foreground='#666').pack(anchor='w',pady=8)
    events=queue.Queue()
    def poll():
        try:
            while True:status.set(events.get_nowait())
        except queue.Empty:pass
        root.after(200,poll)
    poll()
    folders=[]
    def refresh():
        folders[:]=sorted([p for p in OUT.iterdir() if (p/'摘要.json').exists()],reverse=True);listing.delete(0,'end')
        for p in folders:
            try: name=json.loads((p/'摘要.json').read_text(encoding='utf-8')).get('因子','因子测试')
            except Exception: name='因子测试'
            listing.insert('end',p.name[:15]+' '+name)
    def show(event=None):
        if not listing.curselection():return
        p=folders[listing.curselection()[0]];m=json.loads((p/'摘要.json').read_text(encoding='utf-8'));df=pd.read_csv(p/'每期分组和IC.csv',parse_dates=['信号日'])
        title.config(text=m.get('因子','因子测试')+' · 分组结果'); info.set('区间 %s 至 %s  |  %s期  |  平均 RankIC %.4f  |  ICIR %s  |  IC为正 %.1f%%  |  可计算覆盖 %.1f%%'%(m['开始'],m['结束'],m['期数'],m['平均RankIC'],('%.3f'%m['ICIR'] if m.get('ICIR') is not None else '—'),100*m['IC正比例'],100*m['覆盖率']))
        ax.clear();ax2.clear()
        for i,color in enumerate(['#8c8c8c','#b6b6b6','#666666','#6090b8','#1d5fbf'],1):
            y=df['第%d组'%i];ax.plot(pd.to_datetime(df['卖出日']),(1+y).cumprod(),color=color,label='第%d组'%i)
        ax.set_ylabel('分组净值（口径见说明）');ax.legend(ncol=5,fontsize=8);ax.grid(alpha=.15)
        if '前10%比赛成本代理收益' in df:
            ax2.plot(pd.to_datetime(df['卖出日']),(1+df['前10%比赛成本代理收益']).cumprod(),color='#1d5fbf',label='前10%比赛成本代理');ax2.legend(fontsize=8);ax2.set_ylabel('前10%代理净值')
        else: ax2.bar(df['信号日'],df['RankIC'],width=3);ax2.set_ylabel('RankIC')
        ax2.grid(alpha=.15);fig.tight_layout();canvas.draw()
        icfile=p/'因子IC统计.csv'
        if icfile.exists():
            q=pd.read_csv(icfile);ictext.set('各因子 RankIC / ICIR（未年化）：'+'    '.join('%s %.3f / %.3f'%(r['因子'],r['平均RankIC'],r['ICIR（未年化）']) for _,r in q.iterrows()))
        else:ictext.set('此旧结果没有单因子 IC 统计。')
        status.set('结果保存在：'+str(p))
    def start_run():
        try: a=values['开始日期'].get();b=values['结束日期'].get();n=int(values['分组周期（交易日）'].get());pd.Timestamp(a);pd.Timestamp(b)
        except Exception as e:messagebox.showerror('参数错误',str(e));return
        selection=selected.get();button.config(state='disabled');status.set('正在读取全市场数据，可能需要几分钟……')
        def work():
            try:
                from factor_api_compute import compute
                p=compute(a,b,n,selection=selection,progress=events.put)
                def done():refresh();listing.selection_set(folders.index(p));show();button.config(state='normal')
                root.after(0,done)
            except Exception as e:
                msg=str(e);root.after(0,lambda:(button.config(state='normal'),status.set('测试失败'),messagebox.showerror('测试失败',msg)))
        threading.Thread(target=work,daemon=True).start()
    button.config(command=start_run);listing.bind('<<ListboxSelect>>',show);refresh()
    if folders:listing.selection_set(0);show()
    return root
