#!/usr/bin/env python3
import argparse,json,pathlib,sys

def has_cycle(graph):
    visiting=set(); visited=set()
    def dfs(n):
        if n in visiting: return True
        if n in visited: return False
        visiting.add(n)
        for m in graph.get(n,[]): 
            if dfs(m): return True
        visiting.remove(n); visited.add(n); return False
    return any(dfs(n) for n in graph)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--graph",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.graph).read_text())
    nodes=set(d.get("subsystems",[]))
    edges=d.get("dependencies",[])
    graph={n:[] for n in nodes}
    for e in edges:
        src=e.get("from"); dst=e.get("to")
        if src not in nodes or dst not in nodes:
            print(json.dumps({"status":"FAIL","reason":"DEPENDENCY_UNKNOWN_SUBSYSTEM","edge":e})); return 2
        graph[src].append(dst)
    if has_cycle(graph):
        print(json.dumps({"status":"FAIL","reason":"DEPENDENCY_CYCLE"})); return 3
    print(json.dumps({"status":"PASS","nodes":len(nodes),"edges":len(edges)})); return 0
if __name__=="__main__":
    sys.exit(main())
