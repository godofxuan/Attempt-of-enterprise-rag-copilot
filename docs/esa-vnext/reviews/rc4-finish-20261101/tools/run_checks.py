"""Run the self-contained supplement against a real source checkout, with temp data only."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True, help='Root containing app/')
    parser.add_argument('--output', type=Path, default=Path('rc4-check-results'))
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    if not (source / 'app' / 'workbench_app.py').is_file():
        parser.error('--source must be the actual project root containing app/workbench_app.py')
    if sys.version_info[:2] not in {(3, 11), (3, 12)}:
        print('WARNING: this interpreter is outside project-supported Python 3.11/3.12; results are not release compatibility proof.', file=sys.stderr)
    tests = Path(__file__).resolve().parents[1] / 'tests'
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'ESA_SOURCE': str(source), 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1'}
    env['PYTHONPATH'] = os.pathsep.join([str(tests), str(source), env.get('PYTHONPATH', '')])
    cmd = [sys.executable, '-m', 'pytest', str(tests / 'test_rc4_product.py'), '-q', '--junitxml=' + str(output / 'results.xml')]
    completed = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding='utf-8')
    text = completed.stdout + completed.stderr
    (output / 'results.log').write_text(text, encoding='utf8')
    print(text)
    return completed.returncode


if __name__ == '__main__':
    raise SystemExit(main())
