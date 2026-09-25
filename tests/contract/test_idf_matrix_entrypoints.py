from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import check_idf_matrix

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tools/run_pinned_idf_matrix.sh"
WORKFLOW = ROOT / ".github/workflows/idf-family-matrix.yml"
IMAGE = check_idf_matrix.CANONICAL_LANE["container_image"]


class IDFMatrixEntrypointTests(unittest.TestCase):
    def test_launcher_passes_exact_digest_platform_and_one_canonical_make_target(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            temporary = Path(name)
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            capture = temporary / "capture.json"
            docker = fake_bin / "docker"
            docker.write_text(
                "#!/bin/sh\npython3 - \"$@\" <<'PY'\n"
                "import json, os, sys\n"
                "json.dump({'args': sys.argv[1:]}, open(os.environ['FAKE_CAPTURE'], 'w'))\n"
                "PY\n",
                encoding="utf-8",
            )
            docker.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                    "FAKE_CAPTURE": str(capture),
                    "WDC_CONTAINER_RUNTIME": "docker",
                    "WDC_IDF_MATRIX_OUT_DIR": "reports/idf-family/test-entrypoint",
                }
            )
            process = subprocess.run(
                [str(LAUNCHER)],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            args = json.loads(capture.read_text(encoding="utf-8"))["args"]
            self.assertEqual(args[0:4], ["run", "--rm", "--platform", "linux/amd64"])
            self.assertIn(f"PULSE_IDF_CONTAINER_IMAGE={IMAGE}", args)
            self.assertIn("PULSE_IDF_EXECUTION_ADAPTER=docker", args)
            self.assertIn(IMAGE, args)
            self.assertEqual(args[-2:], ["make", "idf-family-qualify"])
            self.assertNotIn("--privileged", args)

    def test_launcher_rejects_unsupported_runtime_and_unsafe_output(self) -> None:
        cases = (
            ({"WDC_CONTAINER_RUNTIME": "/bin/true"}, "Docker or Podman"),
            ({"WDC_CONTAINER_RUNTIME": "docker", "WDC_IDF_MATRIX_OUT_DIR": "../escape"}, "normalized path"),
        )
        for extra, message in cases:
            with self.subTest(message=message):
                environment = os.environ.copy()
                environment.update(extra)
                process = subprocess.run(
                    [str(LAUNCHER)],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertNotEqual(process.returncode, 0)
                self.assertIn(message, process.stderr)

    def test_workflow_is_fixed_digest_pinned_and_uploads_evidence_always(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-24.04", text)
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("run: tools/run_pinned_idf_matrix.sh", text)
        self.assertIn("if: always()", text)
        self.assertIn("if-no-files-found: error", text)
        self.assertIn("${{ github.sha }}", text)
        self.assertNotIn("continue-on-error", text)
        self.assertNotIn("actions/cache", text)
        pins = re.findall(r"uses: actions/(?:checkout|upload-artifact)@([0-9a-f]+)", text)
        self.assertEqual(len(pins), 2)
        self.assertTrue(all(len(pin) == 40 for pin in pins))

    def test_makefile_exposes_all_if6_targets(self) -> None:
        text = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in (
            "idf-matrix-validate:",
            "idf-reference-qualify:",
            "idf-family-probe:",
            "idf-family-qualify:",
        ):
            self.assertIn(target, text)


if __name__ == "__main__":
    unittest.main()
