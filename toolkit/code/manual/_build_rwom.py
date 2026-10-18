"""Temporary: build RWoM csproj via dotnet, report errors only."""
import subprocess
from pathlib import Path

PROJ = Path(r"D:\Programs\UnityAiDevSystem\RimWorld\PatchApplier\RWoM-main\RimWorldOfMagic\RimWorldOfMagic\RimWorldOfMagic.csproj")
r = subprocess.run(
    ["dotnet", "build", str(PROJ), "-c", "Debug", "-v", "quiet", "--nologo",
     "-p:WarningLevel=0"],
    capture_output=True, text=True, timeout=300,
)
print("rc =", r.returncode, flush=True)
for line in (r.stdout or "").splitlines():
    if "error" in line.lower() or "ошиб" in line.lower():
        print(line, flush=True)
print("--- tail ---", flush=True)
print("\n".join((r.stdout or "").splitlines()[-6:]), flush=True)
