# IDF 5.4.4 component locks

These four files are target-aware outputs from ESP-IDF Component Manager for
the sole maintained lane. They are build inputs, not hardware or runtime
evidence.

Regenerate them from the repository root in the matrix-pinned image:

```bash
docker run --rm --platform linux/amd64 \
  -v "$PWD:/project" -w /project \
  espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82 \
  bash -lc '
    python3 -B tools/verify_idf_environment.py
    python3 -B tools/build_idf_cell.py --cell esp32s3-reference --update-lock
    python3 -B tools/build_idf_cell.py --cell esp32-compile --update-lock
    python3 -B tools/build_idf_cell.py --cell esp32c3-compile --update-lock
    python3 -B tools/build_idf_cell.py --cell esp32c6-compile --update-lock
    python3 -B tools/check_idf_matrix.py --check-locks
  '
```

Run the same four updates a second time. Every report must contain
`"changed": false`; any difference fails the reproducibility gate. Save the
command output and `check_idf_matrix.py --check-locks` JSON outside the source
tree as review evidence.

The lock validator pins:

- lock format and internal target;
- IDF `5.4.4`;
- WAMR `2.4.0~1`;
- Espressif registry source;
- WAMR component hash
  `04f25aad2896b5e906397a061d35cce560609bebd3913a4be7e365ecbf2dd9d6`;
- manifest hash
  `2915c87bbbb4002ac21c3e598680f5204fded60ca89131ba8adb3a8b8f0a3148`;
  and
- the exact advertised target list.

Flashing, board selection, electrical checks, runtime memory behavior,
FreeRTOS/core policy, network transports, Pulse capability ABI design, and the
ESP32 provider are explicitly deferred.
