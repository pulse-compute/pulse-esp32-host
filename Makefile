PYTHON ?= /usr/bin/python3 -B
HX_AITRIP_SEALED_ELF ?= $(CURDIR)/tests/hardware-in-loop/hx45-s3-aitrip-n8r2/fixtures/synthetic-loopback-esp32s3.elf
HX_AITRIP_IDF_PATH ?= $(IDF_PATH)
HX_AITRIP_IDF_PY ?= $(HX_AITRIP_IDF_PATH)/tools/idf.py
HX_XIAO_SEALED_ELF ?= $(CURDIR)/tests/hardware-in-loop/hx45-c6-seeed-xiao-4m/fixtures/synthetic-loopback-esp32c6.elf
HX_XIAO_IDF_PATH ?= $(IDF_PATH)
HX_XIAO_IDF_PY ?= $(HX_XIAO_IDF_PATH)/tools/idf.py
HP3_5_IDF_PATH ?= $(IDF_PATH)
HP3_5_IDF_PY ?= $(HP3_5_IDF_PATH)/tools/idf.py
HP5_5_IDF_PATH ?= $(IDF_PATH)
HP5_5_IDF_PY ?= $(HP5_5_IDF_PATH)/tools/idf.py
HP5_SOURCE_ARCHIVE ?=
PACKAGE_OUT_DIR ?= $(CURDIR)/dist
SOURCE_PACKAGE ?= $(PACKAGE_OUT_DIR)/pulse-esp32-host-source.zip
HOST_EVIDENCE_PACKAGE ?= $(PACKAGE_OUT_DIR)/pulse-esp32-host-hx1-hx45-host-evidence.zip
HARDWARE_EVIDENCE_PACKAGE ?= $(PACKAGE_OUT_DIR)/pulse-esp32-host-hx45-aitrip-hardware-evidence.zip
XIAO_HARDWARE_EVIDENCE_PACKAGE ?= $(PACKAGE_OUT_DIR)/pulse-esp32-host-hx45-c6-xiao-hardware-evidence.zip
HP0_EVIDENCE_PACKAGE ?= $(PACKAGE_OUT_DIR)/pulse-esp32-host-hx5b-hardware-evidence.zip
HP0_SOURCE_SNAPSHOT ?=
HP0_HANDOFF ?=
HP0_INPUT_ARCHIVE ?=
HP0_S3_RUN_DIR ?=
HP0_C6_RUN_DIR ?=
HP0_DUAL_RUN_DIR ?=
HX5B_HARDWARE_ARGS ?=

.PHONY: \
	test validate \
	check-r0 check-r1 check-r2 check-r3 check-r3-5 check-r3_5 check-r3.5 check-r4 check-r5 check-r6 check-r7 check-r8 check-r8-1 check-r8_1 check-r8.1 check-r8-2 check-r8_2 check-r8.2 check-r9 check-hx0 check-hx1 check-hx2 check-hx3 check-hx4 check-hx4-5 check-hx4_5 check-hx4.5 check-hx5a check-hx5b check-hp0 check-hp1 check-hp2 check-hp3 check-hp3-5 check-hp3_5 check-hp3.5 check-hp4-0 check-hp4_0 check-hp4.0 check-hp4-1 check-hp4_1 check-hp4.1 check-hp4-2 check-hp4_2 check-hp4.2 check-hp4-3 check-hp4_3 check-hp4.3 check-hp4-4 check-hp4_4 check-hp4.4 check-hp5 check-hp5-0 check-hp5_0 check-hp5.0 check-hp5-5 check-hp5_5 check-hp5.5 check-hx45-s3-aitrip check-hx45-c6-xiao check-docs docs-check \
	deps-check deps-host deps-rust deps-idf deps-bootstrap bootstrap-deps \
	build-guest build-firmware idf-matrix-validate idf-reference-qualify idf-family-probe idf-family-qualify idf-family-docs-check idf-family-seal-check check-full check-full-network \
	host-extension-loader-qualify host-extension-admission-qualify host-extension-runtime-qualify host-extension-adversarial-qualify host-extension-faults-qualify host-extension-pressure-qualify host-kernel-qualify host-build-qualify app-slots-qualify app-slots-adversarial-qualify administration-contract-qualify administration-core-qualify administration-update-qualify administration-recovery-qualify administration-adversarial-qualify host-network-qualify hp5_5-readiness-qualify hp5_5-provision hp5_5-s3-aitrip-build hp5_5-s3-aitrip-client hp5_5-s3-aitrip-evaluate hp5_5-c6-xiao-build hp5_5-c6-xiao-client hp5_5-c6-xiao-evaluate hp5_5-hardware-evaluate hp3_5-s3-aitrip-build hp3_5-s3-aitrip-evaluate hp3_5-c6-xiao-build hp3_5-c6-xiao-evaluate hp3_5-hardware-evaluate hx45-s3-aitrip-build hx45-s3-aitrip-evaluate hx45-c6-xiao-build hx45-c6-xiao-evaluate hx5b-s3-aitrip-build hx5b-s3-aitrip-evaluate hx5b-c6-xiao-build hx5b-c6-xiao-evaluate \
	hp0-evidence-reconcile package-source package-host-evidence package-hardware-evidence package-xiao-hardware-evidence firmware-build guest-wasm regenerate-r2-wasm clean

