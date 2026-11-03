# Oracle 2: engine-core

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/v1/executor/test_vllm_net_devices.py:33 `test_normalize_pci_short_form` | `normalize_pci('bus:dev.fn')` returns `(0, bus, dev, fn)` | `oracle-engine-core-normalize-pci-short-form` | untranslatable | string parsing of a PCI BDF (vllm/v1/executor/vllm_net_devices.py:26-64) | Below the model's level. Note: the model has no vllm_net_devices (NIC-to-GPU selection) behavior at all; the scenario's trace expectation fails to record that |
| tests/engine/test_arg_utils.py:666 `test_composite_arg_parser` | `--mm-processor-kwargs` JSON becomes a dict on the args namespace (None when absent) | `oracle-engine-core-composite-arg-parser` | pass | none (argparse JSON decoding itself is below the model) | `engine-args.from-cli-args` -> `engine-args.post-init` carries `mm_processor_kwargs: {num_crops: 4}` with no warnings. Weak: `ConfigEngineArgs` does not declare `mm_processor_kwargs`; it passes through `merge(input, ...)` |
| tests/engine/test_arg_utils.py:902 `test_device_ids_with_uuid_args_resolve_to_physical_ids` | `device_ids=['GPU-abcd1234']` resolves via the platform to physical `[4]` | `oracle-engine-core-device-ids-uuid-args-resolve` | model-bug | `engine-args.create-engine-config` / `ConfigEngineArgs` / `parallel-config.post-init`: no `device_ids`, no `_resolve_device_ids`, no `assigned_physical_gpu_ids` | Run ok but `parallel_config.assigned_physical_gpu_ids` absent. Code: arg_utils.py:529, 2101-2140, 2586 |

## Fix requests (owning area: engine-core)

1. **--device-ids.** Add `device_ids` to `ConfigEngineArgs` and model `EngineArgs._resolve_device_ids` in `create-engine-config`: duplicates -> ValueError; all UUIDs -> `platform.device_control_id_to_physical_device_id` (seedable platform state); mixing ints and UUIDs -> ValueError "must not mix"; ints compose with CUDA_VISIBLE_DEVICES with a range check; result stored as `parallel_config.assigned_physical_gpu_ids`.
2. (minor) Declare `mm_processor_kwargs` in `ConfigEngineArgs` and carry it into the model config (arg_utils.py:642, 1995).
