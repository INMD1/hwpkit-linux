"""Linux file conversion and PDF review entry point. No network access at runtime."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {".hwp", ".hwpx", ".docx", ".doc", ".md", ".html"}


def run(command, timeout=240, env=None):
    proc = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise RuntimeError("실행이 중단되었거나 제한 시간을 초과했습니다.")
    if proc.returncode:
        raise RuntimeError((stderr or stdout or f"종료 코드 {proc.returncode}")[-4000:])
    if stderr.strip():
        print(stderr.strip(), file=sys.stderr)
    return stdout


def destination(source, output):
    source, output = source.resolve(strict=True), output.absolute()
    if source == output.resolve() or (output.exists() and os.path.samefile(source, output)):
        raise ValueError("입력과 출력은 서로 다른 파일이어야 합니다.")
    # Lexists also protects broken symlinks. Never overwrite existing user output.
    if os.path.lexists(output):
        raise ValueError(f"출력 파일이 이미 있습니다: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    return source, output


def publish(staged, output):
    # Same-filesystem hard link is an atomic no-clobber operation, including races.
    os.link(staged, output)


def convert(source, output):
    source, output = destination(source, output)
    if source.suffix.lower() not in FORMATS or output.suffix.lower() not in FORMATS:
        raise ValueError("지원 형식: hwp, hwpx, docx, doc, md, html")
    if ".doc" in {source.suffix.lower(), output.suffix.lower()} and (
        source.suffix.lower() in {".md", ".html"} or output.suffix.lower() in {".md", ".html"}
    ):
        raise ValueError("DOC와 MD/HTML 간 변환은 먼저 DOCX로 변환하세요.")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js 18 이상이 필요합니다. README.md를 확인하세요.")
    with tempfile.TemporaryDirectory(prefix=".hwpkit-", dir=output.parent) as tmp:
        staged = Path(tmp) / ("converted" + output.suffix.lower())
        run([node, str(ROOT / "app/convert.cjs"), str(source), str(staged)])
        if not staged.is_file() or not staged.stat().st_size:
            raise RuntimeError("변환 결과가 생성되지 않았습니다.")
        publish(staged, output)
    print(output)


def render(source, output):
    source, output = destination(source, output)
    if source.suffix.lower() not in {".docx", ".doc"} or output.suffix.lower() != ".pdf":
        raise ValueError("render는 DOCX/DOC 입력과 PDF 출력을 지원합니다.")
    soffice = shutil.which(os.environ.get("HWPKIT_SOFFICE", "soffice"))
    if not soffice:
        raise RuntimeError("LibreOffice Writer가 필요합니다.")
    with tempfile.TemporaryDirectory(prefix=".hwpkit-pdf-", dir=output.parent) as tmp:
        work = Path(tmp)
        # Use a controlled filename and separate profile for every invocation.
        local = work / ("source" + source.suffix.lower())
        shutil.copyfile(source, local)
        out = work / "output"
        out.mkdir()
        runtime = work / "runtime"
        runtime.mkdir(mode=0o700)
        env = {**os.environ, "XDG_RUNTIME_DIR": str(runtime), "SAL_USE_VCLPLUGIN": "svp"}
        run([soffice, f"-env:UserInstallation={(work / 'profile').as_uri()}", "--headless",
             "--convert-to", 'pdf:writer_pdf_Export:{"IsSkipEmptyPages":{"type":"boolean","value":"false"}}',
             "--outdir", str(out), str(local)], env=env)
        staged = out / "source.pdf"
        if not staged.is_file() or not staged.stat().st_size:
            raise RuntimeError("LibreOffice가 PDF를 생성하지 않았습니다.")
        publish(staged, output)
    print(output)


def compare(args):
    if importlib.util.find_spec("fitz") is None:
        raise RuntimeError("PDF 비교 환경이 없습니다. 패키지의 setup.sh를 실행하세요.")
    from pdf_layout_review import compare_pdfs, write_outputs
    import fitz
    reference = args.reference.resolve(strict=True)
    with fitz.open(reference) as pdf:
        producer = pdf.metadata.get("producer", "")
    if "hancom" not in producer.lower() and not args.allow_other_producer:
        raise ValueError(f"한컴 제작 원본 PDF가 필요합니다(제작 프로그램: {producer or '미기록'}). "
                         "다른 PDF의 진단은 --allow-other-producer를 지정하세요.")
    result = compare_pdfs(reference, args.generated.resolve(strict=True), args.tolerance_mm, args.target)
    args.output.mkdir(parents=True, exist_ok=False)
    write_outputs(result, args.output, args.review_pages)
    print(json.dumps({k: result[k] for k in ("score", "position_f1", "ink_f1", "passed")}, ensure_ascii=False, indent=2))
    print(f"비교 PDF: {(args.output / 'review.pdf').resolve()}")
    return 0 if result["passed"] else 1


def doctor():
    checks = {"python": sys.version.split()[0], "node": shutil.which("node"),
              "soffice": shutil.which(os.environ.get("HWPKIT_SOFFICE", "soffice")),
              "pymupdf": importlib.util.find_spec("fitz") is not None,
              "engine": (ROOT / "app/engine/core.mjs").is_file()}
    if checks["node"]:
        version = run([checks["node"], "--version"]).strip()
        checks["node_version"] = version
        checks["node_supported"] = int(version.lstrip("v").split(".")[0]) >= 18
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks.get("node_supported") and checks["engine"] and checks["pymupdf"] and checks["soffice"] else 2


def main():
    p = argparse.ArgumentParser(description="Hwpkit Linux — 문서 변환·PDF 출력·한컴 원본 위치 비교")
    p.add_argument("--version", action="version", version=(ROOT / "VERSION").read_text().strip())
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="실행 환경 확인")
    for name in ("convert", "render"):
        cmd = sub.add_parser(name, help="문서 변환" if name == "convert" else "DOCX/DOC → PDF")
        cmd.add_argument("input", type=Path)
        cmd.add_argument("output", type=Path)
    cmd = sub.add_parser("compare", help="한컴 원본 PDF와 변환 PDF 비교")
    cmd.add_argument("--reference", type=Path, required=True)
    cmd.add_argument("--generated", type=Path, required=True)
    cmd.add_argument("--output", type=Path, required=True)
    cmd.add_argument("--target", type=float, default=0.94)
    cmd.add_argument("--tolerance-mm", type=float, default=1.0)
    cmd.add_argument("--review-pages", type=int, default=6)
    cmd.add_argument("--allow-other-producer", action="store_true")
    args = p.parse_args()
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == "compare":
            if args.review_pages < 1:
                raise ValueError("review-pages는 양수여야 합니다.")
            return compare(args)
        {"convert": convert, "render": render}[args.command](args.input, args.output)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
