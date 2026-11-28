from time import monotonic
from Question1.model.example import example
from model.map.joint import joint
from Question1.model.report import report


# 作用：运行同一场景并输出本策略的校验结果。输入：无。返回：无。
def main():
    p = example()
    start = monotonic()
    result = joint(p, seconds=10)
    report(p, result, monotonic()-start)


if __name__ == "__main__":
    main()
