import subprocess, sys

def run(cmd, cwd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=cwd)

tl = 'D:/Programs/UnityAiDevSystem/PatchAppliers/PatchApplier'

out = run(['git', 'status', '--short'], tl)
print('=== status ===')
print(out.stdout.rstrip('\n') or '(clean)')

out = run(['git', 'add', '-A'], tl)
print('')
print('git add rc:', out.returncode)

msg = 'chore: remove temp leftover, harden inline-code tempfile cleanup\n\n- run_python(code=...): retry unlink with small sleeps (Windows AV lock)\n'
out = run(['git', 'commit', '-m', msg], tl)
print('')
print('commit rc:', out.returncode)
print(out.stdout.rstrip('\n'))
if out.stderr.strip():
    print('stderr:', out.stderr.strip()[:300])

out = run(['git', 'log', '--oneline', '-1'], tl)
print('HEAD:', out.stdout.strip())
