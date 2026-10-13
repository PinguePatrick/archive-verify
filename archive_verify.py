"""Find reclaimable disk space and archive folders with proof that nothing was lost.

    python archive_verify.py plan <root>                     rebuildable folders and the largest folders under <root>
    python archive_verify.py pack <folder> --vault <dir>     zip one folder, then prove every file by SHA-256
    python archive_verify.py verify <pack.zip>               re-check a pack against its proof file
    python archive_verify.py unpack <pack.zip> <to>          restore into an empty folder

Nothing here deletes anything. The pack result prints the command to remove the original,
so a person makes that call after reading the proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zipfile

# Folders that come back from a requirements file or a rebuild, so they hold nothing unique.
REBUILDABLE = {".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
               ".mypy_cache", ".next", ".cache", ".parcel-cache", ".turbo", "Cache", "Code Cache", "GPUCache"}


def du(path: Path) -> tuple[int, int]:
    """Total bytes and file count under a folder."""
    size = files = 0
    for dirpath, _dirs, names in os.walk(path):
        for n in names:
            try:
                size += os.stat(os.path.join(dirpath, n)).st_size
                files += 1
            except OSError:
                pass
    return size, files


def rebuildable(root: Path) -> list[dict]:
    """Every rebuildable folder under root, outermost only."""
    out = []
    for dirpath, dirnames, _files in os.walk(root):
        keep = []
        for d in dirnames:
            if d in REBUILDABLE:
                size, files = du(Path(dirpath) / d)
                out.append({"path": (Path(dirpath) / d).relative_to(root).as_posix(), "bytes": size, "files": files})
            else:
                keep.append(d)
        dirnames[:] = keep
    return sorted(out, key=lambda r: -r["bytes"])


def top_folders(root: Path) -> list[dict]:
    out = []
    for p in root.iterdir():
        if p.is_dir():
            size, files = du(p)
            out.append({"path": p.name, "bytes": size, "files": files})
    return sorted(out, key=lambda r: -r["bytes"])


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha_member(z: zipfile.ZipFile, name: str) -> str:
    h = hashlib.sha256()
    with z.open(name) as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pack(folder: Path, vault: Path) -> dict:
    """Zip one folder (skipping rebuildable subfolders), then read every file back and compare hashes."""
    src = folder.resolve()
    if not src.is_dir():
        return {"ok": False, "why": f"{folder} is not a folder"}
    vault.mkdir(parents=True, exist_ok=True)
    target = vault / f"{src.name}.zip"
    if target.exists():
        return {"ok": False, "why": f"{target.name} already exists in the vault; nothing was changed"}
    tmp = target.with_suffix(".zip.tmp")
    hashes: dict[str, str] = {}
    skipped: list[str] = []
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True, strict_timestamps=False) as z:
        for dirpath, dirs, names in os.walk(src):
            skipped += [(Path(dirpath) / d).relative_to(src).as_posix() for d in dirs if d in REBUILDABLE]
            dirs[:] = [d for d in dirs if d not in REBUILDABLE]
            for n in names:
                full = Path(dirpath) / n
                rel = full.relative_to(src).as_posix()
                try:
                    hashes[rel] = sha_file(full)
                    z.write(full, rel)
                except OSError as exc:
                    z.close()
                    tmp.unlink(missing_ok=True)
                    return {"ok": False, "why": f"could not read {rel}: {exc}; nothing was changed"}
    with zipfile.ZipFile(tmp) as z:
        names = set(z.namelist())
        bad = [rel for rel, h in hashes.items() if rel not in names or sha_member(z, rel) != h]
    if bad:
        tmp.unlink(missing_ok=True)
        return {"ok": False, "why": f"{len(bad)} files did not read back identical; the pack was discarded", "first": bad[:5]}
    os.replace(tmp, target)
    original = sum((src / r).stat().st_size for r in hashes)
    proof = {"folder": src.name, "files": len(hashes), "original_bytes": original, "pack_bytes": target.stat().st_size,
             "proved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rebuildable_not_packed": skipped, "sha256": hashes}
    target.with_suffix(".proof.json").write_text(json.dumps(proof, indent=1), encoding="utf-8")
    return {"ok": True, "pack": target.name, "files": len(hashes), "rebuildable_not_packed": len(skipped),
            "original_bytes": original, "pack_bytes": proof["pack_bytes"],
            "remove_original_with": f'Remove-Item -LiteralPath "{folder}" -Recurse'}


def verify(pack_path: Path) -> dict:
    proof = json.loads(pack_path.with_suffix(".proof.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(pack_path) as z:
        names = set(z.namelist())
        bad = [rel for rel, h in proof["sha256"].items() if rel not in names or sha_member(z, rel) != h]
    return {"ok": not bad, "files": len(proof["sha256"]), "mismatched": bad[:5]}


def unpack(pack_path: Path, to: Path) -> dict:
    if to.exists() and any(to.iterdir()):
        return {"ok": False, "why": f"{to} is not empty; nothing was written"}
    with zipfile.ZipFile(pack_path) as z:
        z.extractall(to)
        return {"ok": True, "files": len(z.namelist())}


def mb(n: int) -> str:
    return f"{n / 1e6:,.1f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("root")
    p.add_argument("--top", type=int, default=10)
    k = sub.add_parser("pack")
    k.add_argument("folder")
    k.add_argument("--vault", required=True)
    v = sub.add_parser("verify")
    v.add_argument("pack")
    u = sub.add_parser("unpack")
    u.add_argument("pack")
    u.add_argument("to")
    args = ap.parse_args(argv)

    if args.cmd == "plan":
        root = Path(args.root)
        rows = rebuildable(root)
        print(f"Rebuildable folders under {args.root}: {mb(sum(r['bytes'] for r in rows))} MB in {len(rows)} folders")
        for r in rows[:args.top]:
            print(f"  {mb(r['bytes']):>10} MB  {r['files']:>7,} files  {r['path']}")
        print(f"Largest folders under {args.root}:")
        for r in top_folders(root)[:args.top]:
            print(f"  {mb(r['bytes']):>10} MB  {r['files']:>7,} files  {r['path']}")
        return 0
    if args.cmd == "pack":
        out = pack(Path(args.folder), Path(args.vault))
    elif args.cmd == "verify":
        out = verify(Path(args.pack))
    else:
        out = unpack(Path(args.pack), Path(args.to))
    print(json.dumps(out, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
