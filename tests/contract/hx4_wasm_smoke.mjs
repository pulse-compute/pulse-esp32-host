import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const wasmPath = fileURLToPath(
  new URL(
    "../../firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm",
    import.meta.url,
  ),
);
const wasmBytes = await readFile(wasmPath);
const expectedRequest = Buffer.from([
  0xa2,
  0x18, 0x26, 0x1a, 0x45, 0x43, 0x48, 0x4f,
  0x09, 0x48, 0x68, 0x78, 0x34, 0x2d, 0x65, 0x63, 0x68, 0x6f,
]);
const completionResponse = Buffer.from([
  0xa7,
  0x00, 0x00,
  0x18, 0x26, 0x1a, 0x45, 0x43, 0x48, 0x4f,
  0x18, 0x27, 0x01,
  0x18, 0x28, 0x19, 0x07, 0xd0,
  0x18, 0x29, 0x01,
  0x18, 0x2a, 0x00,
  0x09, 0x48, 0x68, 0x78, 0x34, 0x2d, 0x65, 0x63, 0x68, 0x6f,
]);

let memory;
const calls = [];
const imports = {
  wdc: {
    wdc_host_call(opcode, requestPtr, requestLen, responsePtr, responseCap) {
      if (!(memory instanceof WebAssembly.Memory)) {
        throw new Error("guest memory was unavailable to the host import");
      }
      const bytes = new Uint8Array(memory.buffer);
      if (
        requestPtr < 0 || requestLen < 0 || responsePtr < 0 || responseCap < 0 ||
        requestPtr + requestLen > bytes.length ||
        responsePtr + responseCap > bytes.length
      ) {
        throw new Error("guest supplied an out-of-bounds host-call span");
      }
      const request = Buffer.from(bytes.slice(requestPtr, requestPtr + requestLen));
      if (opcode !== 0x0801) {
        throw new Error(`unexpected opcode ${opcode}`);
      }
      if (!request.equals(expectedRequest)) {
        throw new Error(`unexpected request ${request.toString("hex")}`);
      }
      if (completionResponse.length > responseCap) {
        throw new Error("completion response does not fit the guest-provided bound");
      }
      bytes.set(completionResponse, responsePtr);
      calls.push({
        opcode,
        request_ptr: requestPtr,
        request_len: requestLen,
        response_ptr: responsePtr,
        response_cap: responseCap,
        operation_id: 0x4543484f,
        payload: "hx4-echo",
        response_len: completionResponse.length,
      });
      return 0;
    },
  },
};

const compiled = await WebAssembly.compile(wasmBytes);
const instance = await WebAssembly.instantiate(compiled, imports);
memory = instance.exports.memory;
if (!(memory instanceof WebAssembly.Memory)) {
  throw new Error("HX4 fixture does not export memory");
}

const lifecycle = {
  init: instance.exports.wdc_module_init(),
  on_event: instance.exports.wdc_module_on_event(3072, 0),
  health: instance.exports.wdc_module_health(),
  shutdown: instance.exports.wdc_module_shutdown(0),
};
if (Object.values(lifecycle).some((status) => status !== 0)) {
  throw new Error(`non-OK lifecycle result ${JSON.stringify(lifecycle)}`);
}
if (calls.length !== 1) {
  throw new Error(`expected one effect host call, observed ${calls.length}`);
}

const moduleImports = WebAssembly.Module.imports(compiled);
const moduleExports = WebAssembly.Module.exports(compiled);
const moduleText = wasmBytes.toString("latin1");
const targetNeutral =
  !moduleText.includes("esp32s3") &&
  !moduleText.includes("esp32c6") &&
  !moduleText.includes("xtensa") &&
  !moduleText.includes("riscv");
if (!targetNeutral) {
  throw new Error("common Wasm fixture contains a target selector");
}

console.log(JSON.stringify({
  status: "PASS",
  wasm_sha256: createHash("sha256").update(wasmBytes).digest("hex"),
  wasm_bytes: wasmBytes.length,
  target_neutral: targetNeutral,
  imports: moduleImports,
  exports: moduleExports,
  lifecycle,
  calls,
}));
