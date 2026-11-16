import sys,shutil,json,traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from app_paths import DATA,WORK
import backtest_local,factor_local

def case_tab(parent):
 p=DATA/'策略案例'; frame=ttk.Frame(parent,padding=16);frame.pack(fill='both',expand=True)
 ttk.Label(frame,text='研究案例：主板小市值轮动 + 收盘止损 8%',font=('Microsoft YaHei',15,'bold')).pack(anchor='w')
 ttk.Label(frame,text='历史示例｜2023-01-03 至 2026-09-24｜初始资金10万元｜日线研究模拟，不代表实盘收益',foreground='#666').pack(anchor='w',pady=5)
 m=json.loads((p/'指标.json').read_text(encoding='utf8')); n=pd.read_csv(p/'净值.csv',parse_dates=['date']);t=pd.read_csv(p/'平仓.csv')
 items=[('策略收益',f"{m['return']:.2%}"),('年化收益',f"{m['annual']:.2%}"),('基准收益',f"{m['benchmark_return']:.2%}"),('最大回撤',f"{m['max_drawdown']:.2%}"),('夏普',f"{m['sharpe']:.2f}"),('已平仓胜率',f"{m['win_rate']:.2%}"),('平仓笔数',str(m['closed_trades']))]
 line=ttk.Frame(frame);line.pack(fill='x',pady=8)
 for k,v in items:
  a=ttk.Frame(line,padding=(0,0,20,0));a.pack(side='left');ttk.Label(a,text=k,foreground='#777').pack(anchor='w');ttk.Label(a,text=v,font=('Microsoft YaHei',11,'bold')).pack(anchor='w')
 fig=Figure(figsize=(10,4),dpi=90);ax=fig.add_subplot(211);dd=fig.add_subplot(212)
 ax.plot(n.date,n.equity/100000,label='策略');ax.plot(n.date,n.benchmark/100000,label='沪深300');ax.legend();ax.grid(alpha=.2);dd.fill_between(n.date,n.drawdown,0,alpha=.3);dd.set_ylabel('回撤');dd.grid(alpha=.2);fig.tight_layout();canvas=FigureCanvasTkAgg(fig,master=frame);canvas.get_tk_widget().pack(fill='both',expand=True)
 ttk.Label(frame,text='重要：这是本地历史近似回测。流通市值和历史风险名称为估算，开盘成交、分红与止损存在模拟限制；最大持仓5只不等于单股上限20%。请阅读演示数据中的研究报告。',wraplength=1100,foreground='#9b4a22').pack(anchor='w',pady=7)
 ttk.Label(frame,text='示例数据：演示数据/策略案例；包含净值、平仓、成交和研究报告。',foreground='#666').pack(anchor='w')

def main():
 WORK.mkdir(parents=True,exist_ok=True)
 sample=WORK/'因子结果'/'示例_Alpha191';source=DATA/'因子示例'/'Alpha191五因子_历史示例'
 if not sample.exists():sample.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(source,sample)
 root=tk.Tk();root.title('本地量化研究工具 · 面试演示版');root.geometry('1450x920');root.minsize(1100,720)
 note=ttk.Label(root,text='研究与能力展示｜历史结果仅供演示；在线回测需访问 BaoStock｜示例不包含账户与密码',foreground='#705000',padding=(10,5));note.pack(fill='x')
 tabs=ttk.Notebook(root);tabs.pack(fill='both',expand=True)
 case=ttk.Frame(tabs);stock=ttk.Frame(tabs);factor=ttk.Frame(tabs)
 tabs.add(case,text='研究案例（离线）');tabs.add(stock,text='股票策略回测（在线）');tabs.add(factor,text='因子测试（在线）')
 case_tab(case);backtest_local.app(stock);factor_local.panel(factor)
 if '--online-test' in sys.argv:
  def test_online():
   try:
    path=backtest_local.backtest('000001','2025-01-02','2025-03-31',100000,'均线趋势',5,20,.0000854,.001)
    (WORK/'在线自检.txt').write_text(str(path),encoding='utf8')
   except Exception:
    (WORK/'在线自检错误.txt').write_text(traceback.format_exc(),encoding='utf8')
   finally:root.destroy()
  root.after(500,test_online)
 if '--self-test' in sys.argv:
  def done():
   import baostock, factor_api_compute, factor_api_data
   assert backtest_local.ROOT == WORK and factor_local.OUT == WORK/'因子结果', '模块路径未隔离'
   assert len(tabs.tabs()) == 3 and (WORK/'因子结果'/'示例_Alpha191'/'摘要.json').exists(), '示例未加载'
   (WORK/'启动自检.txt').write_text('GUI initialized; three tabs and sample loaded; outputs use portable directory.\n',encoding='utf8');root.destroy()
  root.after(1500,done)
 root.mainloop()
if __name__=='__main__':
 try:main()
 except Exception:
  WORK.mkdir(parents=True,exist_ok=True);(WORK/'启动错误.txt').write_text(traceback.format_exc(),encoding='utf8');raise
