import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const commonWasmPath = fileURLToPath(
  new URL(
    "../../firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm",
    import.meta.url,
  ),
);
const trapWasmPath = fileURLToPath(
  new URL(
    "../../firmware/components/wdc_runtime/test_vectors/wdc_static_event_trap_wasm.wasm",
    import.meta.url,
  ),
);
const commonBytes = await readFile(commonWasmPath);
const trapBytes = await readFile(trapWasmPath);
const expectedRequest = Buffer.from([
  0xa2,
  0x18, 0x26, 0x1a, 0x45, 0x43, 0x48, 0x4f,
  0x09, 0x48, 0x68, 0x78, 0x34, 0x2d, 0x65, 0x63, 0x68, 0x6f,
]);
const rejectionStatuses = [-6, -4, -11, -16, -9];

const commonModule = await WebAssembly.compile(commonBytes);
const propagations = [];
for (const hostStatus of rejectionStatuses) {
  let memory;
  let calls = 0;
  const instance = await WebAssembly.instantiate(commonModule, {
    wdc: {
      wdc_host_call(opcode, requestPtr, requestLen, responsePtr, responseCap) {
        if (!(memory instanceof WebAssembly.Memory)) {
          throw new Error("common Wasm memory was unavailable");
        }
        const bytes = new Uint8Array(memory.buffer);
        if (
          requestPtr < 0 || requestLen < 0 || responsePtr < 0 || responseCap < 0 ||
          requestPtr + requestLen > bytes.length ||
          responsePtr + responseCap > bytes.length
        ) {
          throw new Error("common Wasm supplied an out-of-bounds host-call span");
        }
        const request = Buffer.from(bytes.slice(requestPtr, requestPtr + requestLen));
        if (opcode !== 0x0801 || !request.equals(expectedRequest)) {
          throw new Error("common Wasm effect request drifted");
        }
        calls += 1;
        return hostStatus;
      },
    },
  });
  memory = instance.exports.memory;
  if (instance.exports.wdc_module_init() !== 0) {
    throw new Error("common Wasm init failed");
  }
  const guestStatus = instance.exports.wdc_module_on_event(3072, 0);
  if (guestStatus !== hostStatus || calls !== 1) {
    throw new Error(
      `host status ${hostStatus} became ${guestStatus} across ${calls} calls`,
    );
  }
  propagations.push({ host_status: hostStatus, guest_status: guestStatus, calls });
}

const trapModule = await WebAssembly.compile(trapBytes);
const trapInstance = await WebAssembly.instantiate(trapModule, {
  wdc: { wdc_log: () => 0 },
});
if (trapInstance.exports.wdc_module_init() !== 0) {
  throw new Error("event-trap fixture init failed");
}
let trapped = false;
let trapName = null;
try {
  trapInstance.exports.wdc_module_on_event(0, 0);
} catch (error) {
  if (!(error instanceof WebAssembly.RuntimeError)) {
    throw error;
  }
  trapped = true;
  trapName = error.name;
}
if (!trapped) {
  throw new Error("event-trap fixture returned instead of trapping");
}

const text = commonBytes.toString("latin1");
const targetNeutral = ["esp32s3", "esp32c6", "xtensa", "riscv", "IDF_TARGET"]
  .every((token) => !text.includes(token));
if (!targetNeutral) {
  throw new Error("common Wasm contains a target selector");
}

console.log(JSON.stringify({
  status: "PASS",
  common_wasm_sha256: createHash("sha256").update(commonBytes).digest("hex"),
  common_wasm_bytes: commonBytes.length,
  target_neutral: targetNeutral,
  status_propagations: propagations,
  event_trap: {
    observed: trapped,
    error_name: trapName,
    wasm_sha256: createHash("sha256").update(trapBytes).digest("hex"),
    wasm_bytes: trapBytes.length,
  },
}));
