import json,html
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'test-output/accuracy-improvement'
r=json.loads((p/'lighton-polish-line.json').read_text('utf-8'))
previous=json.loads((p/'polish-candidate-comparison.json').read_text('utf-8'))['rows'][0]
body=f'''<meta charset="utf-8"><title>IHPAN LightOnOCR — реальний тест</title>
<h1>IHPAN LightOnOCR: реальний польський рукопис</h1>
<p>Експериментальний рушій встановлено локально. Еталона немає, точність не виміряна.</p>
<p>Ціла сторінка: тест зупинено після понад шести хвилин без результату на CPU.</p>
<p>Один рядок: {r['seconds']:.1f} с. Досягнуто ліміту, текст відхилено й не застосовано. Повторювані дати не є встановленими фактами.</p>
<img style="max-width:100%" src="polish-line-1.png">
<h2>LightOnOCR — відхилений частковий текст</h2><pre style="white-space:pre-wrap">{html.escape(r['text'])}</pre>
<h2>PP-OCRv6 medium — також неперевірений текст</h2><p>{html.escape(previous['medium'])}</p>
<h2>Polish metrical — також неперевірений текст</h2><p>{html.escape(previous['polish_experimental'].get('text',''))}</p>'''
(p/'lighton-report.html').write_text(body,'utf-8')
