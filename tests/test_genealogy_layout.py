import unittest
from backend.archivereader.genealogy_layout import layout_tree


class GenealogyLayoutTests(unittest.TestCase):
    def test_focus_is_on_top_and_couples_are_adjacent_below(self):
        people=[{'id':str(i),'name':str(i),'tree_root':i==0} for i in range(6)]
        links=[{'left':str(a),'right':str(b),'kind':kind,'status':'imported'} for a,b,kind in
               [(1,0,'parent'),(2,0,'parent'),(1,2,'spouse'),(3,1,'parent'),(4,1,'parent'),(3,4,'spouse')]]
        result=layout_tree(people,links);nodes={n['id']:n for n in result['nodes']}
        self.assertEqual([nodes[str(i)]['generation'] for i in range(5)],[0,1,1,2,2])
        self.assertEqual(abs(nodes['1']['column']-nodes['2']['column']),1)
        self.assertEqual(abs(nodes['3']['column']-nodes['4']['column']),1)
        self.assertFalse(nodes['5']['connected']);self.assertEqual(nodes['5']['generation'],3)

    def test_cycles_are_reported_without_unbounded_layout(self):
        people=[{'id':str(i),'name':str(i)} for i in range(2)]
        links=[{'left':a,'right':b,'kind':'parent','status':'imported'} for a,b in [('0','1'),('1','0')]]
        self.assertIn('ancestor_cycle',layout_tree(people,links)['warnings'])

    def test_withdrawn_links_do_not_move_people_or_create_couples(self):
        people=[{'id':'a','name':'A'},{'id':'b','name':'B'}]
        result=layout_tree(people,[{'left':'a','right':'b','kind':'spouse','status':'withdrawn'}],root='a')
        self.assertFalse(next(n for n in result['nodes'] if n['id']=='b')['connected'])
