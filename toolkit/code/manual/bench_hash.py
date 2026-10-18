"""Benchmark file-content hashes on .cs files.

Usage: python bench_hash.py [root]
If root not given, walks up from cwd to find a directory containing RimWorld/.
"""
import os
import sys
import time
import hashlib
import zlib


def find_root():
    if len(sys.argv) > 1:
        return sys.argv[1]
    here = os.path.abspath(os.getcwd())
    for _ in range(6):
        cand = os.path.join(here, "RimWorld")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


def find_cs(root):
    out = []
    for dp, dns, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".cs"):
                out.append(os.path.join(dp, fn))
    return out


def load(files):
    out = []
    for p in files:
        try:
            with open(p, "rb") as f:
                out.append((p, f.read()))
        except OSError as e:
            print(f"skip {p}: {e}")
    return out


def timeit(data, func, reps=3):
    best = None
    for _ in range(reps):
        t0 = time.perf_counter()
        acc = 0
        for _, d in data:
            acc ^= func(d)
        dt = time.perf_counter() - t0
        if best is None or dt < best:
            best = dt
    return best


def main():
    root = find_root()
    if not root or not os.path.isdir(root):
        print(f"root not found: {root}")
        return 1
    files = find_cs(root)
    if not files:
        print(f"no .cs under {root}")
        return 1
    print(f"root: {root}")
    print(f"files: {len(files)}")
    total_bytes = sum(os.path.getsize(p) for p in files)
    print(f"total: {total_bytes/1e6:.1f} MB")

    t0 = time.perf_counter()
    data = load(files)
    load_dt = time.perf_counter() - t0
    print(f"read: {load_dt:.3f}s")
    print()

    hashers = [
        ("crc32", lambda d: zlib.crc32(d)),
        ("blake2b-8", lambda d: int.from_bytes(hashlib.blake2b(d, digest_size=8).digest(), "big")),
        ("blake2b-16", lambda d: int.from_bytes(hashlib.blake2b(d, digest_size=16).digest(), "big")),
        ("sha256-16", lambda d: hashlib.sha256(d).hexdigest()[:16]),
        ("sha1-16", lambda d: hashlib.sha1(d).hexdigest()[:16]),
    ]

    base = None
    print(f"{'hash':14s} {'best-of-3':>10s} {'vs crc32':>10s} {'MB/s':>10s}")
    for name, fn in hashers:
        dt = timeit(data, fn)
        mbps = total_bytes / 1e6 / dt if dt else 0
        if name == "crc32":
            base = dt
        ratio = (dt / base) if base else 0
        print(f"{name:14s} {dt:>9.3f}s {ratio:>9.2f}x {mbps:>9.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
