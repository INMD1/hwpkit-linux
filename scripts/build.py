#!/usr/bin/env python3
"""Build standalone Linux payloads without modifying sibling repositories."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent


def run(args, cwd=PROJECT):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def copy_sources(source, destination):
    destination.mkdir(parents=True)
    shutil.copytree(source / "src", destination / "src")
    for name in ("package.json", "package-lock.json", "tsconfig.json", "tsup.config.ts"):
        shutil.copy2(source / name, destination / name)


def collect_licenses(meta_paths, destination):
    packages = {}
    for meta in meta_paths:
        for filename in json.loads(meta.read_text())["inputs"]:
            path = (PROJECT / filename).resolve()
            if "node_modules" not in path.parts:
                continue
            for parent in path.parents:
                info = parent / "package.json"
                if info.is_file():
                    data = json.loads(info.read_text())
                    packages[data["name"]] = (parent, data)
                    break
    listing = []
    for name, (parent, data) in sorted(packages.items()):
        folder = destination / name.replace("/", "__")
        folder.mkdir(parents=True)
        shutil.copy2(parent / "package.json", folder / "package.json")
        for candidate in parent.iterdir():
            if candidate.is_file() and candidate.name.lower().startswith(("license", "licence", "copying", "copyright")):
                shutil.copy2(candidate, folder / candidate.name)
        listing.append({"name": name, "version": data.get("version"), "license": data.get("license")})
    return listing


def build(output, make_deb):
    version = (PROJECT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[.+~][a-zA-Z0-9.]+)?", version):
        raise ValueError("Invalid VERSION")
    library, research = WORKSPACE / "hwpkit", WORKSPACE / "hwpkit_research"
    esbuild = library / "node_modules/esbuild/bin/esbuild"
    if not esbuild.is_file():
        raise RuntimeError("먼저 hwpkit 폴더에서 npm ci를 실행하세요.")
    if make_deb and not shutil.which("dpkg-deb"):
        raise RuntimeError("deb 빌드에는 dpkg-deb가 필요합니다. --format tar로 tar.gz만 만들 수 있습니다.")
    output.mkdir(parents=True, exist_ok=True)
    stem = f"hwpkit-linux-{version}-linux"
    tar_path, deb_path = output / f"{stem}.tar.gz", output / f"hwpkit-linux_{version}_all.deb"
    for path in [tar_path, *([deb_path] if make_deb else [])]:
        if path.exists():
            raise FileExistsError(f"배포물이 이미 있습니다. 다른 --output을 선택하세요: {path}")
    with tempfile.TemporaryDirectory(prefix="hwpkit-package-") as temp:
        work = Path(temp)
        payload = work / stem
        (payload / "bin").mkdir(parents=True)
        engine = payload / "app/engine"
        engine.mkdir(parents=True)
        for filename in ("cli.py", "convert.cjs"):
            shutil.copy2(PROJECT / "app" / filename, payload / "app" / filename)
        shutil.copy2(PROJECT / "app/hwpkit-linux", payload / "bin/hwpkit-linux")
        (payload / "bin/hwpkit-linux").chmod(0o755)
        for filename in ("VERSION", "README.md", "requirements.txt", "setup.sh", "LICENSE"):
            shutil.copy2(PROJECT / filename, payload / filename)
        (payload / "setup.sh").chmod(0o755)
        shutil.copy2(research / "compare/pdf_layout_review.py", payload / "app/pdf_layout_review.py")
        core_meta, bridge_meta = work / "core.json", work / "legacy.json"
        run([esbuild, library / "src/index.ts", "--bundle", "--platform=node", "--target=node18", "--format=esm",
             "--banner:js=import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);",
             f"--outfile={engine / 'core.mjs'}", f"--metafile={core_meta}"])
        run([esbuild, research / "runner/convert_file.js", "--bundle", "--platform=node", "--target=node18",
             "--format=cjs", f"--outfile={engine / 'legacy.cjs'}", f"--metafile={bridge_meta}"])
        # Verify in the temporary tree, where neither sibling node_modules is visible.
        run(["node", "--input-type=module", "-e",
             "const {Pipeline}=await import(process.argv[1]);const r=await Pipeline.open('Package check').to('docx');if(!r.ok||!r.data.length)throw Error('Engine smoke failed');",
             (engine / "core.mjs").as_uri()], cwd=work)
        copy_sources(library, payload / "sources/hwpkit")
        source_tools = payload / "sources/hwpkit_research"
        (source_tools / "runner").mkdir(parents=True)
        (source_tools / "compare").mkdir()
        for name in ("convert_file.js", "package.json", "package-lock.json"):
            shutil.copy2(research / "runner" / name, source_tools / "runner" / name)
        shutil.copy2(research / "compare/pdf_layout_review.py", source_tools / "compare/pdf_layout_review.py")
        packaging_source = payload / "sources/hwpkit-linux"
        shutil.copytree(PROJECT / "scripts", packaging_source / "scripts")
        shutil.copytree(PROJECT / "app", packaging_source / "app")
        shutil.copytree(PROJECT / "tests", packaging_source / "tests", ignore=shutil.ignore_patterns('__pycache__'))
        for name in ("VERSION", "README.md", "requirements.txt", "setup.sh", "LICENSE", "Makefile"):
            shutil.copy2(PROJECT / name, packaging_source / name)
        packages = collect_licenses([core_meta, bridge_meta], payload / "licenses")
        manifest = {"name": "hwpkit-linux", "version": version, "engine": "hwpkit/src (current workspace)",
                    "runtime": {"node": ">=18", "python": ">=3.10", "pdf_comparison": "PyMuPDF 1.28.0",
                                "pdf_render_and_doc": "system LibreOffice Writer"},
                    "bundled_npm_dependencies": packages,
                    "quality": {"pdf_target": 0.94, "target_achieved": False},
                    "files": {str(p.relative_to(payload)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(payload.rglob("*")) if p.is_file()}}
        (payload / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        staged_tar = work / tar_path.name
        with tarfile.open(staged_tar, "w:gz") as archive:
            archive.add(payload, arcname=stem)
        staged_deb = None
        if make_deb:
            debroot = work / "deb"
            install = debroot / "usr/lib/hwpkit-linux"
            shutil.copytree(payload, install)
            (debroot / "usr/bin").mkdir(parents=True)
            (debroot / "usr/bin/hwpkit-linux").symlink_to("../lib/hwpkit-linux/bin/hwpkit-linux")
            control = debroot / "DEBIAN"
            control.mkdir()
            size = sum(p.stat().st_size for p in install.rglob("*") if p.is_file()) // 1024
            (control / "control").write_text(
                f"Package: hwpkit-linux\nVersion: {version}\nArchitecture: all\n"
                "Maintainer: Hwpkit contributors\nSection: utils\nPriority: optional\n"
                "Depends: python3 (>= 3.10), nodejs (>= 18), bash\n"
                "Recommends: libreoffice-writer, fonts-noto-cjk, python3-venv, python3-pymupdf\n"
                f"Installed-Size: {size}\nDescription: HWP document conversion and PDF layout review\n"
                " Converts HWP/HWPX/DOCX and compares physical PDF layout.\n")
            staged_deb = work / deb_path.name
            run(["dpkg-deb", "--root-owner-group", "--build", debroot, staged_deb])
        # Publish completed artifacts only, without overwriting a previous build.
        for staged, target in [(staged_tar, tar_path), *([(staged_deb, deb_path)] if staged_deb else [])]:
            with tempfile.NamedTemporaryFile(dir=output, prefix=".artifact-", delete=False) as dest:
                local_stage = Path(dest.name)
                try:
                    with staged.open("rb") as source:
                        shutil.copyfileobj(source, dest)
                    dest.flush()
                    local_stage.chmod(0o644)
                    os.link(local_stage, target)
                finally:
                    local_stage.unlink(missing_ok=True)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            target.with_suffix(target.suffix + ".sha256").write_text(f"{digest}  {target.name}\n")
            print(target)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=PROJECT / "dist")
    p.add_argument("--format", choices=("tar", "all"), default="all")
    args = p.parse_args()
    build(args.output.resolve(), args.format == "all")
