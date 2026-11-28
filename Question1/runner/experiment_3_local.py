from time import monotonic
from Question1.model.example import example
from Question1.model.baseline import baseline
from model.dp import local
from Question1.model.report import report


# 作用：固定邻车轨迹，复核车 0 的顺序。输入：无。返回：无，输出改进前后指标。
def main():
    p = example()
    start = monotonic()
    base = baseline(p)
    report(p,base,monotonic()-start)
    if base.frames:
        start = monotonic()
        result = local(p,base,0,0,p.horizon)
        report(p,result,monotonic()-start)


if __name__ == "__main__":
    main()
