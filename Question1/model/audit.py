"""独立回放输出：从轨迹和任务表重建资源、速度、窗口与指标。"""
from math import ceil
from model.map import fits, safe_trace
from model.problem import validate


# 作用：独立复算硬约束与指标。输入：p 为原计划，result 为候选完整解。返回：指标字典，违约时抛出 ValueError。
def audit(p, result):
    validate(p)
    rows = result.frames
    jobs = {v.task: v for v in result.lifts}
    tr = p.track
    if len(rows) != p.horizon+1 or rows[0] != tr.initial or not safe_trace(rows, tr.gaps):
        raise ValueError("轨迹边界或安全间距错误")
    if len(jobs) != len(result.lifts) or set(jobs) != {t.name for t in p.tasks}:
        raise ValueError("任务覆盖错误")
    moving = 0
    for before, after in zip(rows, rows[1:]):
        for k,(a,b) in enumerate(zip(before,after)):
            if (a == b and a not in tr.parking) or (a != b and (a,b) not in tr.edges[k]):
                raise ValueError("非法移动或驻车")
            moving += a != b
    busy = set()
    reservations = list(p.bookings)
    waits, loaded = [], 0
    delivery_slack = 0
    prestart_occupancy = 0
    for t in p.tasks:
        v = jobs[t.name]
        if not (v.car in t.cars and t.ready <= v.start < v.end <= t.due
                and v.end-v.start == abs(t.dst-t.src)):
            raise ValueError("车辆资格、窗口或行程错误")
        if t.latest_pick is not None and v.start > t.latest_pick:
            raise ValueError("源位腾空超期")
        if any(jobs[a].end+lag > v.start for a,lag in t.parents):
            raise ValueError("违反工艺顺序")
        step = 1 if t.dst > t.src else -1
        for i in range(v.start, v.end+1):
            if rows[i][v.car] != t.src + (i-v.start)*step:
                raise ValueError("带包轨迹错误")
            if i < v.end:
                if (v.car,i) in busy:
                    raise ValueError("同车重复指派")
                busy.add((v.car,i))
        reservations.extend(((t.source,t.upstream,v.start+t.release_lag),
                             (t.receiver,v.end,t.downstream)))
        waits.append(v.start-t.ready)
        loaded += v.end-v.start
        # 各任务的提前交付时长，以及落包至下游开工的时长，均按任务累加。
        delivery_slack += t.due - v.end
        prestart_occupancy += t.downstream - v.end
    if not fits(reservations,p.caps) or (sum(waits),moving) != (result.wait,result.movement):
        raise ValueError("资源超容或目标值不一致")
    return dict(wait=sum(waits), p95=sorted(waits)[ceil(.95*len(waits))-1] if waits else 0,
                post_wait=delivery_slack,  # 兼容旧报表，原字段一直统计交付余量。
                delivery_slack=delivery_slack, prestart_occupancy=prestart_occupancy,
                loaded=loaded, empty=moving-loaded,
                min_gap=min((b-a for row in rows for a,b in zip(row,row[1:])), default=None))
