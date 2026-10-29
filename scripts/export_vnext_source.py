"""Export committed product source and its self-contained regression helpers.

No worktree data, environments, model records or uncommitted files are copied.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


PATHS = (
    'app', 'tests/vnext', 'tests/v2_test_support.py',
    'tests/agent_v2/test_a1_draft_delivery.py',
    'tests/agent_v2/test_continuous_generation_handoff.py',
    'tests/agent_v2/test_controller_v2.py',
    'tests/agent_v2/test_evidence_relevance.py',
    'tests/agent_v2/test_generation_v2.py',
    'tests/api_v2/helpers.py', 'tests/api_v2/test_identity_boundary_api.py',
    'tests/fixtures/a1_mapping', 'tests/fixtures/vnext',
    'examples/esa', 'docs/esa-vnext', 'README.md', 'AGENTS.md',
    'pyproject.toml', 'uv.lock', '.gitignore', 'LICENSE',
    'scripts/export_vnext_source.py',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--output-dir', default='.private/esa-vnext/build')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    def git(*parts):
        return subprocess.check_output(['git', *parts], cwd=root, text=True).strip()
    commit = git('rev-parse', '--verify', args.ref + '^{commit}')
    paths = [p for p in PATHS if git('ls-tree', commit, '--', p)]
    destination = (root / args.output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / ('ESA_0.2.0_source_' + commit[:8] + '.zip')
    if archive.exists():
        raise FileExistsError(archive)
    subprocess.run(['git', 'archive', '--format=zip', '--output', str(archive), commit, *paths], cwd=root, check=True)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert 'tests/api_v2/helpers.py' in zipped.namelist()
        assert not any('/.private/' in n or n.endswith('.sqlite3') for n in zipped.namelist())
    result = {'commit': commit, 'archive': str(archive), 'bytes': archive.stat().st_size,
              'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
    (destination / ('EXPORT_' + commit[:8] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
