"""共享时空图的二元整数规划，两阶段调用 SciPy/HiGHS。"""
from collections import defaultdict
from time import monotonic
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix
from Question1.model.problem import Lift, Result, validate
from model.audit import audit


# 作用：解共享时空图上的两阶段约束模型。输入：p 为完整计划，seconds 为两阶段共用秒数。返回：经回放的 Result，optimal 表示两阶段均已证明最优。
def joint(p, seconds=10):
    deadline = monotonic()+seconds
    validate(p)
    tr = p.track
    nodes = [sorted(set(tr.parking) | {x} | {z for edge in edges for z in edge})
             for edges,x in zip(tr.edges,tr.initial)]
    arcs, candidates = {}, {}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    moves, waits = {}, {}
    for k,points in enumerate(nodes):
        for h in range(p.horizon):
            for x in points:
                for y in (x-1,x,x+1):
                    if (x,y) not in tr.edges[k] and not (x == y and x in tr.parking):
                        continue
                    idx = len(arcs)
                    arcs[k,h,x,y] = idx
                    incoming[k,h+1,y].append(idx)
                    outgoing[k,h,x].append(idx)
                    moves[idx] = int(x != y)
    rows,lower,upper = [],[],[]

    # 作用：加入一行线性约束。输入：terms 为(变量列,系数)，lo/hi 为上下界。返回：无。
    def constrain(terms, lo, hi):
        rows.append(list(terms))
        lower.append(lo)
        upper.append(hi)

    for k,points in enumerate(nodes):
        for h in range(p.horizon):
            for x in points:
                rhs = int(h == 0 and x == tr.initial[k])
                constrain([(i,1) for i in outgoing[k,h,x]]+[(i,-1) for i in incoming[k,h,x]],rhs,rhs)
    for k,gap in enumerate(tr.gaps):
        for h in range(1,p.horizon+1):
            constrain([(i,sign*x) for car,sign in ((k,-1),(k+1,1))
                       for x in nodes[car] for i in incoming[car,h,x]],gap,np.inf)

    by_task, busy, occupancy = defaultdict(list),defaultdict(list),defaultdict(list)
    for t in p.tasks:
        length = abs(t.dst-t.src)
        step = 1 if t.dst > t.src else -1
        last = min(t.due-length,t.latest_pick if t.latest_pick is not None else t.due)
        for k in set(t.cars):
            if any((x,x+step) not in tr.edges[k] for x in range(t.src,t.dst,step)):
                continue
            for s in range(t.ready,last+1):
                v = Lift(t.name,k,s,s+length)
                idx = len(arcs)+len(candidates)
                candidates[v] = idx
                by_task[t.name].append((v,idx))
                waits[idx] = s-t.ready
                for offset,x in enumerate(range(t.src,t.dst,step)):
                    constrain([(idx,1),(arcs[k,s+offset,x,x+step],-1)],-np.inf,0)
                    busy[k,s+offset].append(idx)
                for resource,a,b in ((t.source,t.upstream,s+t.release_lag),(t.receiver,v.end,t.downstream)):
                    if resource is not None:
                        for h in range(a,b):
                            occupancy[resource,h].append(idx)
        if not by_task[t.name]:
            return Result("infeasible")
        constrain([(i,1) for _,i in by_task[t.name]],1,1)
    for t in p.tasks:
        for parent,lag in t.parents:
            constrain([(i,v.start) for v,i in by_task[t.name]]+
                      [(i,-v.end) for v,i in by_task[parent]],lag,np.inf)
    for indices in busy.values():
        constrain([(i,1) for i in indices],-np.inf,1)
    for (key,h),indices in occupancy.items():
        reserved = sum(r == key and a <= h < b for r,a,b in p.bookings)
        constrain([(i,1) for i in indices],-np.inf,p.caps[key]-reserved)
    n = len(arcs)+len(candidates)
    if not n:
        if p.horizon:
            return Result("infeasible")
        return Result("optimal",(),(tr.initial,),0,0)

    # 作用：解当前阶段并解码轨迹。输入：cost 为目标系数映射。返回：(状态及可行解, 是否已证明该阶段最优)。
    def stage(cost):
        remaining = deadline-monotonic()
        if remaining <= 0:
            return Result("unknown"),False
        rr,cc,values = [],[],[]
        for row,terms in enumerate(rows):
            for col,value in terms:
                rr.append(row)
                cc.append(col)
                values.append(value)
        matrix = coo_matrix((values,(rr,cc)),shape=(len(rows),n)).tocsr()
        objective = np.zeros(n)
        for i,value in cost.items():
            objective[i] = value
        sol = milp(objective,integrality=np.ones(n),bounds=Bounds(0,1),
                   constraints=LinearConstraint(matrix,lower,upper),
                   options={"time_limit":remaining,"mip_rel_gap":0.0})
        if sol.x is None:
            return Result("infeasible" if sol.status == 2 else "unknown"),False
        lifts = tuple(v for v,i in candidates.items() if sol.x[i] > .5)
        frames = [list(tr.initial) for _ in range(p.horizon+1)]
        for (k,h,x,y),i in arcs.items():
            if sol.x[i] > .5:
                frames[h+1][k] = y
        result = Result("feasible",lifts,tuple(map(tuple,frames)),
                        sum(value for i,value in waits.items() if sol.x[i] > .5),
                        sum(value for i,value in moves.items() if sol.x[i] > .5))
        audit(p,result)
        return result,sol.status == 0

    first, proven = stage(waits)
    if not first.frames:
        return first
    constrain(waits.items(),first.wait if proven else -np.inf,first.wait)
    second, refined = stage(moves)
    if not second.frames:
        return first
    from dataclasses import replace
    incumbent = min((first,second),key=lambda r:(r.wait,r.movement))
    return replace(incumbent,status="optimal" if proven and refined else "feasible")
