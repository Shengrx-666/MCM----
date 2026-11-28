"""小窗口精确动态规划。分层状态包括全体车位及已起吊记录（含正在运行的任务）。"""
from itertools import product
from time import monotonic

from model.map import fits, separated
from Question1.model.problem import Lift, Result, validate


# 作用：构造已知占位区间。输入：p 为计划，lifts 为已确定的吊运。返回：所有已知预约。
def bookings(p, lifts):
    indexed = {t.name: t for t in p.tasks}
    rows = list(p.bookings)
    for lift in lifts:
        t = indexed[lift.task]
        rows.extend(((t.source, t.upstream, lift.start + t.release_lag),
                     (t.receiver, lift.end, t.downstream)))
    return rows


# 作用：枚举单车下一拍动作。输入：p 为计划，k 为车号，x 为车位，now 为时刻，known 为已启动任务，fixed 为固定承诺。返回：(新坐标,新增吊运或 None)。
def actions(p, k, x, now, known, fixed):
    edges = p.track.edges[k]
    active = next((v for v in known.values() if v.car == k and v.end > now), None)
    for t in p.tasks:
        step = 1 if t.dst > t.src else -1
        if active:
            if active.task == t.name and (x, x + step) in edges:
                yield x + step, None
            continue
        if t.name in known or k not in t.cars or x != t.src:
            continue
        end = now + abs(t.dst - t.src)
        if now < t.ready or end > t.due or (t.latest_pick is not None and now > t.latest_pick):
            continue
        if any(a not in known or known[a].end + lag > now for a, lag in t.parents):
            continue
        lift = Lift(t.name, k, now, end)
        if t.name in fixed and lift != fixed[t.name]:
            continue
        if all((i, i+step) in edges for i in range(x, t.dst, step)):
            yield x + step, lift
    if active is None:
        if x in p.track.parking:
            yield x, None
        for dst in (x-1, x+1):
            if (x, dst) in edges:
                yield dst, None


# 作用：联合求解整个窗口。输入：p 为计划，seconds 为秒数预算，fixed 为固定吊运，pins 为(时刻,车号)到车位映射，priority 指定目标顺序。返回：带状态、逐拍轨迹与任务表的 Result。
def solve(p, seconds=10, fixed=(), pins=None, priority="wait"):
    deadline = monotonic() + seconds
    validate(p)
    if priority not in ("wait", "movement"):
        raise ValueError("未知优化目标")
    commitments = {v.task: v for v in fixed}
    if len(commitments) != len(fixed) or commitments.keys() - {t.name for t in p.tasks}:
        raise ValueError("固定承诺的任务重复或不存在")
    pins = {} if pins is None else pins
    n = len(p.track.initial)
    if any(not (0 <= time <= p.horizon and 0 <= car < n) for time, car in pins):
        raise ValueError("固定车位超出时域或车辆范围")
    if any(pins.get((0,k), x) != x for k,x in enumerate(p.track.initial)):
        return Result("infeasible")
    layer = {(p.track.initial, ()): (0, (p.track.initial,))}
    tasks = {t.name: t for t in p.tasks}
    best = None
    best_score = None
    for now in range(p.horizon + 1):
        next_layer = {}
        for (positions, lifts), (movement, frames) in layer.items():
            if monotonic() >= deadline:
                if best is None:
                    return Result("unknown")
                return Result("feasible", best.lifts, best.frames, best.wait, best.movement)
            known = {v.task: v for v in lifts}
            if any(t.name not in known and (now + abs(t.dst-t.src) > t.due
                   or (t.latest_pick is not None and now > t.latest_pick)) for t in p.tasks):
                continue
            if now == p.horizon:
                if len(lifts) == len(tasks):
                    wait = sum(v.start - tasks[v.task].ready for v in lifts)
                    score = (wait, movement) if priority == "wait" else (movement, wait)
                    if best_score is None or score < best_score:
                        best_score = score
                        best = Result("optimal", lifts, frames, wait, movement)
                continue
            choices = [actions(p, k, x, now, known, commitments) for k,x in enumerate(positions)]
            for joint in product(*choices):
                if monotonic() >= deadline:
                    return Result("unknown")
                new_positions = tuple(x for x, _ in joint)
                if not separated(new_positions, p.track.gaps):
                    continue
                if any(pins.get((now+1,k), x) != x for k,x in enumerate(new_positions)):
                    continue
                added = tuple(v for _,v in joint if v is not None)
                if len({v.task for v in added}) != len(added):
                    continue
                new_lifts = tuple(sorted(lifts + added))
                if added and not fits(bookings(p, new_lifts), p.caps):
                    continue
                cost = movement + sum(a != b for a,b in zip(positions, new_positions))
                key = (new_positions, new_lifts)
                if key not in next_layer or cost < next_layer[key][0]:
                    next_layer[key] = cost, frames + (new_positions,)
        layer = next_layer
        if not layer:
            break
    return best or Result("infeasible")


# 作用：复核局部车序并保留窗外承诺。输入：p 为全计划，base 为已验解，car 为目标车，begin/end 为窗口边界，seconds 为预算。返回：经全程复核的解或搜索状态。
def local(p, base, car, begin, end, seconds=10):
    from dataclasses import replace
    from model.audit import audit
    audit(p, base)
    if not 0 <= begin < end <= p.horizon or not 0 <= car < len(p.track.initial):
        raise ValueError("局部窗口或车辆编号无效")
    free = {v.task for v in base.lifts if v.car == car and begin <= v.start and v.end <= end}
    tasks = tuple(replace(t, cars=(car,),
                          latest_pick=min(end-abs(t.dst-t.src),
                                          t.latest_pick if t.latest_pick is not None else end))
                  if t.name in free else t for t in p.tasks)
    pins = {(i,k): x for i,row in enumerate(base.frames) for k,x in enumerate(row)
            if k != car or i <= begin or i >= end}
    # 保留原就绪时刻的目标口径，将自由任务的起吊下界设为入窗时间；同一任务集的目标仅相差一个常数。
    constrained = replace(p, tasks=tuple(replace(t, alpha=max(t.alpha, begin-t.upstream))
                                         if t.name in free else t for t in tasks))
    result = solve(constrained, seconds, tuple(v for v in base.lifts if v.task not in free), pins)
    if result.frames:
        ready = {t.name: t.ready for t in p.tasks}
        result = replace(result, wait=sum(v.start-ready[v.task] for v in result.lifts))
        audit(p, result)
    return result
