from pathlib import Path
import sys
BASE=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
DATA=BASE/'演示数据'
WORK=BASE/'运行结果'
