from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import build_idf_cell

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "tools/build_idf_cell.py"
COMMIT = "296b6eab9445fd720e71aecab961e2d3fbca9944"

FAKE_IDF = r'''#!/usr/bin/env python3
import hashlib
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("ESP-IDF v5.4.4")
    raise SystemExit(0)

def argument(prefix):
    for item in args:
        if item.startswith(prefix):
            return item[len(prefix):]
    return None

if "-B" not in args:
    print("missing -B", file=sys.stderr)
    raise SystemExit(2)
build_dir = Path(args[args.index("-B") + 1])
action = next((name for name in ("reconfigure", "build", "size") if name in args), "unknown")
target = os.environ.get("IDF_TARGET", "")
project = Path.cwd()
defaults_raw = argument("-DSDKCONFIG_DEFAULTS=") or ""
defaults = [Path(value) for value in defaults_raw.split(";") if value]
lock = project / "dependencies.lock"
trace_path = os.environ.get("FAKE_IDF_TRACE")
if trace_path:
    trace = {
        "action": action,
        "args": args,
        "cwd": str(project),
        "target": target,
        "idf_ccache_enable": os.environ.get("IDF_CCACHE_ENABLE"),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None,
        "defaults": [path.name for path in defaults],
        "defaults_text": [path.read_text(encoding="utf-8") for path in defaults if path.is_file()],
    }
    with Path(trace_path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, sort_keys=True) + "\n")

if action == "reconfigure":
    if os.environ.get("FAKE_IDF_MUTATE_LOCK") == "1":
        lock.write_bytes(lock.read_bytes() + b"\n")
    print(f"configured {project} for {target}")
elif action == "build":
    failure = os.environ.get("FAKE_IDF_FAIL_BUILD")
    if failure == "compile":
        print("error: unsupported target feature")
        raise SystemExit(2)
    if failure == "infrastructure":
        print("ERROR: Cannot establish a connection to the component registry")
        raise SystemExit(3)
    if failure == "unknown":
        print("mysterious build failure")
        raise SystemExit(4)
    sleep_seconds = float(os.environ.get("FAKE_IDF_SLEEP_BUILD", "0"))
    if sleep_seconds:
        time.sleep(sleep_seconds)
    artifacts = (
        "wdc_esp32_host.elf",
        "wdc_esp32_host.bin",
        "bootloader/bootloader.bin",
        "partition_table/partition-table.bin",
    )
    omitted = os.environ.get("FAKE_IDF_OMIT", "")
    for relative in artifacts:
        if relative == omitted:
            continue
        path = build_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{target}:{relative}\n".encode("utf-8"))
    sdkconfig_raw = argument("-DSDKCONFIG=")
    if sdkconfig_raw:
        sdkconfig_target = os.environ.get("FAKE_IDF_SDKCONFIG_TARGET", target)
        Path(sdkconfig_raw).write_text(f'CONFIG_IDF_TARGET="{sdkconfig_target}"\n', encoding="utf-8")
    print(f"built {build_dir} for {target}")
elif action == "size":
    if os.environ.get("FAKE_IDF_BAD_SIZE") == "1":
        print("not json")
    else:
        print("size report follows")
        print(json.dumps({"build_dir": str(build_dir), "target": target, "total_size": 1234}, sort_keys=True))
else:
    print("unknown action", file=sys.stderr)
    raise SystemExit(2)
'''


class IDFCellBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp = Path(self.temporary.name)
        self.firmware = self.temp / "firmware"
        shutil.copytree(ROOT / "firmware", self.firmware)
        self.matrix = self.firmware / "idf-family-matrix.json"

        self.idf_path = self.temp / "idf"
        self.idf_py = self.idf_path / "tools/idf.py"
        self.idf_py.parent.mkdir(parents=True)
        self.idf_py.write_text(FAKE_IDF, encoding="utf-8")
        self.idf_py.chmod(0o755)

        self.fake_bin = self.temp / "bin"
        self.fake_bin.mkdir()
        git = self.fake_bin / "git"
        git.write_text(f"#!/bin/sh\nprintf '%s\\n' '{COMMIT}'\n", encoding="utf-8")
        git.chmod(0o755)
        self.trace = self.temp / "trace.jsonl"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def source_snapshot(self) -> dict[str, str]:
        return {
            path.relative_to(self.firmware).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.firmware.rglob("*"))
            if path.is_file()
        }

    def run_builder(
        self,
        *,
        cell: str = "esp32c3-compile",
        output_name: str = "out",
        timeout: int = 10,
        extra_environment: dict[str, str] | None = None,
        out_dir: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        output = out_dir or (self.temp / output_name)
        environment = os.environ.copy()
        environment["PATH"] = f"{self.fake_bin}{os.pathsep}{environment.get('PATH', '')}"
        environment["FAKE_IDF_TRACE"] = str(self.trace)
        environment.update(extra_environment or {})
        process = subprocess.run(
            [
                sys.executable,
                "-B",
                str(BUILDER),
                "--matrix",
                str(self.matrix),
                "--cell",
                cell,
                "--out-dir",
                str(output),
                "--idf-path",
                str(self.idf_path),
                "--idf-py",
                str(self.idf_py),
                "--timeout",
                str(timeout),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return process, output

    def read_report(self, output: Path) -> dict[str, object]:
        return json.loads((output / "cell-report.json").read_text(encoding="utf-8"))

    def test_success_stages_declared_inputs_and_emits_complete_normalized_evidence(self) -> None:
        before = self.source_snapshot()
        process, output = self.run_builder()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(self.source_snapshot(), before)

        report = self.read_report(output)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["result"], "COMPILE_PROVEN")
        self.assertEqual(report["realization"]["target"], "esp32c3")  # type: ignore[index]
        artifacts = report["evidence"]["outputs"]["artifacts"]  # type: ignore[index]
        self.assertEqual(
            set(artifacts),
            {"application_elf", "application_binary", "bootloader_binary", "partition_table_binary"},
        )
        for evidence in artifacts.values():
            path = output / evidence["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), evidence["sha256"])
        for name in ["build.log", "sdkconfig", "size.json", "cell-report.json"]:
            self.assertTrue((output / name).is_file(), name)

        traces = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([trace["action"] for trace in traces], ["reconfigure", "build", "size"])
        for trace in traces[:2]:
            self.assertEqual(trace["target"], "esp32c3")
            self.assertEqual(trace["idf_ccache_enable"], "0")
            self.assertIn("-DIDF_TARGET=esp32c3", trace["args"])
            self.assertNotIn("set-target", trace["args"])
            self.assertEqual(trace["defaults"], ["sdkconfig.defaults", "esp32c3-compile.defaults"])
            self.assertIn("partitions/compile-16m-no-psram.csv", "".join(trace["defaults_text"]))
        expected_lock = self.firmware / "locks/idf-5.4.4/esp32c3/dependencies.lock"
        self.assertEqual(
            traces[0]["lock_sha256"], hashlib.sha256(expected_lock.read_bytes()).hexdigest()
        )

        report_text = (output / "cell-report.json").read_text(encoding="utf-8")
        log_text = (output / "build.log").read_text(encoding="utf-8")
        self.assertNotIn(str(self.temp), report_text)
        self.assertNotIn(str(self.temp), log_text)
        self.assertIn("<project>", log_text)
        size = json.loads((output / "size.json").read_text(encoding="utf-8"))
        self.assertEqual(size["build_dir"], "<build>")

    def test_two_fake_builds_emit_identical_normalized_reports(self) -> None:
        first_process, first_output = self.run_builder(output_name="repeat-1")
        second_process, second_output = self.run_builder(output_name="repeat-2")
        self.assertEqual(first_process.returncode, 0, first_process.stderr)
        self.assertEqual(second_process.returncode, 0, second_process.stderr)
        self.assertEqual(
            (first_output / "cell-report.json").read_bytes(),
            (second_output / "cell-report.json").read_bytes(),
        )
        self.assertEqual(
            (first_output / "build.log").read_bytes(),
            (second_output / "build.log").read_bytes(),
        )

    def test_missing_artifact_fails_without_copying_partial_outputs(self) -> None:
        before = self.source_snapshot()
        process, output = self.run_builder(
            output_name="missing",
            extra_environment={"FAKE_IDF_OMIT": "bootloader/bootloader.bin"},
        )
        self.assertNotEqual(process.returncode, 0)
        report = self.read_report(output)
        self.assertEqual(report["result"], "UNCLASSIFIED_FAILURE")
        self.assertEqual(report["failure"]["stage"], "artifacts")  # type: ignore[index]
        self.assertFalse((output / "artifacts").exists())
        self.assertEqual(self.source_snapshot(), before)

    def test_generated_sdkconfig_target_mismatch_fails_closed(self) -> None:
        process, output = self.run_builder(
            output_name="wrong-sdkconfig-target",
            extra_environment={"FAKE_IDF_SDKCONFIG_TARGET": "esp32s3"},
        )
        self.assertNotEqual(process.returncode, 0)
        report = self.read_report(output)
        self.assertEqual(report["result"], "UNCLASSIFIED_FAILURE")
        self.assertEqual(report["failure"]["stage"], "artifacts")  # type: ignore[index]
        self.assertIn("sdkconfig target mismatch", report["failure"]["message"])  # type: ignore[index]
        self.assertFalse((output / "artifacts").exists())

    def test_lock_mutation_fails_closed_and_preserves_source_lock(self) -> None:
        lock = self.firmware / "locks/idf-5.4.4/esp32c3/dependencies.lock"
        original = lock.read_bytes()
        process, output = self.run_builder(
            output_name="mutated-lock",
            extra_environment={"FAKE_IDF_MUTATE_LOCK": "1"},
        )
        self.assertNotEqual(process.returncode, 0)
        report = self.read_report(output)
        self.assertEqual(report["result"], "UNCLASSIFIED_FAILURE")
        self.assertEqual(report["failure"]["stage"], "reconfigure")  # type: ignore[index]
        self.assertIn("mutated", report["failure"]["message"])  # type: ignore[index]
        self.assertEqual(lock.read_bytes(), original)

    def test_timeout_is_an_infrastructure_failure(self) -> None:
        process, output = self.run_builder(
            output_name="timeout",
            timeout=1,
            extra_environment={"FAKE_IDF_SLEEP_BUILD": "2"},
        )
        self.assertNotEqual(process.returncode, 0)
        report = self.read_report(output)
        self.assertEqual(report["result"], "INFRASTRUCTURE_FAILURE")
        self.assertEqual(report["failure"]["stage"], "build")  # type: ignore[index]

    def test_invalid_size_json_fails_before_artifacts_are_published(self) -> None:
        process, output = self.run_builder(
            output_name="bad-size",
            extra_environment={"FAKE_IDF_BAD_SIZE": "1"},
        )
        self.assertNotEqual(process.returncode, 0)
        report = self.read_report(output)
        self.assertEqual(report["result"], "UNCLASSIFIED_FAILURE")
        self.assertEqual(report["failure"]["stage"], "size")  # type: ignore[index]
        self.assertFalse((output / "artifacts").exists())

    def test_command_failures_have_deterministic_classification(self) -> None:
        cases = {
            "compile": "INCOMPATIBLE",
            "infrastructure": "INFRASTRUCTURE_FAILURE",
            "unknown": "UNCLASSIFIED_FAILURE",
        }
        for failure, expected in cases.items():
            with self.subTest(failure=failure):
                process, output = self.run_builder(
                    output_name=f"failure-{failure}",
                    extra_environment={"FAKE_IDF_FAIL_BUILD": failure},
                )
                self.assertNotEqual(process.returncode, 0)
                report = self.read_report(output)
                self.assertEqual(report["result"], expected)
                self.assertEqual(report["failure"]["stage"], "build")  # type: ignore[index]
                if failure == "compile":
                    self.assertIn(
                        "error: unsupported target feature",
                        report["failure"]["message"],  # type: ignore[index]
                    )

    def test_linker_overflow_detail_wins_over_generic_collect2_error(self) -> None:
        output = (
            "ld: region `dram0_0_seg' overflowed by 17664 bytes\n"
            "collect2: error: ld returned 1 exit status\n"
        )
        self.assertEqual(
            build_idf_cell._command_failure_detail(output),  # noqa: SLF001
            "region `dram0_0_seg' overflowed by 17664 bytes",
        )

    def test_unknown_cell_and_output_inside_firmware_fail_closed(self) -> None:
        process, output = self.run_builder(cell="esp32p4-deferred", output_name="unknown")
        self.assertNotEqual(process.returncode, 0)
        report = self.read_report(output)
        self.assertEqual(report["failure"]["stage"], "matrix")  # type: ignore[index]

        nested = self.firmware / "evidence"
        process, _output = self.run_builder(out_dir=nested)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("may not be inside", process.stderr)
        self.assertFalse(nested.exists())

        dirty = self.temp / "dirty-output"
        dirty.mkdir()
        (dirty / "prior-evidence.txt").write_text("preserve me\n", encoding="utf-8")
        process, _output = self.run_builder(out_dir=dirty)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("must be absent or empty", process.stderr)
        self.assertEqual((dirty / "prior-evidence.txt").read_text(encoding="utf-8"), "preserve me\n")


if __name__ == "__main__":
    unittest.main()
