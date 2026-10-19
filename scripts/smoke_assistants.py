"""Render actual assistant windows using isolated synthetic data, never live data."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.archivereader.engine import Engine
from backend.archivereader.tutor import TutorTools
from backend.archivereader.agents import AgentTools
from backend.archivereader.board_import import BoardTools


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--language',choices=['uk','en','pl','cs']);args=parser.parse_args()
    output=ROOT/'test-output'/'ui-assistants';output.mkdir(parents=True,exist_ok=True)
    source=output/'synthetic.png';image=Image.new('RGB',(1200,500),'#fffdf4');draw=ImageDraw.Draw(image)
    draw.text((80,80),'SYNTHETIC TEST — NOT AN ARCHIVAL SOURCE\nJoannes filius Pauli et Annae. Domus 34.',font=ImageFont.truetype('C:/Windows/Fonts/times.ttf',38),fill='black',spacing=40);image.save(source)
    for language in ([args.language] if args.language else ['uk','en','pl','cs']):
        folder=output/language;engine=Engine(folder);engine.import_file({'path':str(source)});page=engine.list_pages({})[0]['id']
        tutor=TutorTools(engine)
        if not tutor.tutor_lessons({'id':page}):tutor.tutor_save({'id':page,'rect':[.05,.3,.88,.16],'text':'Joannes filius Pauli et Annae. Domus 34.','verified':True,'notes':'Synthetic human-confirmed fixture only.'})
        agents=AgentTools(engine)
        if not agents.agent_jobs({'page':page}):
            region=agents.annotations({'id':page})[0];report={'rows':[{'id':region['id'],'results':{'A':{'text':'Joannes filius Pauli'},'B':{'text':'Joannes filius Pauli et Annae'}}}],'models':[]}
            agents.write_job('synthetic-job',{'page':page,'annotation':region['id'],'snapshot':'synthetic','models':[],'identities':[],'state':'review','stages':{'recognition':report},'verified':False},'synthetic fixture; inference not run')
        board=BoardTools(engine)
        if not board.board_list({}):
            snapshot={'fileKey':'synthetic-only','pageId':'0:1','nodes':[{'id':'p1','type':'SHAPE_WITH_TEXT','text':'Joannes\nSynthetic person\n1832–?','x':40,'y':40,'width':240,'height':150,'images':[]},{'id':'p2','type':'SHAPE_WITH_TEXT','text':'Paulus\nSynthetic person','x':440,'y':40,'width':240,'height':150,'images':[]},{'id':'note','type':'TEXT','text':'Synthetic board. Connector is not proof of kinship.','x':70,'y':300,'width':600,'height':70},{'id':'edge','type':'CONNECTOR','start':{'endpointNodeId':'p1'},'end':{'endpointNodeId':'p2'}}]}
            path=folder/'synthetic-board.json';path.write_text(json.dumps(snapshot),encoding='utf8');preview=board.board_preview({'path':str(path)});board.board_import({'path':str(path),'sha':preview['sha'],'people':['p1','p2']})
        engine.db.close()
        env=os.environ.copy();env.update(ARCHIVEREADER_DATA=str(folder),ARCHIVEREADER_LANGUAGE=language,ARCHIVEREADER_PYTHON=sys.executable)
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        subprocess.run([str(ROOT/'bin/Release/net10.0-windows/ArchiveReader.exe'),'--smoke-test','--smoke-tutor','--smoke-agents','--smoke-board'],env=env,startupinfo=startup,check=True,timeout=150)
        expected=[folder/'window.png',folder/'agents-ui/workflow.png',folder/'board-ui/board.png']+[folder/'tutor-ui'/f'tab-{i}.png' for i in range(3)]
        if not all(path.is_file() for path in expected):raise RuntimeError('Missing assistant UI render: '+language)
        print(language+': OK',flush=True)

if __name__=='__main__':main()
