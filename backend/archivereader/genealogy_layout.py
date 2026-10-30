"""Place the focus person above their ancestors and keep documented couples adjacent."""
from collections import deque


def layout_tree(people, relationships, root=None):
    persons={p['id']:p for p in people}
    if not persons:return {'root':None,'nodes':[],'warnings':[],'unconnected_generation':None}
    if root is not None and root not in persons:raise ValueError('Tree root not found.')
    links=[f for f in relationships if f['status'] in ['confirmed','imported'] and f['left'] in persons and f['right'] in persons]
    groups={ident:ident for ident in persons}
    def find(ident):
        while groups[ident]!=ident:
            groups[ident]=groups[groups[ident]];ident=groups[ident]
        return ident
    for link in links:
        if link['kind']=='spouse':groups[find(link['right'])]=find(link['left'])
    members={}
    for ident in persons:members.setdefault(find(ident),[]).append(ident)
    edges={key:set() for key in members};indegree={key:0 for key in members};warnings=[]
    adjacent={ident:set() for ident in persons}
    for link in links:
        left,right=link['left'],link['right'];adjacent[left].add(right);adjacent[right].add(left)
        if link['kind']!='parent':continue
        parent,child=find(left),find(right)
        if parent==child:
            warnings.append('parent_inside_couple');continue
        if child not in edges[parent]:edges[parent].add(child);indegree[child]+=1
    queue=deque(key for key in members if indegree[key]==0);depth={key:0 for key in members};visited=set()
    while queue:
        parent=queue.popleft();visited.add(parent)
        for child in edges[parent]:
            depth[child]=max(depth[child],depth[parent]+1);indegree[child]-=1
            if indegree[child]==0:queue.append(child)
    if len(visited)!=len(members):warnings.append('ancestor_cycle')
    root=root or next((p['id'] for p in people if p.get('tree_root')),None) or max(persons,key=lambda ident:depth[find(ident)])
    connected={root};queue=deque([root])
    while queue:
        for neighbor in adjacent[queue.popleft()]-connected:connected.add(neighbor);queue.append(neighbor)
    generation={key:max(0,depth[find(root)]-depth[key]) for key in members}
    last=max((generation[find(ident)] for ident in connected),default=0)
    unconnected=last+1 if connected!=set(persons) else None
    remaining=set(persons)-connected
    while remaining:
        seed=next(ident for ident in persons if ident in remaining);component={seed};queue=deque([seed])
        while queue:
            for neighbor in adjacent[queue.popleft()]-component:component.add(neighbor);queue.append(neighbor)
        remaining-=component
        deepest=max(depth[find(ident)] for ident in component)
        for ident in component:generation[find(ident)]=unconnected+deepest-depth[find(ident)]
    rows={}
    for key,ids in members.items():
        level=generation[key]
        rows.setdefault(level,[]).extend(ids)
    widest=max(map(len,rows.values()),default=1);nodes=[]
    for level,ids in sorted(rows.items()):
        if root in ids:ids=[root]+[ident for ident in ids if ident!=root]
        for column,ident in enumerate(ids):
            nodes.append({'id':ident,'name':persons[ident]['name'],'generation':level,'column':column,
                          'x':30+(widest-len(ids))*122+column*244,'y':45+level*230,'connected':ident in connected})
    return {'root':root,'nodes':nodes,'warnings':warnings,'unconnected_generation':unconnected,
            'width':max(800,widest*244+60),'height':max(600,(max(rows,default=0)+1)*230+60)}
