"""Show actual source-linked CATMuS outputs without certifying transcription."""
import html,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];p=root/'test-output/accuracy-improvement'
small=json.loads((p/'catmus-latin.json').read_text('utf-8'));full=json.loads((p/'catmus-latin-full-page.json').read_text('utf-8'));medium=json.loads((p/'medium-native-lines.json').read_text('utf-8'))
rows=''
for row in small['rows']:
 n=row['line'];text='\n'.join(r['text'] for r in row['result'])
 image=(root/f'test-output/gologory-surname-review/inputs/entry-line{n}.png').as_uri()
 rows+=f'<tr><td><img style="max-width:100%" src="{image}"></td><td>{html.escape(text)}</td></tr>'
body=f'''<meta charset="utf-8"><title>CATMuS — латинський документ</title><h1>CATMuS Medieval: справжній латинський документ</h1>
<p>Zenodo 21488839 (запис 1.6.2, файл моделі 1.6.0). Середньовічна модель; ця пізніша метрична книга виходить за типовий період навчання. Еталона немає, точність не виміряна. Помилки залишаються.</p>
<h2>Три справжні рядки</h2><table border="1"><tr><th>Оригінал</th><th>Неперевірений CATMuS</th></tr>{rows}</table>
<h2>Ціла сторінка: {full['seconds']:.1f} с, {len(full['lines'])} отриманих ділянок</h2>
<p>Кількість ділянок не доводить повноти прочитання.</p><img style="width:60%" src="../gologory-source-research/PL_1_301_334_0003.jpg">
<pre style="white-space:pre-wrap">{html.escape(chr(10).join(r['text'] for r in full['lines']))}</pre>
<h2>Попередній PP-OCRv6 medium на тих самих трьох рядках</h2><pre style="white-space:pre-wrap">{html.escape(json.dumps(medium,ensure_ascii=False,indent=2))}</pre>'''
(p/'catmus-report.html').write_text(body,'utf-8')
