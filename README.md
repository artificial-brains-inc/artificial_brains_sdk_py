# ArtificialBrains Python SDK

This repository contains a Python SDK for interacting with the
Artificial Brains API. Artificial Brains is the end-to-end platform for building biologically inspired brain for robots, using a new apporach to robotic intelligence based on Spiking Neural Networks, bringing continual learning and edge computing as its main benefits. 

This SDK wraps the REST and realtime endpoints and
provides helpers for streaming sensor data, decoding neural output
spikes into robot commands, building feedback rasters and computing
rewards.  The goal of this SDK is to make it easy for developers to
connect their own robots, simulators or control systems to the
Artificial Brains backend without having to re‑implement the low level
protocol.

## Features

- **HTTP client** for starting and stopping runs and querying state
- **Realtime client** built on Socket.IO for streaming inputs and
  receiving telemetry at high rates
- **Input streamer** that automatically responds to server requests for
  sensor data
- **Decoder plugins** for converting brain output spikes into joint
  commands; includes a ready to use bipolar split decoder
- **Deviation and reward plugins** for computing error signals and
  global/per‑layer rewards
- **Feedback error generator** to build correction spikes from
  deviations
- **Reward modulation** helper mirroring biological-brains behaviour around rewards for learning rules

The SDK abstracts away the networking details and allows you to
focus on your controller and learning logic.

## Installation

### Requirements

This SDK requires Python **3.8** or newer.  It depends on the
following third party libraries:

- [`python‑socketio` ≥ 5.16.0](https://pypi.org/project/python-socketio/), released on
  24 December 2025【35173131248404†L25-L33】, which provides the Socket.IO client
  implementation used for realtime communication.
- [`httpx` ≥ 0.28.1](https://pypi.org/project/httpx/), released on
  6 December 2024【174665618111792†L25-L33】, a modern HTTP client that
  supports both synchronous and asynchronous APIs.

The SDK itself is pure Python and has no additional compiled
dependencies.

You can install the required dependencies into your project by
creating a `requirements.txt` file and running `pip install -r requirements.txt`:

```txt
python-socketio==5.16.0
httpx==0.28.1
```

After installing dependencies you can include this SDK in your
project by copying the `ab_sdk` directory into your source tree or
adding it to your Python path.

## Quick start

The typical workflow when using this SDK is:

1. Create an `ABClient` pointing at your Artificial Brains API:

   ```python
   from ab_sdk import ABClient
   client = ABClient("https://artificialbrains.app/api/", api_key="my_secret")
   
   # start a run for project 'robot_arm'
   run = client.start("robot_arm")
   ```

2. Attach sensor providers and start streaming inputs:

   ```python
   from ab_sdk import InputStreamer

   streamer = InputStreamer(run)
   
   # provider function returning the latest JPEG image from your camera
   def get_camera_frame():
       # user code here
       img_bytes = ...  # bytes of JPEG
       return {
           'format': 'jpeg',
           'meta': {'width': 640, 'height': 480},
           'data': img_bytes,
       }
   
   streamer.register_input('cam_rgb', 'Image', get_camera_frame)

   # provider function returning audio as raw PCM
   def get_audio_chunk():
       pcm = ...  # bytes of 16‑bit PCM
       return {
           'format': 'pcm16',
           'meta': {'sampleRate': 16000, 'channels': 1},
           'data': pcm,
       }
   streamer.register_kind('Audio', get_audio_chunk)

   streamer.start()
   ```

3. Define a decoder to turn output spikes into robot commands and
   create a control loop:

   ```python
   from ab_sdk import RobotLoop, BipolarSplitDecoder
   from ab_sdk.plugins.decoder import MappingEntry

   # define how each output population drives a joint
   mapping = [
       MappingEntry(output_id='V1', joint_index=0, gain=0.5, per_step_max=0.004),
       MappingEntry(output_id='L1', joint_index=1, gain=0.5, per_step_max=0.004),
       MappingEntry(output_id='P1', joint_index=-1, gain=1.0, per_step_max=0.001),
   ]
   decoder = BipolarSplitDecoder(mapping)
   run.set_decoder(decoder)

   # callback returning the current robot state
   def get_state():
       return {
           'q': [0.0, 0.0],        # joint positions
           'dq': [0.0, 0.0],       # joint velocities
           'grip': {'pos': 0.0},
           'dt': 0.02,
       }

   # callback applying the decoded command to your robot
   def apply_command(cmd):
       dq = cmd['dq']
       dg = cmd['dg']
       # send dq and dg to your motors / gripper here
       print(f"Move joints by {dq}, gripper by {dg}")

   loop = RobotLoop(run, state_provider=get_state, command_executor=apply_command)
   loop.run_forever()
   ```

4. Optionally implement deviation and reward policies:

   ```python
   from ab_sdk.plugins.deviation import DefaultDeviation
   from ab_sdk.plugins.reward import DefaultReward

   # attach default zero deviation policy
   run.set_deviation(DefaultDeviation(run))
   
   # attach a simple reward policy; this one returns a constant reward
   run.set_reward(DefaultReward(run))
   ```

Refer to the docstrings in each module for more detailed
documentation.

## Logging and error handling

The SDK uses Python's standard `logging` library.  All modules
inherit the root logger's configuration, so you can control the log
level globally by configuring logging in your application:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

During development you may wish to enable debug logging for a more
detailed view of the realtime messages being sent and received.  To
do so set the level for the `ab_sdk` namespace:

```python
logging.getLogger('ab_sdk').setLevel(logging.DEBUG)
```

If the SDK encounters a problem (for example a provider returns
invalid data) it will log an error and continue running.  Exceptions
raised by your callback code are logged with stack traces to aid in
debugging.  When a deviation or reward plugin returns values outside
the allowed range the SDK will clamp them to safe defaults.

## Contributing

This SDK is a reference implementation.  Feel free to fork it and
adapt it to your needs.  Please open issues or pull requests if you
find bugs or have suggestions.
