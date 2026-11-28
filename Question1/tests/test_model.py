from dataclasses import replace
import unittest
from Question1.model.example import example
from model.map import Track, fits, safe_trace
from Question1.model.problem import Problem
from model.windows import Task, Cast, cast_bookings, chain
from model.dp import solve, local
from Question1.model.baseline import baseline
from model.audit import audit


# 作用：建立手算小窗口。输入：a 为 A 起吊期限，b 为 B 落包期限。返回：单车双任务 Problem。
def manual(a,b):
    edges = frozenset(((0,1),(1,0),(1,2),(2,1)))
    track = Track((1,),(edges,),frozenset(range(3)),())
    tasks = (Task("A",0,2,0,6,(0,),latest_pick=a),Task("B",2,0,0,b,(0,)))
    return Problem(tasks,track,6,{})


class ModelTests(unittest.TestCase):
    # 作用：复现三组手算结论。输入：self 为测试实例。返回：无。
    def test_orders(self):
        for a,b,order in [(2,6,"AB"),(4,4,"BA"),(2,4,None)]:
            p = manual(a,b)
            r = solve(p)
            if order is None:
                self.assertEqual(r.status,"infeasible")
            else:
                self.assertEqual(audit(p,r)["wait"],4)
                self.assertEqual("".join(v.task for v in sorted(r.lifts,key=lambda x:x.start)),order)

    # 作用：区分异常输入、不可行和超时。输入：self 为测试实例。返回：无。
    def test_windows(self):
        p = manual(2,6)
        t = p.tasks[0]
        with self.assertRaisesRegex(ValueError,"就绪"):
            solve(replace(p,tasks=(replace(t,upstream=3,downstream=2),)))
        self.assertEqual(solve(replace(p,tasks=(replace(t,downstream=1),))).status,"infeasible")
        self.assertEqual(solve(p,0).status,"unknown")

    # 作用：检查中间越车与左闭右开容量。输入：self 为测试实例。返回：无。
    def test_map(self):
        self.assertFalse(safe_trace(((0,10),(6,4),(0,10)),(2,)))
        p = manual(2,6)
        t = replace(p.tasks[0],receiver="LF")
        for end,status in [(5,"optimal"),(6,"optimal")]:
            q = replace(p,tasks=(t,),caps={"LF":1},bookings=(("LF",0,end),))
            q = replace(q,tasks=(replace(t,latest_pick=None),))
            r = solve(q)
            self.assertEqual(r.status,status)
            self.assertGreaterEqual(r.lifts[0].end,end)
        self.assertFalse(fits((("R",5,9),("R",8,10)),{"R":1}))
        self.assertTrue(fits((("R",5,9),("R",9,10)),{"R":1}))

    # 作用：验证三任务优化、邻车与窗外承诺。输入：self 为测试实例。返回：无。
    def test_joint_and_local(self):
        p = example()
        base = baseline(p)
        best = solve(p)
        patch = local(p,base,0,0,8)
        self.assertEqual([audit(p,r)["wait"] for r in (base,best,patch)],[6,2,2])
        self.assertEqual([audit(p,r)["empty"] for r in (base,best)],[3,1])
        self.assertEqual(patch.frames[8:],base.frames[8:])
        self.assertEqual([v[1:] for v in patch.frames],[v[1:] for v in base.frames])

    # 作用：测试两车择车、避让及错误轨迹回放。输入：self 为测试实例。返回：无。
    def test_assignment(self):
        edges = frozenset((a,b) for a in range(5) for b in range(5) if abs(a-b)==1)
        tr = Track((0,2),(edges,edges),frozenset(range(5)),(1,))
        p = Problem((Task("A",0,2,0,2,(0,1)),Task("B",2,3,0,1,(0,1))),tr,2,{})
        r = solve(p)
        self.assertEqual(audit(p,r)["wait"],0)
        self.assertEqual({v.task:v.car for v in r.lifts},{"A":0,"B":1})
        with self.assertRaises(ValueError):
            audit(p,replace(r,frames=(tr.initial,(2,1),r.frames[-1])))

    # 作用：核对工艺间隔、断浇与源位释放滞后。输入：self 为测试实例。返回：无。
    def test_process(self):
        p = manual(4,6)
        a,b = p.tasks
        self.assertEqual(solve(replace(p,tasks=chain((a,b),(2,)))).status,"infeasible")
        q = replace(p,tasks=(replace(a,source="炉后",release_lag=2),),
                    caps={"炉后":1},bookings=(("炉后",2,3),))
        self.assertEqual(solve(q).status,"infeasible")
        tasks = (replace(a,downstream=2),b)
        cs = (Cast("CC","S","A",2,5),Cast("CC","S","B",6,8,1))
        self.assertEqual(cast_bookings(cs,tasks)[1],("CC",5,6))
        with self.assertRaisesRegex(ValueError,"断浇"):
            cast_bookings((cs[0],replace(cs[1],changeover=0)),tasks)

    # 作用：独立算法交叉检查最优目标与无解判断。输入：self 为测试实例。返回：无。
    def test_milp_against_dp(self):
        from model.map.joint import joint
        from random import Random
        rng = Random(17)
        cases = [manual(2,6),manual(4,4),manual(2,4),example()]
        for _ in range(20):
            p = manual(4,6)
            tasks = tuple(replace(t,upstream=rng.randrange(3),downstream=rng.randrange(3,7),
                                  latest_pick=rng.randrange(5),receiver="R") for t in p.tasks)
            cases.append(replace(p,tasks=tasks,caps={"R":1}))
        for p in cases:
            a,b = joint(p),solve(p)
            self.assertEqual((a.status,a.wait,a.movement),(b.status,b.wait,b.movement))
            if a.frames:
                audit(p,a)

    # 作用：检查环依赖、重复任务和非法回程渡车。输入：self 为测试实例。返回：无。
    def test_malformed(self):
        p = manual(2,6)
        a,b = p.tasks
        for bad in [(a,a),(replace(a,parents=(("B",0),)),replace(b,parents=(("A",0),))),
                    (replace(a,return_ferry=4),)]:
            with self.assertRaises(ValueError):
                solve(replace(p,tasks=bad))
