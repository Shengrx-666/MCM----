"""剩余裕量优先插单，每次保留已承诺的车辆和起落时间。"""
from dataclasses import replace
from time import monotonic
from model.problem import Lift, Result, validate
from model.dp import solve


# 作用：按剩余裕量和新增空驶选单。输入：p 为完整计划，seconds 为全次运行秒数。返回：可行解、限时状态或规则无法继续的状态。
def baseline(p, seconds=10):
    deadline = monotonic() + seconds
    validate(p)
    fixed = ()
    chosen = set()
    previous = None
    while len(chosen) < len(p.tasks):
        choices = []
        for t in p.tasks:
            if t.name in chosen or any(a not in chosen for a,_ in t.parents):
                continue
            sub = replace(p, tasks=tuple(v for v in p.tasks if v.name in chosen or v == t))
            length = abs(t.dst-t.src)
            for start in range(t.ready, min(t.due-length, t.latest_pick if t.latest_pick is not None else t.due)+1):
                at_start = []
                for k in t.cars:
                    lift = Lift(t.name,k,start,start+length)
                    plan = solve(sub, deadline-monotonic(), fixed+(lift,), priority="movement")
                    if plan.status in ("unknown","feasible"):
                        return Result("unknown", fixed)
                    if plan.frames:
                        old_moves = previous.movement if previous else 0
                        extra_empty = plan.movement-old_moves-length
                        at_start.append(((t.due-lift.end,extra_empty,t.name,k),plan))
                if at_start:
                    choices.extend(at_start)
                    break
        if not choices:
            return Result("greedy_blocked", fixed)
        _,previous = min(choices, key=lambda pair: pair[0])
        fixed = previous.lifts
        chosen = {v.task for v in fixed}
    if previous is None:
        previous = solve(p,deadline-monotonic())
    return replace(previous,status="feasible") if previous.frames else previous
