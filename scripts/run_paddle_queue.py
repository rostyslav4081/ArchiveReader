"""Sequential local Paddle controls for the supplied Gologory manifests."""
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / 'integration-envs/paddle-stable/Scripts/python.exe'


def wait_for(predicate, description, timeout=3600):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError(description)
        time.sleep(5)


def main():
    marriage = ROOT / 'test-output/integrations/gologory-paddle/report.json'
    wait_for(lambda: marriage.exists() and json.loads(marriage.read_text(encoding='utf8')).get('status') == 'complete',
             'Existing marriage run did not complete; no overlapping model process started')
    outcomes = []
    for unit, output in [(334, 'gologory-deaths-paddle'), (331, 'gologory-331-paddle'),
                         (333, 'gologory-333-paddle'), (335, 'gologory-335-paddle'),
                         (336, 'gologory-336-paddle')]:
        manifest = ROOT / f'test-output/gologory-301-{unit}/cases.json'
        wait_for(manifest.exists, f'Manifest not ready: {manifest}')
        # Parse the complete manifest before starting inference; preparation writes atomically.
        count = len(json.loads(manifest.read_text(encoding='utf8'))['cases'])
        directory = ROOT / 'test-output/integrations' / output
        log = directory.with_name(directory.name + '-run.log')
        print(f'Starting unit {unit}: {count} real pages', flush=True)
        with log.open('w', encoding='utf8') as stream:
            result = subprocess.run([str(PYTHON), '-X', 'utf8', str(ROOT / 'scripts/test_paddle_integration.py'),
                                     '--manifest', str(manifest), '--output', str(directory),
                                     '--retry-errors', '--mkldnn'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        report_path = directory / 'report.json'
        report = json.loads(report_path.read_text(encoding='utf8')) if report_path.exists() else {}
        outcome = {'unit': unit, 'exit_code': result.returncode, 'report': str(report_path),
                   'status': report.get('status'), 'summary': report.get('summary', {})}
        outcomes.append(outcome)
        (ROOT / 'test-output/integrations/gologory-queue.json').write_text(
            json.dumps(outcomes, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(outcome), flush=True)
        if result.returncode or report.get('status') != 'complete':
            raise RuntimeError(f'Unit {unit} incomplete; queue stopped, evidence retained')


if __name__ == '__main__':
    main()
