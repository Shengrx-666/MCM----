"""合成验收场景。"""
from model.map import Track
from model.windows import Task
from Question1.model.problem import Problem


# 作用：构造同一组五车三任务。输入：无。返回：可重复的合成 Problem，单位为分钟和等距轨道格。
def example():
    edges = frozenset((a,b) for a in range(4) for b in range(4) if abs(a-b)==1)
    other = frozenset(((6,7),(7,6)))
    track = Track((0,6,10,12,14),(edges,other,frozenset(),frozenset(),frozenset()),
                  frozenset((0,1,2,3,6,7,10,12,14)),(2,2,2,2))
    tasks = (Task("A",0,3,0,6,(0,),receiver="LF"),
             Task("B",0,1,0,9,(0,),receiver="RH"),
             Task("C",6,7,1,5,(1,),receiver="CC"))
    return Problem(tasks,track,9,{"LF":1,"RH":1,"CC":1})