test:
	$(PYTHON) tools/run_contract_tests.py

validate:
	$(PYTHON) tools/wdc_validate.py profile --profile examples/device-profiles/relay-node-rev-c.json
	$(PYTHON) tools/wdc_validate.py manifest --manifest examples/bundles/relay-controller/manifest.json --profile examples/device-profiles/relay-node-rev-c.json

check-r0:
	$(PYTHON) tools/check_r0.py

check-r1:
	$(PYTHON) tools/check_r1.py

check-r2:
	$(PYTHON) tools/check_r2.py

check-r3:
	$(PYTHON) tools/check_r3.py

check-r3-5:
	$(PYTHON) tools/check_r3_5.py

check-r3_5: check-r3-5

check-r3.5: check-r3-5

check-r4:
	$(PYTHON) tools/check_r4.py

check-r5:
	$(PYTHON) tools/check_r5.py

check-r6:
	$(PYTHON) tools/check_r6.py

check-r7:
	$(PYTHON) tools/check_r7.py

check-r8:
	$(PYTHON) tools/check_r8.py

check-r8-1:
	$(PYTHON) tools/check_r8_1.py

check-r8_1: check-r8-1

check-r8.1: check-r8-1

check-r8-2:
	$(PYTHON) tools/check_r8_2.py

check-r8_2: check-r8-2

check-r8.2: check-r8-2

check-r9:
	$(PYTHON) tools/check_r9.py

check-hx0:
	$(PYTHON) -m unittest tests.contract.test_hx0_extension_contract -v

check-hx1:
	$(PYTHON) -m unittest tests.contract.test_hx1_elf_loader -v

check-hx2:
	$(PYTHON) -m unittest tests.contract.test_hx2_extension_admission -v

check-hx3:
	$(PYTHON) -m unittest tests.contract.test_hx3_extension_lifecycle -v

check-hx4:
	$(PYTHON) -m unittest tests.contract.test_hx4_extension_event_effect -v

check-hx4-5:
	$(PYTHON) -m unittest tests.contract.test_hx45_extension_adversarial -v

check-hx4_5: check-hx4-5

check-hx4.5: check-hx4-5

check-hx5a:
	$(PYTHON) -m unittest tests.contract.test_hx5a_extension_faults -v

check-hx5b:
	$(PYTHON) -m unittest tests.contract.test_hx5b_extension_pressure -v

check-hp0:
	$(PYTHON) -m unittest tests.contract.test_hp0_evidence_reconciliation -v

check-hp1:
	$(PYTHON) -m unittest tests.contract.test_hp1_host_kernel_resource_authority -v

check-hp2:
	$(PYTHON) -m unittest tests.contract.test_hp2_host_build_coherence -v

