"""调度输入与输出契约。"""
from dataclasses import dataclass
from model.windows import Task, validate_tasks
from model.map import Track, fits, separated


@dataclass(frozen=True)
class Problem:
    tasks: tuple[Task, ...]
    track: Track
    horizon: int
    caps: dict[str, int]
    bookings: tuple[tuple[str, int, int], ...] = ()


@dataclass(frozen=True, order=True)
class Lift:
    task: str
    car: int
    start: int
    end: int


@dataclass(frozen=True)
class Result:
    status: str
    lifts: tuple[Lift, ...] = ()
    frames: tuple[tuple[int, ...], ...] = ()
    wait: int | None = None
    movement: int | None = None


# 作用：检查场景接口契约。输入：p 为完整计划。返回：无，异常输入给出原因。
def validate(p):
    validate_tasks(p.tasks)
    tr = p.track
    n = len(tr.initial)
    if not n or len(tr.edges) != n or len(tr.gaps) != n - 1:
        raise ValueError("轨道车辆与间距维数不一致")
    if any(type(x) is not int for x in (*tr.initial, *tr.parking, *tr.gaps)):
        raise ValueError("坐标和间距必须是整数")
    if any(g <= 0 for g in tr.gaps) or not separated(tr.initial, tr.gaps):
        raise ValueError("初始车位或安全间距无效")
    if any(type(a) is not int or type(b) is not int or abs(a-b) != 1
           for edges in tr.edges for a, b in edges):
        raise ValueError("每条边应对应相邻整数坐标")
    if type(p.horizon) is not int or p.horizon < 0 or any(t.downstream > p.horizon for t in p.tasks):
        raise ValueError("时域须覆盖计划")
    if any(type(v) is not int or v < 1 for v in p.caps.values()):
        raise ValueError("工位容量须为正整数")
    for key, a, b in p.bookings:
        if key not in p.caps or type(a) is not int or type(b) is not int or a < 0 or a > b:
            raise ValueError("已有预约无效")
    if not fits(p.bookings, p.caps):
        raise ValueError("已有预约超容")
    for t in p.tasks:
        if any(type(k) is not int or not 0 <= k < n for k in t.cars):
            raise ValueError("未知车辆")
        if type(t.src) is not int or type(t.dst) is not int or t.src == t.dst:
            raise ValueError("吊运端点须为不同整数坐标")
        if any(key is not None and key not in p.caps for key in (t.source, t.receiver)):
            raise ValueError("工位未定义")
