PYTHON ?= /usr/bin/python3 -B

.PHONY: \
	test validate \
	check-r0 check-r1 check-r2 check-r3 check-r3-5 check-r3_5 check-r3.5 check-r4 check-r5 check-r6 check-r7 check-r8 check-r8-1 check-r8_1 check-r8.1 check-r8-2 check-r8_2 check-r8.2 check-r9 check-docs docs-check \
	deps-check deps-host deps-rust deps-idf deps-bootstrap bootstrap-deps \
	build-guest build-firmware check-full check-full-network \
	firmware-build guest-wasm regenerate-r2-wasm clean

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