check-hp3:
	$(PYTHON) -m unittest tests.contract.test_hp3_application_slots -v

check-hp3-5:
	$(PYTHON) -m unittest tests.contract.test_hp3_5_slot_adversarial -v

check-hp3_5: check-hp3-5

check-hp3.5: check-hp3-5

check-hp4-0:
	$(PYTHON) -m unittest tests.contract.test_hp4_0_administration_contract -v

check-hp4_0: check-hp4-0

check-hp4.0: check-hp4-0

check-hp4-1:
	$(PYTHON) -m unittest tests.contract.test_hp4_1_administration_core -v

check-hp4_1: check-hp4-1

check-hp4.1: check-hp4-1

check-hp4-2:
	$(PYTHON) -m unittest tests.contract.test_hp4_2_admin_update -v

check-hp4_2: check-hp4-2

check-hp4.2: check-hp4-2

check-hp4-3:
	$(PYTHON) -m unittest tests.contract.test_hp4_3_admin_recovery -v

check-hp4_3: check-hp4-3

check-hp4.3: check-hp4-3

check-hp4-4:
	$(PYTHON) -m unittest tests.contract.test_hp4_4_admin_adversarial -v

check-hp4_4: check-hp4-4

check-hp4.4: check-hp4-4

check-hp5:
	$(PYTHON) -m unittest tests.contract.test_hp5_host_network -v

check-hp5-0: check-hp5

check-hp5_0: check-hp5

check-hp5.0: check-hp5

check-hp5-5:
	$(PYTHON) -m unittest tests.contract.test_hp5_5_network_hardware -v

check-hp5_5: check-hp5-5

check-hp5.5: check-hp5-5

check-hx45-s3-aitrip:
	$(PYTHON) -m unittest tests.contract.test_hx45_s3_aitrip_hardware -v

check-hx45-c6-xiao:
	$(PYTHON) -m unittest tests.contract.test_hx45_c6_xiao_hardware -v

hx45-s3-aitrip-build:
	test -n "$${HX_AITRIP_OUT_DIR:-}"
	test -n "$(HX_AITRIP_IDF_PATH)"
	test -f "$(HX_AITRIP_IDF_PY)"
	$(PYTHON) tools/build_hx45_s3_aitrip.py \
		--out-dir "$${HX_AITRIP_OUT_DIR}" \
		--sealed-native-elf "$(HX_AITRIP_SEALED_ELF)" \
		--idf-path "$(HX_AITRIP_IDF_PATH)" \
		--idf-py "$(HX_AITRIP_IDF_PY)" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

hx45-s3-aitrip-evaluate:
	test -n "$${HX_AITRIP_OUT_DIR:-}"
	$(PYTHON) tools/evaluate_hx45_s3_aitrip.py \
		--serial-log "$${HX_AITRIP_OUT_DIR}/serial.log" \
		--build-report "$${HX_AITRIP_OUT_DIR}/build-report.json" \
		--module-marking "$${HX_AITRIP_MODULE_MARKING:-ESP32-S3-WROOM-1 N8R2}" \
		--out-dir "$${HX_AITRIP_OUT_DIR}/evaluation"

hx45-c6-xiao-build:
	test -n "$${HX_XIAO_OUT_DIR:-}"
	test -n "$(HX_XIAO_IDF_PATH)"
	test -f "$(HX_XIAO_IDF_PY)"
	$(PYTHON) tools/build_hx45_c6_xiao.py \
		--out-dir "$${HX_XIAO_OUT_DIR}" \
		--sealed-native-elf "$(HX_XIAO_SEALED_ELF)" \
		--idf-path "$(HX_XIAO_IDF_PATH)" \
		--idf-py "$(HX_XIAO_IDF_PY)" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

