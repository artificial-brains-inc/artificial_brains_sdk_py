"""Endpoint constants for brokered and direct realtime flows."""

# Node broker
NODE_INITIALIZE = "/robots/realtime/{project_id}/initialize"
NODE_TELEMETRY_START = "/robots/realtime/{project_id}/telemetry"
NODE_RUN_STOP = "/robots/realtime/{project_id}/run-stop"
NODE_SDK_RUN_STOPPED = "/robots/realtime/{project_id}/sdk-run-stopped"
NODE_SESSION = "/robots/realtime/{project_id}/session/{compile_id}"

# Python runtime
PY_COMPILE = "/compile"
PY_RUN_START = "/run/start"
PY_RUN_STOP = "/run/stop"
PY_INPUTS = "/inputs/load"
PY_REWARDS = "/rewards/apply"
PY_OUTPUTS = "/outputs/{compile_id}"