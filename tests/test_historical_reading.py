from tests.support import workspace_tempdir
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from backend.archivereader.engine import Engine
from backend.archivereader.historical_reading import HistoricalTools,ROLES
from backend.archivereader.books import BookTools
class HistoricalReadingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=workspace_tempdir();self.root=Path(self.tmp.name);self.e=Engine(self.root/'library');self.h=HistoricalTools(self.e);self.source=self.root/'one.png';im=Image.new('RGB',(400,300),'white');ImageDraw.Draw(im).rectangle((50,50,180,150),fill='black');im.save(self.source);self.e.import_file({'path':str(self.source)});self.page=self.e.list_pages({})[0]['id'];self.annotation=self.h.save_annotation({'page':self.page,'data':{'kind':'line','rect':[.1,.1,.8,.6],'text':'Joannes János Joannis ignotus','verified':False}})['id']
 def tearDown(self):self.e.db.close();self.tmp.cleanup()
 def term(self,form='Joannes',lemma='Іван',language='la',**kwargs):return self.h.historical_term({'page':self.page,'form':form,'lemma':lemma,'meaning':'Human declared name equivalent','language':language,'note':'Personally checked on this book','checked':True,'kind':'name'}|kwargs)
 def analyze(self):return self.h.historical_analyze({'page':self.page,'annotation':self.annotation})
 def decide(self,**values):return self.h.historical_decide({'page':self.page,'annotation':self.annotation,'signature':self.analyze()['signature'],'reading':'Joannes János','interpretation':'Separate modern explanation','note':'Human reviewed source','checked':True,'uncertain':False}|values)
 def comparison(self):
  crop=Path(self.h.region_crop({'id':self.page,'annotation':self.annotation})['path']);folder=self.e.root/'results'/'historical-comparison';folder.mkdir(parents=True,exist_ok=True);image=folder/'line.png';image.write_bytes(crop.read_bytes());case={'id':self.annotation,'image':'line.png','image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'document':self.e.page(self.page)['doc'],'page':1,'rect':[.1,.1,.8,.6]};manifest=folder/'manifest.json';manifest.write_text(json.dumps([case]),'utf-8');report=folder/'report.json';report.write_text(json.dumps({'rows':[case|{'results':{'Latin':{'text':'Joannes','confidence':.8},'Hungarian':{'text':'János','confidence':.4}}}]}),'utf-8');self.e.db.execute('INSERT INTO comparison_runs(id,doc,path,manifest_sha) VALUES (?,?,?,?)',('history-run',case['document'],str(folder),hashlib.sha256(manifest.read_bytes()).hexdigest()));self.e.db.commit();return folder
 def test_profile_book_scope_and_stale_profile_version(self):
  second=self.root/'two.png';Image.new('RGB',(400,300),'yellow').save(second);self.e.import_file({'path':str(second)});other=self.e.list_pages({})[1]['id'];BookTools(self.e).book_save({'name':'Photo book','items':[{'page':self.page},{'page':other}]});old=self.h.historical_get({'page':self.page})['profile'];values={'origin':'Gologory','period':'1755–1795','institution':'Parish','rite':'Latin','script':'Latin cursive','writer':'Hand A','languages':['la','pl','hu'],'notes':'No ethnicity inferred'}
  saved=self.h.historical_profile({'page':self.page,'expected':old['signature'],'values':values});self.assertEqual(self.h.historical_get({'page':other})['profile']['values'],values);self.assertEqual(saved['values'],values)
  with self.assertRaises(ValueError):self.h.historical_profile({'page':self.page,'expected':old['signature'],'values':values})
 def test_crosslanguage_different_roots_explicit_only_and_historical_forms_preserved(self):
  before=self.h.annotations({'id':self.page});self.term(concept='given-name:Ivan');self.term('János',language='hu',concept='given-name:Ivan');self.term('supra',lemma='вище',language='la',kind='word');analysis=self.analyze();john=next(t for t in analysis['tokens'] if t['literal']=='Joannes');self.assertEqual(john['matches'][0]['form'],'Joannes');self.assertIn('János',[e['form'] for e in john['matches'][0]['equivalents']]);self.assertEqual(next(t for t in analysis['tokens'] if t['literal']=='ignotus')['matches'],[]);self.assertTrue(all(not t['unknown_is_error'] for t in analysis['tokens']));self.assertEqual(self.h.annotations({'id':self.page}),before);self.assertLessEqual(analysis['passes'],2)
  with self.assertRaises(ValueError):self.term('Nepotest',checked=False)
  self.assertEqual(self.h.historical_get({'page':self.page})['terms'][1]['form'],'János')
 def test_decision_audited_separate_not_gt_and_span_bounds(self):
  self.comparison();before=self.h.annotations({'id':self.page});analysis=self.analyze();self.assertEqual([x['text'] for x in analysis['alternatives']],['Joannes','János']);self.assertEqual(analysis['alternatives'][0]['raw_prediction']['confidence'],.8);self.assertIn('saved_model_variants_disagree',analysis['warnings']);decision=self.decide(spans=[{'start':0,'end':7,'language':'la'},{'start':8,'end':13,'language':'hu'}]);self.assertFalse(decision['verified']);self.assertFalse(decision['gt_eligible']);self.assertEqual(decision['spans'][0]['literal'],'Joannes');self.assertEqual(self.h.annotations({'id':self.page}),before);self.assertEqual(self.e.page(self.page)['text'],'');self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0);self.assertEqual(self.e.db.execute("SELECT COUNT(*) FROM historical_audit WHERE kind='decision'").fetchone()[0],1)
  with self.assertRaises(ValueError):self.decide(spans=[{'start':0,'end':999,'language':'pl'}])
  with self.assertRaises(ValueError):self.decide(checked=False)
 def test_stale_context_comparison_and_actual_source_change_rejected(self):
  folder=self.comparison();analysis=self.analyze();self.term()
  with self.assertRaises(ValueError):self.decide(signature=analysis['signature'])
  current=self.analyze();self.decide(signature=current['signature']);report=folder/'report.json';data=json.loads(report.read_text('utf-8'));data['rows'][0]['results']['Latin']['text']='Joannis';report.write_text(json.dumps(data),'utf-8');self.assertTrue(self.h.historical_get({'page':self.page})['decisions'][0]['stale'])
  with self.assertRaises(ValueError):self.decide(signature=current['signature'])
  Path(self.e.page(self.page)['path']).write_bytes(b'changed original')
  with self.assertRaises(ValueError):self.h.historical_get({'page':self.page})
 def test_damaged_reading_is_uncertain_and_never_gt(self):
  self.h.historical_layout({'page':self.page,'role':'damage','rect':[.2,.2,.1,.1],'note':'Torn paper','checked':True});self.assertTrue(self.analyze()['damaged'])
  with self.assertRaises(ValueError):self.decide(uncertain=False)
  d=self.decide(reading='Joannes [...]',uncertain=True);self.assertFalse(d['gt_eligible']);self.assertFalse(d['verified']);self.assertFalse(self.h.annotations({'id':self.page})[0]['verified'])
 def test_exemplar_real_pixels_persist_rehydrate_and_guard_bounds(self):
  before=self.h.annotations({'id':self.page});r=self.h.historical_exemplar({'page':self.page,'annotation':self.annotation,'rect':[.15,.2,.1,.15],'label':'ſ','note':'Observed long s, not a model label','checked':True});self.assertFalse(r['automatic_training']);self.assertFalse(r['gt_eligible']);self.assertEqual(hashlib.sha256(Path(r['path']).read_bytes()).hexdigest(),r['crop_sha256'])
  with Image.open(r['path']) as crop:self.assertEqual(crop.convert('RGB').tobytes(),self.h.whole_image(self.page).crop(tuple(r['pixel_box'])).tobytes())
  Path(r['path']).unlink();got=self.h.historical_get({'page':self.page})['exemplars'][0];self.assertTrue(Path(got['path']).is_file());self.assertEqual(self.h.annotations({'id':self.page}),before)
  with self.assertRaises(ValueError):self.h.historical_exemplar({'page':self.page,'annotation':self.annotation,'rect':[.01,.01,.05,.05],'label':'x','note':'outside','checked':True})
 def test_exemplar_transaction_recheck_rolls_back_after_region_moves(self):
  original=self.h.whole_image
  def moved(page):
   result=original(page);self.h.save_annotation({'page':page,'annotation':self.annotation,'data':{'kind':'line','rect':[.2,.1,.7,.6],'text':'changed'}});return result
  with patch.object(self.h,'whole_image',side_effect=moved):
   with self.assertRaises(ValueError):self.h.historical_exemplar({'page':self.page,'annotation':self.annotation,'rect':[.25,.2,.1,.1],'label':'a','note':'stale view','checked':True})
  self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM historical_exemplars').fetchone()[0],0)
 def test_all_layout_roles_are_manual_metadata_without_ocr_exclusion(self):
  old=self.h.historical_get({'page':self.page})['signature'];before=self.h.annotations({'id':self.page})
  for role in ROLES:
   r=self.h.historical_layout({'page':self.page,'role':role,'rect':[.1,.1,.5,.4],'note':'Explicit role review','checked':True});self.assertFalse(r['automatic_ocr_exclusion'])
  self.assertEqual(len(self.h.historical_get({'page':self.page})['layout']),6);self.assertEqual(self.h.annotations({'id':self.page}),before)
  with self.assertRaises(ValueError):self.h.historical_layout({'page':self.page,'role':'text','rect':[.1,.1,.5,.4],'note':'stale','checked':True,'expected':old})
  with self.assertRaises(ValueError):self.h.historical_layout({'page':self.page,'role':'imagined','rect':[.1,.1,.5,.4],'note':'bad','checked':True})
 def test_comparison_changed_crop_not_used(self):
  folder=self.comparison();Image.new('RGB',(10,10),'blue').save(folder/'line.png');analysis=self.analyze();self.assertEqual(analysis['alternatives'],[]);self.assertIn('stale_comparison_ignored',analysis['warnings'])
 def test_structure_proposal_bound_preview_never_saves_roles(self):
  before=self.h.historical_get({'page':self.page});proposal={'candidates':[{'role':'table','rect':[.1,.1,.8,.6],'verified':False,'confidence':None,'method':'ruled_grid_heuristic','evidence':{},'warning':'review'}],'policy':'No semantic claims'}
  with patch('backend.archivereader.structure_proposals.suggest_structure',return_value=proposal):r=self.h.historical_structure_propose({'page':self.page})
  self.assertEqual(r['signature'],before['signature']);self.assertEqual(r['source_sha256'],before['source_sha256']);self.assertFalse(r['saved']);self.assertEqual(self.h.historical_get({'page':self.page})['layout'],[]);self.assertFalse(r['candidates'][0]['verified'])
 def test_same_token_multiple_languages_stays_ambiguous_and_profile_is_only_context(self):
  self.h.save_annotation({'page':self.page,'annotation':self.annotation,'data':{'kind':'line','rect':[.1,.1,.8,.6],'text':'dom Joannis'}})
  self.term('dom',lemma='будинок',language='pl',meaning='House in an explicit Polish context',kind='word',writer='Hand B');self.term('dom',lemma='dominus',language='la',meaning='Declared Latin abbreviation, not automatic expansion',kind='abbreviation',writer='Hand A');self.term('Joannes',lemma='Іван',language='la')
  profile=self.h.historical_get({'page':self.page})['profile'];self.h.historical_profile({'page':self.page,'expected':profile['signature'],'values':{'writer':'Hand A','languages':['la','pl']}});analysis=self.analyze();token=next(t for t in analysis['tokens'] if t['literal']=='dom');self.assertEqual({'la','pl'},{m['language'] for m in token['matches']});self.assertTrue(any(m['context_applicability']['writer']=='different_declared_context' for m in token['matches']));self.assertEqual(analysis['original']['text'],'dom Joannis');joannis=next(t for t in analysis['tokens'] if t['literal']=='Joannis');self.assertTrue(any(m['match_type']=='fuzzy_form_suggestion' for m in joannis['matches']));self.assertFalse(analysis['gt_eligible'])
 def test_book_term_visible_across_photo_pages_without_leaking_to_other_book(self):
  second=self.root/'two.png';third=self.root/'three.png';Image.new('RGB',(400,300),'yellow').save(second);Image.new('RGB',(400,300),'green').save(third);self.e.import_file({'path':str(second)});self.e.import_file({'path':str(third)});pages=self.e.list_pages({});BookTools(self.e).book_save({'name':'Shared book','items':[{'page':self.page},{'page':pages[1]['id']}]});self.term();self.assertEqual(1,len(self.h.historical_get({'page':pages[1]['id']})['terms']));self.assertEqual([],self.h.historical_get({'page':pages[2]['id']})['terms'])
 def test_explicit_shared_concept_links_different_roots_not_crosslanguage_homographs(self):
  self.h.save_annotation({'page':self.page,'annotation':self.annotation,'data':{'kind':'line','rect':[.1,.1,.8,.6],'text':'pater gift'}})
  self.term('pater',lemma='pater',language='la',concept='kinship:father');self.term('apa',lemma='apa',language='hu',concept='kinship:father');self.term('Vater',lemma='Vater',language='de',concept='kinship:father');self.term('gift',lemma='gift',language='en',concept='object:present');self.term('Gift',lemma='gift',language='de',concept='substance:poison')
  analysis=self.analyze();father=next(t for t in analysis['tokens'] if t['literal']=='pater')['matches'][0];self.assertEqual({'apa','Vater'},{e['form'] for e in father['equivalents']});self.assertTrue(all(e['basis']=='human_shared_concept' for e in father['equivalents']))
  gifts=next(t for t in analysis['tokens'] if t['literal']=='gift')['matches'];self.assertTrue(any(m['language']=='en' for m in gifts));self.assertTrue(any(m['language']=='de' for m in gifts));self.assertTrue(all(not m['equivalents'] for m in gifts if m['form'] in ['gift','Gift']))
 def test_entry_analysis_and_decision_allowed_but_letter_exemplar_requires_line(self):
  self.h.save_annotation({'page':self.page,'annotation':self.annotation,'data':{'kind':'entry','rect':[.1,.1,.8,.6],'text':'pater\nJoannes'}})
  before=self.h.annotations({'id':self.page});analysis=self.analyze();self.assertEqual(analysis['original']['kind'],'entry');decision=self.decide(reading='pater\nJoannes');self.assertFalse(decision['gt_eligible']);self.assertEqual(self.h.annotations({'id':self.page}),before)
  with self.assertRaises(ValueError):self.h.historical_exemplar({'page':self.page,'annotation':self.annotation,'rect':[.15,.2,.1,.15],'label':'p','note':'Entry is not a saved parent line','checked':True})
 def test_visual_exemplars_require_explicit_same_hand_and_book_with_stale_guards(self):
  second=self.root/'two.png';Image.new('RGB',(400,300),'yellow').save(second);self.e.import_file({'path':str(second)});other=self.e.list_pages({})[1]['id'];BookTools(self.e).book_save({'name':'Hands book','items':[{'page':self.page},{'page':other}]});otherline=self.h.save_annotation({'page':other,'data':{'kind':'line','rect':[.1,.1,.8,.6],'text':'next line'}})['id']
  def profile(writer,notes=''):
   p=self.h.historical_get({'page':self.page})['profile'];return self.h.historical_profile({'page':self.page,'expected':p['signature'],'values':{'writer':writer,'notes':notes}})
  def exemplar():return self.h.historical_exemplar({'page':self.page,'annotation':self.annotation,'rect':[.15,.2,.1,.15],'label':'ſ','note':'Visually checked shape','checked':True})
  unknown=exemplar();self.assertEqual(self.analyze()['exemplars'],[])
  profile('Hand A');known=exemplar();profile('Hand B');exemplar();self.assertTrue(all(e['hand_label']=='Hand B' for e in self.analyze()['exemplars']))
  profile('Hand A');analysis=self.h.historical_analyze({'page':other,'annotation':otherline});self.assertEqual([known['id']],[e['id'] for e in analysis['exemplars']]);self.assertTrue(analysis['exemplars'][0]['applicable']);self.assertFalse(analysis['exemplars'][0]['automatic_training'])
  profile('Hand A','Changed period context');stale=self.h.historical_analyze({'page':other,'annotation':otherline})['exemplars'][0];self.assertIn('profile_changed',stale['stale_reasons']);self.assertFalse(stale['applicable'])
  Path(self.e.page(self.page)['path']).write_bytes(b'changed source photo');stale=self.h.historical_analyze({'page':other,'annotation':otherline})['exemplars'][0];self.assertIn('source_changed',stale['stale_reasons'])
  p=self.h.historical_get({'page':other})['profile'];self.h.historical_profile({'page':other,'expected':p['signature'],'values':{'writer':''}});self.assertEqual(self.h.historical_analyze({'page':other,'annotation':otherline})['exemplars'],[])
 def test_bound_term_stale_source_deleted_or_moved_region_is_not_a_suggestion(self):
  second=self.root/'two.png';Image.new('RGB',(400,300),'yellow').save(second);self.e.import_file({'path':str(second)});other=self.e.list_pages({})[1]['id'];BookTools(self.e).book_save({'name':'Lexical provenance book','items':[{'page':self.page},{'page':other}]});line=self.h.save_annotation({'page':other,'data':{'kind':'line','rect':[.1,.1,.8,.6],'text':'Joannes pater'}})['id'];bound=self.term(annotation=self.annotation,concept='name:Ivan');valid=self.term('pater',lemma='pater',concept='name:Ivan');source=Path(self.e.page(self.page)['path']);original=source.read_bytes();raw=self.e.db.execute('SELECT data FROM annotations WHERE id=?',(self.annotation,)).fetchone()['data']
  def analyze():return self.h.historical_analyze({'page':other,'annotation':line})
  self.assertTrue(any(m['term_id']==bound['id'] for t in analyze()['tokens'] for m in t['matches']))
  for change in ['source','delete','move']:
   with self.subTest(change=change):
    if change=='source':source.write_bytes(b'changed photo bytes')
    elif change=='delete':self.e.db.execute('DELETE FROM annotations WHERE id=?',(self.annotation,));self.e.db.commit()
    else:
     moved=json.loads(raw);moved['rect']=[.2,.1,.7,.6];self.e.db.execute('UPDATE annotations SET data=? WHERE id=?',(json.dumps(moved),self.annotation));self.e.db.commit()
    current=analyze();self.assertFalse(any(m['term_id']==bound['id'] for t in current['tokens'] for m in t['matches']));self.assertFalse(any(e['term_id']==bound['id'] for t in current['tokens'] for m in t['matches'] for e in m['equivalents']));saved=next(t for t in self.h.historical_get({'page':other})['terms'] if t['id']==bound['id']);self.assertTrue(saved['stale']);self.assertFalse(saved['applicable']);self.assertTrue(saved['stale_reasons']);self.assertEqual(saved['form'],'Joannes')
    source.write_bytes(original)
    if change=='delete':self.e.db.execute('INSERT INTO annotations(id,page,data) VALUES (?,?,?)',(self.annotation,self.page,raw))
    else:self.e.db.execute('UPDATE annotations SET data=? WHERE id=?',(raw,self.annotation))
    self.e.db.commit()
  self.assertTrue(next(t for t in self.h.historical_get({'page':other})['terms'] if t['id']==bound['id'])['applicable'])
 def test_manual_reference_preserves_dates_scope_literal_audit_and_exact_rule_hints(self):
  ref={'title':'Historical grammar','url':'https://example.org/work?edition=2','locator':'folio 12, paragraph 3','resource_type':'grammar','work_period':'1750?','witness_period':'copy ca 1800','edition_period':'1902','scope':'Latin parish registers, Galicia; applicability uncertain','authenticity':'Normative proposal, not proof of usage','checked':True}
  before=self.h.annotations({'id':self.page});saved=self.term(kind='orthography',reference=ref,concept='name:Ivan');self.term('János',language='hu',reference=ref,concept='name:Ivan');self.term('Joannis',kind='grammar',reference=ref);self.term('ignotus',kind='paleography',reference=ref)
  result=self.analyze();john=next(t for t in result['tokens'] if t['literal']=='Joannes')['matches'][0];self.assertEqual(john['reference'],ref);self.assertEqual(john['equivalents'][0]['reference'],ref);self.assertIn('reference_scope_requires_human_review',result['warnings']);self.assertEqual(next(t for t in self.h.historical_get({'page':self.page})['terms'] if t['id']==saved['id'])['reference'],ref);self.assertEqual(self.h.annotations({'id':self.page}),before)
  self.assertFalse(any(m['term_id']==saved['id'] for t in result['tokens'] if t['literal']=='Joannis' for m in t['matches']));audit=json.loads(self.e.db.execute("SELECT after FROM historical_audit WHERE entity=?",(saved['id'],)).fetchone()['after']);self.assertEqual(audit['reference'],ref);self.assertFalse(audit['gt_eligible'])
 def test_reference_invalid_url_unchecked_missing_locator_and_legacy_empty(self):
  self.assertEqual(self.term(reference={})['reference'],{});self.assertEqual(self.term('pater')['reference'],{})
  base={'title':'Work','url':'https://example.org','locator':'p. 3','checked':True}
  for values in [{'url':'file:///C:/book'},{'url':'https://name:password@example.org'},{'url':'javascript:alert(1)'},{'url':'https://example.org:bad'},{'url':'https://example.org/white space'},{'checked':False},{'locator':''}]:
   with self.subTest(values=values),self.assertRaises(ValueError):self.term(reference=base|values)
 def test_local_source_catalog_is_unchecked_listing_and_invalid_data_does_not_block(self):
  from backend.archivereader.historical_reading import reference_sources
  item={'id':'grammar-1','title':'Historical work','url':'https://example.org/grammar','scope':'Regional usage requires review','checked':True};catalog={'version':1,'sources':[item]};before=self.h.annotations({'id':self.page})
  with patch('backend.archivereader.historical_reading.Path.stat') as stat,patch('backend.archivereader.historical_reading.Path.read_text',return_value=json.dumps(catalog)):
   stat.return_value.st_size=500;rows,warnings=reference_sources()
  self.assertEqual(warnings,[]);self.assertEqual(rows[0]['title'],item['title']);self.assertFalse(rows[0]['checked']);self.assertTrue(rows[0]['listing_only']);self.assertFalse(rows[0]['auto_apply']);self.assertEqual(rows[0]['locator'],'')
  with patch('backend.archivereader.historical_reading.reference_sources',return_value=(rows,[])):
   view=self.h.historical_get({'page':self.page});self.assertEqual(view['reference_sources'],rows);self.assertEqual(view['terms'],[])
  self.assertEqual(self.h.annotations({'id':self.page}),before)
  for raw in ['not-json',json.dumps({'version':2,'sources':[]}),json.dumps({'version':1,'sources':[item|{'url':'file:///private'}]})]:
   with patch('backend.archivereader.historical_reading.Path.stat') as stat,patch('backend.archivereader.historical_reading.Path.read_text',return_value=raw):
    stat.return_value.st_size=500;rows,warnings=reference_sources();self.assertEqual(rows,[]);self.assertIn('reference_catalog_unavailable_or_invalid',warnings)
  with patch('backend.archivereader.historical_reading.reference_sources',return_value=([],['reference_catalog_unavailable_or_invalid'])):self.assertEqual(self.h.historical_get({'page':self.page})['warnings'],['reference_catalog_unavailable_or_invalid'])
 def test_package_book_scope_explicit_filter_stale_guard_audit_and_reset(self):
  second=self.root/'two.png';Image.new('RGB',(400,300),'yellow').save(second);self.e.import_file({'path':str(second)});other=self.e.list_pages({})[1]['id'];BookTools(self.e).book_save({'name':'Package book','items':[{'page':self.page},{'page':other}]});line=self.h.save_annotation({'page':other,'data':{'kind':'line','rect':[.1,.1,.8,.6],'text':'Joannes János'}})['id'];latin=self.term(concept='name:Ivan');hungarian=self.term('János',language='hu',concept='name:Ivan');initial=self.h.historical_package_get({'page':self.page});self.assertFalse(initial['configured']);analysis=self.analyze()
  source=initial['reference_sources'][0]['id'] if initial['reference_sources'] else None
  saved=self.h.historical_package_save({'page':self.page,'expected':initial['signature'],'term_ids':[latin['id']],'source_ids':[source] if source else [],'notes':'Only checked Latin reference applies here','checked':True});self.assertEqual(saved['term_ids'],[latin['id']]);self.assertEqual(self.h.historical_package_get({'page':other})['term_ids'],[latin['id']]);selected=self.h.historical_analyze({'page':other,'annotation':line});self.assertFalse(any(m['term_id']==hungarian['id'] for t in selected['tokens'] for m in t['matches']));self.assertFalse(any(e['term_id']==hungarian['id'] for t in selected['tokens'] for m in t['matches'] for e in m['equivalents']));self.assertEqual(self.e.db.execute("SELECT COUNT(*) FROM historical_audit WHERE kind='package'").fetchone()[0],1)
  if source:self.assertFalse(saved['selected_sources'][0]['checked'])
  with self.assertRaises(ValueError):self.decide(signature=analysis['signature'])
  with self.assertRaises(ValueError):self.h.historical_package_save({'page':self.page,'expected':initial['signature'],'term_ids':[],'checked':True})
  for values in [{'term_ids':['other-book-term']},{'source_ids':['missing-source']},{'checked':False}]:
   with self.subTest(values=values),self.assertRaises(ValueError):self.h.historical_package_save({'page':self.page,'expected':saved['signature'],'checked':True}|values)
  disabled=self.h.historical_package_save({'page':self.page,'expected':saved['signature'],'term_ids':[],'checked':True});self.assertTrue(all(not t['matches'] for t in self.analyze()['tokens']));self.h.historical_package_save({'page':self.page,'expected':disabled['signature'],'configured':False,'term_ids':[],'checked':True});self.assertTrue(any(t['matches'] for t in self.analyze()['tokens']))
 def test_word_inspection_exact_span_no_guessed_alignment_manual_crop_and_no_writes(self):
  self.comparison();self.term();before=self.h.annotations({'id':self.page});word=self.h.historical_word({'page':self.page,'annotation':self.annotation,'start':0,'end':7});self.assertEqual(word['literal'],'Joannes');self.assertEqual(word['crop']['geometry_basis'],'whole_saved_region');self.assertFalse(word['crop']['word_geometry_known']);self.assertEqual(word['alternatives'][0]['text'],'Joannes');self.assertEqual(word['alternatives'][0]['alignment'],'textual_only_no_pixel_alignment');self.assertEqual(word['tokens'][0]['matches'][0]['form'],'Joannes');self.assertFalse(word['saved']);self.assertEqual(self.h.annotations({'id':self.page}),before);self.assertEqual(self.e.db.execute('SELECT COUNT(*) FROM historical_decisions').fetchone()[0],0)
  cropped=self.h.historical_word({'page':self.page,'annotation':self.annotation,'start':0,'end':7,'rect':[.15,.2,.1,.15]});self.assertEqual(cropped['crop']['geometry_basis'],'human_manual_word_rect');self.assertEqual(hashlib.sha256(Path(cropped['crop']['path']).read_bytes()).hexdigest(),cropped['crop']['crop_sha256'])
  for values in [{'start':-1,'end':7},{'start':0,'end':1000},{'start':True,'end':7},{'start':0,'end':7,'rect':[0,0,.1,.1]}]:
   with self.subTest(values=values),self.assertRaises(ValueError):self.h.historical_word({'page':self.page,'annotation':self.annotation}|values)
 def test_legacy_lemma_equivalence_is_same_language_only(self):
  self.h.save_annotation({'page':self.page,'annotation':self.annotation,'data':{'kind':'line','rect':[.1,.1,.8,.6],'text':'pater'}});self.term('pater',lemma='pater',language='la');self.term('patris',lemma='pater',language='la');self.term('apa',lemma='pater',language='hu');match=next(t for t in self.analyze()['tokens'] if t['literal']=='pater')['matches'][0];self.assertEqual(['patris'],[e['form'] for e in match['equivalents']]);self.assertEqual(match['equivalents'][0]['basis'],'same_language_lemma')
if __name__=='__main__':unittest.main()