hx45-c6-xiao-evaluate:
	test -n "$${HX_XIAO_OUT_DIR:-}"
	$(PYTHON) tools/evaluate_hx45_c6_xiao.py \
		--serial-log "$${HX_XIAO_OUT_DIR}/serial.log" \
		--build-report "$${HX_XIAO_OUT_DIR}/build-report.json" \
		--board-marking "$${HX_XIAO_BOARD_MARKING:-XIAO ESP32C6}" \
		--out-dir "$${HX_XIAO_OUT_DIR}/evaluation"

hx5b-s3-aitrip-build:
	test -n "$${HX_AITRIP_OUT_DIR:-}"
	test -n "$(HX_AITRIP_IDF_PATH)"
	test -f "$(HX_AITRIP_IDF_PY)"
	$(PYTHON) tools/build_hx45_s3_aitrip.py \
		--out-dir "$${HX_AITRIP_OUT_DIR}" \
		--sealed-native-elf "$(HX_AITRIP_SEALED_ELF)" \
		--idf-path "$(HX_AITRIP_IDF_PATH)" \
		--idf-py "$(HX_AITRIP_IDF_PY)" \
		--hx5b-pressure \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

hx5b-s3-aitrip-evaluate:
	test -n "$${HX_AITRIP_OUT_DIR:-}"
	$(PYTHON) tools/evaluate_hx45_s3_aitrip.py \
		--serial-log "$${HX_AITRIP_OUT_DIR}/serial.log" \
		--build-report "$${HX_AITRIP_OUT_DIR}/build-report.json" \
		--module-marking "$${HX_AITRIP_MODULE_MARKING:-ESP32-S3-WROOM-1 N8R2}" \
		--require-hx5b-pressure \
		--out-dir "$${HX_AITRIP_OUT_DIR}/evaluation"

hx5b-c6-xiao-build:
	test -n "$${HX_XIAO_OUT_DIR:-}"
	test -n "$(HX_XIAO_IDF_PATH)"
	test -f "$(HX_XIAO_IDF_PY)"
	$(PYTHON) tools/build_hx45_c6_xiao.py \
		--out-dir "$${HX_XIAO_OUT_DIR}" \
		--sealed-native-elf "$(HX_XIAO_SEALED_ELF)" \
		--idf-path "$(HX_XIAO_IDF_PATH)" \
		--idf-py "$(HX_XIAO_IDF_PY)" \
		--hx5b-pressure \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

hx5b-c6-xiao-evaluate:
	test -n "$${HX_XIAO_OUT_DIR:-}"
	$(PYTHON) tools/evaluate_hx45_c6_xiao.py \
		--serial-log "$${HX_XIAO_OUT_DIR}/serial.log" \
		--build-report "$${HX_XIAO_OUT_DIR}/build-report.json" \
		--board-marking "$${HX_XIAO_BOARD_MARKING:-XIAO ESP32C6}" \
		--require-hx5b-pressure \
		--out-dir "$${HX_XIAO_OUT_DIR}/evaluation"

package-source:
	$(PYTHON) tools/package_release.py source --out "$(SOURCE_PACKAGE)"

package-host-evidence:
	$(PYTHON) tools/package_release.py host-evidence --out "$(HOST_EVIDENCE_PACKAGE)"

package-hardware-evidence:
	test -n "$${HX_AITRIP_OUT_DIR:-}"
	$(PYTHON) tools/package_release.py hardware-evidence \
		--run-dir "$${HX_AITRIP_OUT_DIR}" \
		--out "$(HARDWARE_EVIDENCE_PACKAGE)"

package-xiao-hardware-evidence:
	test -n "$${HX_XIAO_OUT_DIR:-}"
	$(PYTHON) tools/package_release.py hardware-evidence \
		--run-dir "$${HX_XIAO_OUT_DIR}" \
		--out "$(XIAO_HARDWARE_EVIDENCE_PACKAGE)"

