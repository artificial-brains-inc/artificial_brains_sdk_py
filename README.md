# Artificial Brains Python SDK

A realtime SDK for connecting robots to **Artificial Brains**.

This SDK handles:
- communication with the brain runtime
- encoding sensor inputs into spike signals
- decoding spike outputs into control commands
- streaming inputs, outputs, and rewards in realtime

You focus on the robot.  
The SDK handles the brain.

---

## Core Idea

The system is split into two responsibilities:

**Controller (your configuration)**
- read sensors  
- apply motor commands  
- compute rewards  

**SDK**
- send inputs to the brain  
- receive outputs from the brain  
- route rewards to learning layers  
- manage realtime session lifecycle  

---

## Installation

```bash
pip install artificialbrains-sdk
```

---

## Quick Start

### 1. Configure

Create a `.env` file:

```
AB_PROJECT_ID=your_project_id
AB_PYTHON_URL=http://localhost:8000
AB_NODE_URL=http://localhost:3000
AB_API_KEY=your_api_key
```

---

### 2. Start a session

```python
from ab_sdk import ABClient

client = ABClient.from_env(env_path=".env")
session = client.start_from_env()
```

---

### 3. Send inputs

```python
session.publish_input(
    sensor="ps0",
    signal=1234.0,
    vmax=4095.0
)
```

---

### 4. Receive outputs

```python
def handle_output(output):
    print(output)

session.on_output(handle_output)
```

---

### 5. Send rewards

```python
session.send_global_reward(1.0)
session.send_local_reward("on_line", 0.5)
```

---

## Robot Loop (Recommended)

```python
from ab_sdk import RobotLoop

def get_state():
    return {
        "ps0": 1200.0,
        "ps1": 800.0,
    }

def compute_reward():
    return {
        "global": 0.1,
        "local": {"on_line": 1.0}
    }

def apply_command(cmd):
    print(cmd)

loop = RobotLoop(
    session,
    state_provider=get_state,
    reward_provider=compute_reward,
    command_executor=apply_command,
)

loop.run_forever()
```

---

## Architecture

### Session

`RealtimeSession` is the core runtime object.

It manages:
- input encoding
- output streaming
- reward routing
- decoder execution

---

### Maps

Maps define how the brain connects to your robot:

- **InputSensorMap** → sensors → brain inputs  
- **OutputMotorMap** → brain outputs → motors  
- **RewardMap** → outputs → learning layers  

Make sure your IDs in the brain match the IDs of the sensors and motors. 
---

### Encoder

`SpikeEncoder` converts sensor values into spike populations.

---

### Decoder

`GenericSpikeDecoder` converts spike activity into control commands.

The brain emits **spikes per output population** (neurons firing at each timestep).  
The decoder reconstructs this activity into dense vectors and transforms it into **actuator deltas**.

Each output is mapped using a **decoding scheme**:

- **`bipolarSplit`**  
  Splits the population in two halves:  
  first half = positive, second half = negative  
  → output = (positive − negative)  
  → useful for continuous control (e.g. wheels, joints)

- **`addition`**  
  Sums all active neurons  
  → output = total spike count  
  → useful for accumulating signals or intensity-based control

- **`booleanThreshold`**  
  Activates only if spike count crosses a threshold  
  → output = 1 or 0  
  → useful for discrete actions (e.g. trigger, grasp)

- **`bipolarScalar`**  
  Compares positive vs negative halves  
  → output ∈ {-1, 0, +1}  
  → useful for directional decisions

---

### From spikes to movement

The decoder pipeline is:

1. **Collect spikes** from runtime output  
2. **Reconstruct population activity** (bit vector per output)  
3. **Apply decoding scheme** → scalar value  
4. **Scale to delta** (using gain, limits, etc.)  
5. **Aggregate into command**

Final output:

```python
{
    "t": step,
    "deltas": {
        "left_wheel": 0.01,
        "right_wheel": -0.01,
    }
}

---

## Philosophy

The brain learns.  
The robot acts.  
The SDK connects them.

---


## License

Artificial Brains SDK is **source-available**.

You are free to:
- use the SDK in personal and commercial projects  
- integrate it into your robots, simulators, and applications  
- modify the code for your own internal use  

You may **not**:
- repackage or redistribute the SDK as a standalone product  
- offer the SDK as a hosted or managed service  
- use the SDK to build or operate a competing platform  
- sublicense or resell the SDK itself  

This SDK is designed to enable developers to build on top of Artificial Brains — not to replicate it.

If you are interested in partnerships, embedding at scale, or special licensing terms, contact us.
