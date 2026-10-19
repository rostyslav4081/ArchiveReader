import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.archivereader.engine import Engine
from backend.archivereader.paging import PagingTools
from backend.archivereader.genealogy import GenealogyTools


class PagingTests(unittest.TestCase):
    def setUp(self):
        output=Path(__file__).resolve().parents[1]/'test-output';output.mkdir(exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=output);self.engine=Engine(Path(self.temp.name)/'library');self.tools=PagingTools(self.engine)
        with self.engine.db:
            for i in range(3):self.engine.db.execute('INSERT INTO documents VALUES (?,?,?,?)',(f'd{i}',f'Book {i}','synthetic.png',f'sha{i}'))
            self.engine.db.executemany('INSERT INTO pages(id,doc,num,text,lines) VALUES (?,?,?,?,?)',[(f'p{i:04}',f'd{i//250}',i%250,'x'*10000,'[]') for i in range(625)])
    def tearDown(self):self.engine.db.close();self.temp.cleanup()

    def test_windows_are_bounded_and_cover_library_without_repeated_rows(self):
        rows=[];offset=0;snapshot=None
        while True:
            window=self.tools.pages_window({'offset':offset,'limit':2000,'snapshot':snapshot});self.assertLessEqual(len(window['rows']),200);self.assertEqual(625,window['total']);self.assertFalse(window['snapshot_changed']);snapshot=window['snapshot'];rows+=window['rows']
            self.assertTrue(all('text' not in row and 'lines' not in row for row in window['rows']))
            if not window['has_more']:break
            offset=window['offset']+len(window['rows'])
        self.assertEqual([f'p{i:04}' for i in range(625)],[r['id'] for r in rows]);self.assertEqual(625,len({r['id'] for r in rows}))

    def test_photo_book_order_gaps_and_locate_outside_loaded_window(self):
        book=self.tools.book_save({'name':'Photo book','items':[{'page':'p0501'},{'page':None,'label':'Missing folio'},{'page':'p0002'},{'page':'p0251'}]})
        all_rows=[]
        for offset in range(0,625,200):all_rows+=self.tools.pages_window({'offset':offset})['rows']
        group=[r for r in all_rows if r.get('book')==book['id']];self.assertEqual(['p0501','p0002','p0251'],[r['id'] for r in group]);self.assertEqual([1,3,4],[r['book_position'] for r in group]);self.assertEqual(625,len({r['id'] for r in all_rows}))
        located=self.tools.pages_window({'locate':'p0624','limit':200});self.assertIn('p0624',[r['id'] for r in located['rows']]);self.assertEqual(600,located['offset'])
        current=self.tools.pages_window({});self.tools.book_save({'book':book['id'],'name':'Photo book','items':[{'page':'p0251'},{'page':'p0002'},{'page':'p0501'}]});self.assertTrue(self.tools.pages_window({'snapshot':current['snapshot']})['snapshot_changed'])

    def test_filter_searches_all_records_and_locate_reports_missing(self):
        self.engine.save_record({'id':'evidence','page':'p0610','kind':'Народження','person':'Rare surname'})
        result=self.tools.pages_window({'query':'Rare surname'});self.assertEqual(['p0610'],[r['id'] for r in result['rows']]);self.assertTrue(self.tools.pages_window({'query':'Rare surname','locate':'p0001'})['locate_missing']);self.assertEqual([],self.tools.pages_window({'query':'no such name'})['rows'])

    def test_recognition_book_ids_are_complete_and_ignore_loaded_window(self):
        self.assertEqual(250,len(self.tools.book_page_ids({'page':'p0001'})))
        book=self.tools.book_save({'name':'Photographed book','items':[{'page':'p0624'},{'page':'p0001'},{'page':None,'label':'Gap'},{'page':'p0250'}]})
        with self.engine.db:self.engine.db.execute("UPDATE pages SET status='done' WHERE id='p0001'")
        self.assertEqual(['p0624','p0250'],self.tools.book_page_ids({'page':'p0001'}));self.assertEqual(['p0624','p0001','p0250'],self.tools.book_page_ids({'page':'p0001','pending_only':False}))

    def test_person_lookup_scopes_current_records_and_keeps_staleness(self):
        people=GenealogyTools(self.engine);person=people.person_save({'name':'Anna'})['id'];record=self.engine.save_record({'page':'p0624','kind':'Народження','person':'Anna','related1':'Paulus'})['id'];mention=people.mentions(records=[record])[0]
        self.assertEqual(2,len(people.person_mentions({'id':'p0624'})));self.assertEqual([],people.mentions(records=[]));self.assertEqual([],people.mentions(page='p0001',records=[record]))
        with patch.object(people,'mentions',wraps=people.mentions) as scoped:
            people.person_attach({'person':person,'mention':mention,'signature':mention['signature'],'note':'Read source'});self.assertTrue(all(call.kwargs.get('records') is not None for call in scoped.call_args_list))
        self.engine.save_record({'id':record,'page':'p0624','kind':'Народження','person':'Anne'})
        card=people.person_card({'id':person});self.assertTrue(card['members'][0]['stale']);self.assertEqual('Anne',card['members'][0]['current']['name']);self.assertEqual('Anna',card['members'][0]['mention']['name'])

    def test_same_count_photo_reorder_changes_snapshot_even_when_rowids_reused(self):
        book=self.tools.book_save({'name':'Same count','items':[{'page':'p0001'},{'page':'p0250'},{'page':'p0500'}]})
        before=self.tools.pages_window({})
        old_ids=[r[0] for r in self.engine.db.execute('SELECT rowid FROM book_items ORDER BY rowid')]
        self.tools.book_save({'book':book['id'],'name':'Same count','items':[{'page':'p0500'},{'page':'p0001'},{'page':'p0250'}]})
        self.assertEqual(old_ids,[r[0] for r in self.engine.db.execute('SELECT rowid FROM book_items ORDER BY rowid')])
        after=self.tools.pages_window({'snapshot':before['snapshot']})
        self.assertTrue(after['snapshot_changed']);self.assertNotEqual(before['snapshot'],after['snapshot'])
        self.assertEqual(['p0500','p0001','p0250'],[r['id'] for r in after['rows'] if r.get('book')==book['id']])

    def test_snapshot_detects_other_connection_status_and_same_count_query_swaps(self):
        with self.engine.db:self.engine.db.execute("UPDATE pages SET text='rare query' WHERE id='p0001'")
        before=self.tools.pages_window({'query':'rare query'})
        other=Engine(self.engine.root)
        try:
            with other.db:
                other.db.execute("UPDATE pages SET text='' WHERE id='p0001'")
                other.db.execute("UPDATE pages SET text='rare query',status='done' WHERE id='p0002'")
        finally:other.db.close()
        after=self.tools.pages_window({'query':'rare query','snapshot':before['snapshot']})
        self.assertEqual(1,before['total']);self.assertEqual(1,after['total']);self.assertTrue(after['snapshot_changed'])
        self.assertEqual(['p0002'],[r['id'] for r in after['rows']]);self.assertEqual('done',after['rows'][0]['status'])
        stable=self.tools.pages_window({'query':'rare query','snapshot':after['snapshot']});self.assertFalse(stable['snapshot_changed'])