hp0-evidence-reconcile:
	test -n "$(HP0_SOURCE_SNAPSHOT)"
	test -n "$(HP0_HANDOFF)"
	test -n "$(HP0_INPUT_ARCHIVE)"
	test -n "$(HP0_S3_RUN_DIR)"
	test -n "$(HP0_C6_RUN_DIR)"
	test -n "$(HP0_DUAL_RUN_DIR)"
	$(PYTHON) tools/reconcile_hp0_evidence.py \
		--source-snapshot "$(HP0_SOURCE_SNAPSHOT)" \
		--handoff "$(HP0_HANDOFF)" \
		--input-archive "$(HP0_INPUT_ARCHIVE)" \
		--s3-run "$(HP0_S3_RUN_DIR)" \
		--c6-run "$(HP0_C6_RUN_DIR)" \
		--dual-run "$(HP0_DUAL_RUN_DIR)" \
		--out "$(HP0_EVIDENCE_PACKAGE)"

host-extension-loader-qualify:
	test -n "$${HX_OUT_DIR:-}"
	$(PYTHON) tools/qualify_extension_spine.py \
		--matrix firmware/extension-proof-matrix.json \
		--out-dir "$${HX_OUT_DIR}" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

host-extension-admission-qualify:
	test -n "$${HX_OUT_DIR:-}"
	$(PYTHON) tools/qualify_extension_admission.py \
		--out-dir "$${HX_OUT_DIR}"

host-extension-runtime-qualify:
	test -n "$${HX_OUT_DIR:-}"
	$(PYTHON) tools/qualify_extension_roundtrip.py \
		--out-dir "$${HX_OUT_DIR}"
	$(PYTHON) tools/qualify_extension_spine.py \
		--matrix firmware/extension-proof-matrix.json \
		--out-dir "$${HX_OUT_DIR}/firmware-qualification" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"
	$(PYTHON) tools/qualify_extension_roundtrip.py \
		--out-dir "$${HX_OUT_DIR}" \
		--firmware-report "$${HX_OUT_DIR}/firmware-qualification/qualification-report.json"

host-extension-adversarial-qualify:
	test -n "$${HX_OUT_DIR:-}"
	$(PYTHON) tools/qualify_extension_adversarial.py \
		--out-dir "$${HX_OUT_DIR}"
	$(PYTHON) tools/qualify_extension_spine.py \
		--matrix firmware/extension-proof-matrix.json \
		--out-dir "$${HX_OUT_DIR}/firmware-qualification" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"
	$(PYTHON) tools/qualify_extension_adversarial.py \
		--out-dir "$${HX_OUT_DIR}" \
		--firmware-report "$${HX_OUT_DIR}/firmware-qualification/qualification-report.json"

host-extension-faults-qualify:
	test -n "$${HX_OUT_DIR:-}"
	$(PYTHON) tools/qualify_extension_faults.py \
		--out-dir "$${HX_OUT_DIR}"

host-extension-pressure-qualify:
	test -n "$${HX_OUT_DIR:-}"
	$(PYTHON) tools/qualify_extension_pressure.py \
		--out-dir "$${HX_OUT_DIR}" $(HX5B_HARDWARE_ARGS)

host-kernel-qualify:
	test -n "$${HP1_OUT_DIR:-}"
	$(PYTHON) tools/qualify_host_kernel.py \
		--out-dir "$${HP1_OUT_DIR}"

host-build-qualify:
	test -n "$${HP2_OUT_DIR:-}"
	$(PYTHON) tools/qualify_host_build.py \
		--out-dir "$${HP2_OUT_DIR}"

app-slots-qualify:
	test -n "$${HP3_OUT_DIR:-}"
	$(PYTHON) tools/qualify_app_slots.py \
		--out-dir "$${HP3_OUT_DIR}"

app-slots-adversarial-qualify:
	test -n "$${HP3_5_OUT_DIR:-}"
	$(PYTHON) tools/qualify_app_slot_adversarial.py \
		--out-dir "$${HP3_5_OUT_DIR}"

administration-contract-qualify:
	test -n "$${HP4_0_OUT_DIR:-}"
	$(PYTHON) tools/qualify_admin_contract.py \
		--out-dir "$${HP4_0_OUT_DIR}"

administration-core-qualify:
	test -n "$${HP4_1_OUT_DIR:-}"
	$(PYTHON) tools/qualify_admin_core.py \
		--out-dir "$${HP4_1_OUT_DIR}"

