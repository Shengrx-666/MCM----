from time import monotonic
from Question1.model.example import example
from Question1.model.baseline import baseline
from Question1.model.report import report


# 作用：运行同一场景并输出本策略的校验结果。输入：无。返回：无。
def main():
    p = example()
    start = monotonic()
    result = baseline(p, seconds=10)
    report(p, result, monotonic()-start)


if __name__ == "__main__":
    main()
