# wdc_safety

Safety state and physical-output guard.

Implemented behavior:

- safe GPIO defaults;
- no-bundle safety state;
- app-running safety state;
- fault-stopped safety state;
- denial of physical writes while stopped or in no-bundle mode;
- forcing outputs safe on app/runtime fault;
- safety status counters.

Any new physical operation should be routed through a safety check equivalent to the GPIO path.
