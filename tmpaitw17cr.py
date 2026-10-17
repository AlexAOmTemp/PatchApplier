import subprocess, sys
from pathlib import Path

def run(cmd, cwd=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=cwd)
    except Exception as e:
        print(f'{type(e).__name__}: {e}')
        return None

out = run(['git', 'rev-parse', '--show-toplevel'])
if out is None or out.returncode != 0:
    print('no git repo'); sys.exit(1)
tl = Path(out.stdout.strip())
print('toplevel:', tl)

gitignore = tl / '.gitignore'
existing = gitignore.read_text(encoding='utf-8') if gitignore.exists() else ''
print('')
print('=== .gitignore before ===')
print(existing or '(empty)')

new_lines = [
    'toolkit/code/bridge/bridge_timings.log',
    'toolkit/code/toolkit/runner/last_diff.txt',
    'toolkit/code/toolkit/runner/last_output.txt',
    'toolkit/code/toolkit/runner/last_patch.json',
    '__pycache__/',
    '*.pyc',
    '*.pyo',
]
to_add = [ln for ln in new_lines if ln not in existing]
if to_add:
    if existing and not existing.endswith('\n'):
        existing += '\n'
    existing += '\n# runtime artifacts (session-local)\n' + '\n'.join(to_add) + '\n'
    gitignore.write_text(existing, encoding='utf-8')
    print('')
    print('=== .gitignore added ===')
    for ln in to_add:
        print(' ', ln)
else:
    print('')
    print('=== .gitignore unchanged (all present) ===')

out = run(['git', 'status', '--short'], cwd=tl)
print('')
print('=== git status ===')
print(out.stdout.rstrip('\n') or '(clean)')

msg = 'checkpoint before backend rename\n\n- refactor(toolkit): split replace/create/remove, fix run_python, add tree\n- backends: resolve_physical in FilesystemBackend/WorkspaceBackend/CompositeBackend\n- unit model: replace_unit replace-only; create_unit for annotation; remove_unit for part=all and block=N\n- tools: new tree tool (DFS pre-order, max_dirs cap, frontier_unexpanded)\n- grep: directory in paths -> bad_options\n- docs: LLM_START.ru sync (sources model pending rename)\n- tests: test_run_python_symmetry, test_tree_tool, test_grep_paths + unit_model create/remove\n- .gitignore: ignore runtime artifacts\n'
out = run(['git', 'add', '-A'], cwd=tl)
if out.returncode != 0:
    print('git add failed:', out.stderr[:500]); sys.exit(1)

out = run(['git', 'commit', '-m', msg], cwd=tl)
print('')
print('=== commit ===')
print('rc:', out.returncode)
print(out.stdout.rstrip('\n'))
if out.stderr.strip():
    print('stderr:', out.stderr.strip()[:300])

out = run(['git', 'log', '--oneline', '-1'], cwd=tl)
print('HEAD:', out.stdout.strip())
