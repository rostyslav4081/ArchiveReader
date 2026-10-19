"""Prepare reviewable fact assessments in the isolated lab; never confirm kinship."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.fact_review import FactReviewTools

def main():
    e=Engine(ROOT/'test-output/htr-lab-20261015/library');tools=FactReviewTools(e);report=[]
    try:
        ids=['6dea91291cb75ce38b745836cc35b68d','4747a5864a3e5f0bb0e71aca906518f6','6eb02de1e66f51a2b31973d1cc8759a4','beb20d9cb3dc5fc4865a34e35dfabc50']
        for record in ids:
            view=tools.fact_reviews({'record':record});source=view['source'];bounds=next((r['rect'] for r in source['regions'] if r.get('rect')),None)
            for field in ['person','date','house','age']:
                fact=next(f for f in view['facts'] if f['field']==field)
                if fact['assessment'] or not fact['value']:continue
                state='document_observation' if field in ['house','age'] else 'transcription'
                note='Тестова попередня оцінка за архівним зображенням. Прочитання асистента потребує вашої перевірки; це не підтвердження тотожності людей.'
                tools.fact_save({'record':record,'field':field,'value':fact['value'],'status':state,'note':note,'signature':source['signature'],'rect':bounds})
            if record==ids[1] and not next(f for f in view['facts'] if f['field']=='kinship')['assessment']:
                tools.fact_save({'record':record,'field':'kinship','value':'Ignatius Skowyra може бути братом Philippus Skowyra','status':'hypothesis','note':'Припущення користувача: спільний будинок №34. Імена батьків обох чоловіків та інші незалежні докази ще не встановлені. Спорідненість не підтверджена.','signature':source['signature'],'rect':bounds})
            report.append({'record':record,'assessed':sum(bool(v['assessment']) for v in tools.fact_reviews({'record':record})['facts'])})
        (ROOT/'test-output/philip-source-research/fact-review-seed.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print('Prepared assessments for '+str(len(report))+' test records')
    finally:e.db.close()

if __name__=='__main__':main()