administration-update-qualify:
	test -n "$${HP4_2_OUT_DIR:-}"
	$(PYTHON) tools/qualify_admin_update.py \
		--out-dir "$${HP4_2_OUT_DIR}"

administration-recovery-qualify:
	test -n "$${HP4_3_OUT_DIR:-}"
	$(PYTHON) tools/qualify_admin_recovery.py \
		--out-dir "$${HP4_3_OUT_DIR}"

administration-adversarial-qualify:
	test -n "$${HP4_4_OUT_DIR:-}"
	$(PYTHON) tools/qualify_admin_adversarial.py \
		--out-dir "$${HP4_4_OUT_DIR}"

host-network-qualify:
	test -n "$${HP5_OUT_DIR:-}"
	$(PYTHON) tools/qualify_host_network.py \
		--out-dir "$${HP5_OUT_DIR}"

hp5_5-readiness-qualify:
	test -n "$${HP5_5_OUT_DIR:-}"
	$(PYTHON) tools/qualify_hp5_5_network_hardware.py \
		--out-dir "$${HP5_5_OUT_DIR}" $(if $(HP5_SOURCE_ARCHIVE),--source-archive "$(HP5_SOURCE_ARCHIVE)",)

hp5_5-provision:
	test -n "$${HP5_5_PROVISION_DIR:-}"
	$(PYTHON) tools/prepare_hp5_5_provision.py \
		--out-dir "$${HP5_5_PROVISION_DIR}"

hp5_5-s3-aitrip-build:
	test -n "$${HP5_5_S3_RUN_DIR:-}"
	test -n "$${HP5_5_PROVISION_DIR:-}"
	test -n "$(HP5_SOURCE_ARCHIVE)"
	test -f "$(HP5_SOURCE_ARCHIVE)"
	test -n "$(HP5_5_IDF_PATH)"
	test -f "$(HP5_5_IDF_PY)"
	$(PYTHON) tools/build_hp5_5_network_hardware.py \
		--board-id aitrip-esp32s3-devkitc-1-n8r2 \
		--out-dir "$${HP5_5_S3_RUN_DIR}" \
		--source-archive "$(HP5_SOURCE_ARCHIVE)" \
		--provision-dir "$${HP5_5_PROVISION_DIR}" \
		--idf-path "$(HP5_5_IDF_PATH)" \
		--idf-py "$(HP5_5_IDF_PY)" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

hp5_5-s3-aitrip-client:
	test -n "$${HP5_5_S3_RUN_DIR:-}"
	test -n "$${HP5_5_PROVISION_DIR:-}"
	test -n "$${HP5_5_S3_DEVICE_HOST:-}"
	$(PYTHON) tools/run_hp5_5_network_client.py \
		--run-dir "$${HP5_5_S3_RUN_DIR}" \
		--provision-dir "$${HP5_5_PROVISION_DIR}" \
		--device-host "$${HP5_5_S3_DEVICE_HOST}"

hp5_5-s3-aitrip-evaluate:
	test -n "$${HP5_5_S3_RUN_DIR:-}"
	test -n "$${HP5_5_PROVISION_DIR:-}"
	test -n "$${HP5_5_S3_RESTORE_COMMAND:-}"
	$(PYTHON) tools/evaluate_hp5_5_network_board.py \
		--run-dir "$${HP5_5_S3_RUN_DIR}" \
		--provision-dir "$${HP5_5_PROVISION_DIR}" \
		--module-or-board-marking "$${HP5_5_S3_MARKING:-AITRIP ESP32-S3-DevKitC-1 N8R2}" \
		--restore-command "$${HP5_5_S3_RESTORE_COMMAND}" \
		--fresh-erase-attested --operator-attended

