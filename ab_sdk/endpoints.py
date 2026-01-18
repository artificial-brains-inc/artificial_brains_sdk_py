"""API endpoint definitions.

This module defines the HTTP endpoint paths used by the SDK relative
to the base URL provided when instantiating :class:`~ab_sdk.client.ABClient`.
Keeping these values in one place makes it easy to audit and update
the API surface when the server changes.

Note that all paths are joined to the base URL (for example
``https://artificialbrains.app/api``) so you should not include
``/api`` at the beginning when constructing the `ABClient`.
"""

START_RUN = "/robot/{project_id}/start"
"""POST start a new run.  Replace ``{project_id}`` with the target project identifier."""

STOP_RUN = "/robot/{project_id}/stop"
"""POST stop the current run for the project.  Safe to call even if no run is active."""

IO_STATE = "/robot/{project_id}/io/state"
"""GET fetch the current IO state (needed inputs, cycle, etc.) for resynchronization."""

# The following endpoints are used implicitly via Socket.IO events.  They are
# documented here for completeness; your backend should implement the
# corresponding handlers on its realtime gateway.

RUN_JOIN_EVENT = "run:join"
"""Client emits this event to join the room for a given run ID."""

IO_NEED_EVENT = "io:need"
"""Server emits this event to inform the client which inputs are needed for the next cycle."""

IO_CHUNK_EVENT = "io:chunk"
"""Client emits this event to send raw input data (image/audio/lidar/etc.) or feedback rasters."""

ROBOT_STATE_EVENT = "robot:state"
"""Client emits this event periodically with the robot's current joint positions, velocities and gripper state."""

ROBOT_CMD_EVENT = "robot:cmd"
"""Server may emit this legacy event with direct joint commands.  Newer versions omit this in favour of decoding on the client."""

CYCLE_UPDATE_EVENT = "cycle:update"
"""Server emits this event after each cycle with the latest telemetry (spike activity, error, etc.)."""

LEARN_REWARD_EVENT = "learn:reward"
"""Client emits this event with global and per‑layer reward values for STDP3 learning."""

CONTRACT = "/robot/{project_id}/contract"
"""GET fetch the IO/constants contract without starting a run."""
