import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const trapCycles = 64;
const pressureBytes = 4 * 1024 * 1024;
const commonPath = fileURLToPath(
  new URL(
    "../../firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm",
    import.meta.url,
  ),
);
const trapPath = fileURLToPath(
  new URL(
    "../../firmware/components/wdc_runtime/test_vectors/wdc_static_event_trap_wasm.wasm",
    import.meta.url,
  ),
);
const commonBytes = await readFile(commonPath);
const trapBytes = await readFile(trapPath);
const commonModule = await WebAssembly.compile(commonBytes);
const trapModule = await WebAssembly.compile(trapBytes);
const pressure = Buffer.alloc(pressureBytes);
let pressureChecksum = 0;
let traps = 0;
let recoveries = 0;
let hostCalls = 0;

for (let index = 0; index < pressure.length; index += 4096) {
  pressure[index] = (index / 4096 + 17) & 0xff;
  pressureChecksum = (pressureChecksum + pressure[index]) >>> 0;
}

for (let cycle = 0; cycle < trapCycles; cycle += 1) {
  const trapInstance = await WebAssembly.instantiate(trapModule, {
    wdc: { wdc_log: () => 0 },
  });
  if (trapInstance.exports.wdc_module_init() !== 0) {
    throw new Error(`trap fixture init failed in cycle ${cycle}`);
  }
  try {
    trapInstance.exports.wdc_module_on_event(0, 0);
    throw new Error(`trap fixture returned in cycle ${cycle}`);
  } catch (error) {
    if (!(error instanceof WebAssembly.RuntimeError)) {
      throw error;
    }
    traps += 1;
  }

  let memory;
  let cycleCalls = 0;
  const commonInstance = await WebAssembly.instantiate(commonModule, {
    wdc: {
      wdc_host_call() {
        if (!(memory instanceof WebAssembly.Memory)) {
          throw new Error("common Wasm memory was unavailable");
        }
        cycleCalls += 1;
        hostCalls += 1;
        return 0;
      },
    },
  });
  memory = commonInstance.exports.memory;
  if (
    commonInstance.exports.wdc_module_init() !== 0 ||
    commonInstance.exports.wdc_module_on_event(3072, 0) !== 0 ||
    cycleCalls !== 1
  ) {
    throw new Error(`post-trap common-Wasm recovery failed in cycle ${cycle}`);
  }
  recoveries += 1;
}

if (
  traps !== trapCycles ||
  recoveries !== trapCycles ||
  hostCalls !== trapCycles ||
  pressureChecksum === 0
) {
  throw new Error("HX5b Wasm pressure counters drifted");
}

console.log(JSON.stringify({
  schema: "pulse.esp32.hx5b-wasm-pressure-smoke.v1",
  status: "PASS",
  trap_cycles: trapCycles,
  traps,
  successful_recoveries: recoveries,
  host_calls: hostCalls,
  pressure_reservation_bytes: pressureBytes,
  pressure_checksum: pressureChecksum,
  common_wasm_sha256: createHash("sha256").update(commonBytes).digest("hex"),
  trap_wasm_sha256: createHash("sha256").update(trapBytes).digest("hex"),
}));