hp5_5-c6-xiao-build:
	test -n "$${HP5_5_C6_RUN_DIR:-}"
	test -n "$${HP5_5_PROVISION_DIR:-}"
	test -n "$(HP5_SOURCE_ARCHIVE)"
	test -f "$(HP5_SOURCE_ARCHIVE)"
	test -n "$(HP5_5_IDF_PATH)"
	test -f "$(HP5_5_IDF_PY)"
	$(PYTHON) tools/build_hp5_5_network_hardware.py \
		--board-id seeed-xiao-esp32c6-4m \
		--out-dir "$${HP5_5_C6_RUN_DIR}" \
		--source-archive "$(HP5_SOURCE_ARCHIVE)" \
		--provision-dir "$${HP5_5_PROVISION_DIR}" \
		--idf-path "$(HP5_5_IDF_PATH)" \
		--idf-py "$(HP5_5_IDF_PY)" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

hp5_5-c6-xiao-client:
	test -n "$${HP5_5_C6_RUN_DIR:-}"
	test -n "$${HP5_5_PROVISION_DIR:-}"
	test -n "$${HP5_5_C6_DEVICE_HOST:-}"
	$(PYTHON) tools/run_hp5_5_network_client.py \
		--run-dir "$${HP5_5_C6_RUN_DIR}" \
		--provision-dir "$${HP5_5_PROVISION_DIR}" \
		--device-host "$${HP5_5_C6_DEVICE_HOST}"

hp5_5-c6-xiao-evaluate:
	test -n "$${HP5_5_C6_RUN_DIR:-}"
	test -n "$${HP5_5_PROVISION_DIR:-}"
	test -n "$${HP5_5_C6_RESTORE_COMMAND:-}"
	$(PYTHON) tools/evaluate_hp5_5_network_board.py \
		--run-dir "$${HP5_5_C6_RUN_DIR}" \
		--provision-dir "$${HP5_5_PROVISION_DIR}" \
		--module-or-board-marking "$${HP5_5_C6_MARKING:-Seeed Studio XIAO ESP32C6 4MB}" \
		--restore-command "$${HP5_5_C6_RESTORE_COMMAND}" \
		--fresh-erase-attested --operator-attended

hp5_5-hardware-evaluate:
	test -n "$${HP5_5_S3_RUN_DIR:-}"
	test -n "$${HP5_5_C6_RUN_DIR:-}"
	test -n "$${HP5_5_HARDWARE_OUT_DIR:-}"
	$(PYTHON) tools/evaluate_hp5_5_network_hardware.py \
		--s3-run "$${HP5_5_S3_RUN_DIR}" \
		--c6-run "$${HP5_5_C6_RUN_DIR}" \
		--out-dir "$${HP5_5_HARDWARE_OUT_DIR}"

hp3_5-s3-aitrip-build:
	test -n "$${HP3_5_S3_RUN_DIR:-}"
	test -n "$(HP3_5_IDF_PATH)"
	test -f "$(HP3_5_IDF_PY)"
	$(PYTHON) tools/build_hp3_5_slot_hardware.py \
		--board-id aitrip-esp32s3-devkitc-1-n8r2 \
		--out-dir "$${HP3_5_S3_RUN_DIR}" \
		--idf-path "$(HP3_5_IDF_PATH)" \
		--idf-py "$(HP3_5_IDF_PY)" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

hp3_5-s3-aitrip-evaluate:
	test -n "$${HP3_5_S3_RUN_DIR:-}"
	$(PYTHON) tools/evaluate_hp3_5_slot_board.py \
		--run-dir "$${HP3_5_S3_RUN_DIR}" \
		--module-or-board-marking "$${HP3_5_S3_MARKING:-ESP32-S3-WROOM-1-N8R2}"

hp3_5-c6-xiao-build:
	test -n "$${HP3_5_C6_RUN_DIR:-}"
	test -n "$(HP3_5_IDF_PATH)"
	test -f "$(HP3_5_IDF_PY)"
	$(PYTHON) tools/build_hp3_5_slot_hardware.py \
		--board-id seeed-xiao-esp32c6-4m \
		--out-dir "$${HP3_5_C6_RUN_DIR}" \
		--idf-path "$(HP3_5_IDF_PATH)" \
		--idf-py "$(HP3_5_IDF_PY)" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

