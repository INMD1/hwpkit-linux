"""Exercise the built artifact outside every source repository."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("HWPKIT_TEST_PYTHON", sys.executable)
ARTIFACT_DIR = Path(os.environ.get("HWPKIT_TEST_DIST", ROOT / "dist"))


class PackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidates = sorted(ARTIFACT_DIR.glob("hwpkit-linux-*-linux.tar.gz"))
        if not candidates:
            raise RuntimeError("먼저 make build를 실행하세요.")
        cls.temp = tempfile.TemporaryDirectory(prefix="hwpkit Linux package ")
        cls.work = Path(cls.temp.name)
        with tarfile.open(candidates[-1]) as archive:
            archive.extractall(cls.work, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        cls.package = next(cls.work.glob("hwpkit-linux-*-linux"))
        cls.env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "NODE_PATH"}}
        # The shell launcher must also work with an external, explicitly selected venv.
        cls.env["HWPKIT_LINUX_VENV"] = str(Path(PYTHON).absolute().parent.parent)
        cls.have_pdf = shutil.which("soffice") and subprocess.run(
            [PYTHON, "-c", "import fitz"], capture_output=True).returncode == 0

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.output = self.work / self._testMethodName
        self.output.mkdir()

    def command(self, *args):
        return subprocess.run([str(self.package / "bin/hwpkit-linux"), *map(str, args)],
                              cwd=self.output, env=self.env, text=True, capture_output=True, timeout=120)

    def docx(self):
        source, dest = self.output / "한글 원본.md", self.output / "변환 결과.docx"
        source.write_text("# Linux 변환 검사\n\n한글과 공백 경로를 확인합니다.")
        result = self.command("convert", source, dest)
        self.assertEqual(result.returncode, 0, result.stderr)
        return source, dest

    def test_manifest_and_rebuild_sources(self):
        manifest = json.loads((self.package / "manifest.json").read_text())
        for path, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256((self.package / path).read_bytes()).hexdigest(), digest, path)
            self.assertNotIn("node_modules/", path)
            self.assertNotIn("datasets/", path)
        self.assertTrue((self.package / "sources/hwpkit-linux/scripts/build.py").is_file())
        self.assertTrue((self.package / "sources/hwpkit_research/runner/package-lock.json").is_file())

    def test_launcher_and_environment(self):
        result = self.command("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), (ROOT / "VERSION").read_text().strip())
        result = self.command("doctor")
        data = json.loads(result.stdout)
        self.assertTrue(data["node_supported"])
        self.assertTrue(data["engine"])

    def test_unicode_conversion_and_roundtrip(self):
        _, dest = self.docx()
        with zipfile.ZipFile(dest) as archive:
            self.assertIn("한글과 공백", archive.read("word/document.xml").decode())
        back = self.output / "다시.md"
        result = self.command("convert", dest, back)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("한글과 공백", back.read_text())

    def test_existing_outputs_and_input_are_preserved(self):
        source, dest = self.docx()
        before = dest.read_bytes()
        self.assertEqual(self.command("convert", source, dest).returncode, 2)
        self.assertEqual(dest.read_bytes(), before)
        original = source.read_bytes()
        self.assertEqual(self.command("convert", source, source).returncode, 2)
        self.assertEqual(source.read_bytes(), original)
        alias = self.output / "alias.docx"
        alias.symlink_to(dest)
        self.assertEqual(self.command("convert", source, alias).returncode, 2)
        self.assertEqual(dest.read_bytes(), before)

    def test_real_pdf_render_and_comparison(self):
        if not self.have_pdf:
            self.skipTest("PyMuPDF and LibreOffice are required")
        _, docx = self.docx()
        generated = self.output / "변환.pdf"
        result = self.command("render", docx, generated)
        self.assertEqual(result.returncode, 0, result.stderr)
        reference = self.output / "원본 시험용.pdf"
        # Controlled test fixture: same pixels, explicitly synthetic Hancom producer.
        subprocess.run([PYTHON, "-c", "import fitz,sys; d=fitz.open(sys.argv[1]); d.set_metadata({'producer':'Hancom test fixture'}); d.save(sys.argv[2])",
                        str(generated), str(reference)], check=True)
        report = self.output / "비교 자료"
        result = self.command("compare", "--reference", reference, "--generated", generated, "--output", report)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((report / "metrics.json").read_text())["score"], 1)
        self.assertTrue((report / "review.pdf").is_file())
        before = (report / "metrics.json").read_bytes()
        repeat = self.command("compare", "--reference", reference, "--generated", generated, "--output", report)
        self.assertEqual(repeat.returncode, 2)
        self.assertEqual((report / "metrics.json").read_bytes(), before)
        mismatch = self.output / "다른 내용.pdf"
        subprocess.run([PYTHON, "-c", "import fitz,sys; d=fitz.open(); p=d.new_page(); p.insert_text((50,50),'DIFFERENT DOCUMENT'); d.set_metadata({'producer':'Hancom test fixture'}); d.save(sys.argv[1])",
                        str(mismatch)], check=True)
        failed = self.output / "미달 결과"
        result = self.command("compare", "--reference", mismatch, "--generated", generated, "--output", failed)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads((failed / "metrics.json").read_text())["passed"])
        denied = self.output / "출처 확인"
        result = self.command("compare", "--reference", generated, "--generated", generated, "--output", denied)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(denied.exists())

    def test_legacy_doc_bridge(self):
        if not shutil.which("soffice"):
            self.skipTest("LibreOffice required")
        _, docx = self.docx()
        doc = self.output / "구형 워드.doc"
        result = self.command("convert", docx, doc)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(doc.read_bytes()[:8], bytes.fromhex("d0cf11e0a1b11ae1"))
        restored = self.output / "왕복.docx"
        result = self.command("convert", doc, restored)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(zipfile.is_zipfile(restored))


if __name__ == "__main__":
    unittest.main()
