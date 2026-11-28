"""统一实验输出，时刻和时长均以网格拍计。"""
from model.audit import audit


# 作用：打印求解状态、性能和调度明细。输入：p 为场景，r 为候选解，elapsed 为求解秒数。返回：无。
def report(p, r, elapsed):
    chosen = {v.task for v in r.lifts}
    print(r.status, "求解秒数", round(elapsed,4), "未排", [t.name for t in p.tasks if t.name not in chosen])
    if not r.frames:
        return
    print(audit(p,r))
    tasks = {t.name:t for t in p.tasks}
    for v in sorted(r.lifts, key=lambda v:v.start):
        t = tasks[v.task]
        print(v.task, "车辆", v.car, "起落", (v.start,v.end), "源位释放", v.start+t.release_lag,
              "交付余量", t.due-v.end, "接收预约", (t.receiver,v.end,t.downstream))
    print("逐拍车位", r.frames)