hp3_5-c6-xiao-evaluate:
	test -n "$${HP3_5_C6_RUN_DIR:-}"
	$(PYTHON) tools/evaluate_hp3_5_slot_board.py \
		--run-dir "$${HP3_5_C6_RUN_DIR}" \
		--module-or-board-marking "$${HP3_5_C6_MARKING:-XIAO ESP32C6 / ESP32-C6FH4}"

hp3_5-hardware-evaluate:
	test -n "$${HP3_5_S3_RUN_DIR:-}"
	test -n "$${HP3_5_C6_RUN_DIR:-}"
	test -n "$${HP3_5_HARDWARE_OUT_DIR:-}"
	$(PYTHON) tools/evaluate_hp3_5_slot_hardware.py \
		--s3-run "$${HP3_5_S3_RUN_DIR}" \
		--c6-run "$${HP3_5_C6_RUN_DIR}" \
		--out-dir "$${HP3_5_HARDWARE_OUT_DIR}"

check-docs:
	$(PYTHON) tools/check_docs.py --repo-root . --json-out reports/docs_check.json --md-out reports/docs_check.md

docs-check: check-docs

deps-check:
	$(PYTHON) tools/check_deps.py --repo-root . --json-out reports/deps_check.json --md-out reports/deps_check.md

deps-host: deps-check

deps-rust:
	bash tools/bootstrap_rust.sh

deps-idf:
	bash tools/bootstrap_idf.sh

deps-bootstrap:
	bash tools/bootstrap_deps.sh

bootstrap-deps: deps-bootstrap

build-guest:
	bash tools/build_guest_wasm.sh

build-firmware:
	bash tools/build_firmware.sh

idf-matrix-validate:
	$(PYTHON) tools/check_idf_matrix.py --matrix firmware/idf-family-matrix.json --check-locks

idf-reference-qualify: idf-matrix-validate
	$(PYTHON) tools/qualify_idf_matrix.py \
		--matrix firmware/idf-family-matrix.json \
		--out-dir "$${WDC_IDF_MATRIX_OUT_DIR:-$${WDC_IDF_OUT_DIR:-reports/idf-family/esp32s3-reference-qualification}}" \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

idf-family-probe: idf-matrix-validate
	$(PYTHON) tools/qualify_idf_matrix.py \
		--matrix firmware/idf-family-matrix.json \
		--out-dir "$${WDC_IDF_MATRIX_OUT_DIR:-reports/idf-family/matrix-qualification}" \
		--include-exploratory \
		--timeout "$${WDC_IDF_TIMEOUT_SECONDS:-1800}"

idf-family-qualify: idf-family-probe

idf-family-docs-check:
	$(PYTHON) tools/check_idf_family_docs.py

idf-family-seal-check: idf-matrix-validate idf-family-docs-check

check-full:
	$(PYTHON) tools/check_docs.py --repo-root . --json-out reports/docs_check_report.json --md-out reports/docs_check_report.md
	$(PYTHON) -B tools/check_r9.py > reports/logs/r9_production_hardening_check.log
	$(PYTHON) -B tools/write_r9_report.py --repo-root .

check-full-network:
	$(PYTHON) tools/check_docs.py --repo-root . --json-out reports/docs_check_report.json --md-out reports/docs_check_report.md
	$(PYTHON) -B tools/check_r9.py > reports/logs/r9_production_hardening_check.log
	$(PYTHON) -B tools/write_r9_report.py --repo-root .

firmware-build: build-firmware

guest-wasm: build-guest

regenerate-r2-wasm:
	$(PYTHON) tools/gen_r2_wasm.py

clean:
	rm -rf firmware/build guest-sdk/rust/target guest-sdk/rust/examples/noop_bundle/target guest-sdk/rust/examples/relay_toggle/target build/guest-wasm
	find reports -mindepth 1 -maxdepth 1 ! -name README.md ! -name .gitkeep ! -name logs -exec rm -rf {} +
	find reports/logs -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
