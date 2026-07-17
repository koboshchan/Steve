# Steve

> Reinforcement learning agent that learns to PvP in Minecraft 1.8.9

Steve is a self-improving AI that learns Minecraft PvP combat from scratch using [Proximal Policy Optimization (PPO)](https://arxiv.org/abs/1707.06347). It connects to a live Minecraft 1.8.9 server, observes the game state in real-time, and trains against bots — learning movement, aiming, sword fighting, rod usage, and spatial awareness through pure trial and error.

## How It Works

Steve is split into three components that communicate over WebSocket:

```
┌──────────────┐   WebSocket    ┌──────────────┐    Minecraft     ┌──────────────┐
│  SteveServer │◄──────────────►│  SteveClient │◄────────────────►│  PVP Server  │
│  (Python)    │  state/actions │  (Forge Mod) │   game protocol  │  (Paper 1.8) │
│  PPO Agent   │                │  Tick Bridge │                  │  Bot Duels   │
└──────────────┘                └──────────────┘                  └──────────────┘
```

1. **SteveClient** — A Forge 1.8.9 mod that hooks into the client tick loop, extracts game state (HP, velocities, positions, aim offsets, distances), and sends it to the server every tick (50ms). It receives actions back and applies them as key presses, mouse movements, and combat inputs.

2. **SteveServer** — A Python WebSocket server that runs the PPO neural network. In inference mode (`server.py`), it receives state, runs a forward pass, and returns actions. In training mode (`train.py`), it manages a full RL training loop with parallel environments, reward shaping, and checkpointing.

3. **PVPServer** — A Dockerized Paper 1.8.8 Minecraft server with the StrikePractice plugin for bot dueling. Provides a controlled environment where Steve can fight bots of varying difficulty.

### Observation Space (41 features)

| Feature Group        | Dimensions | Description                              |
|----------------------|-----------:|------------------------------------------|
| Self stats           |          5 | HP, velocity (x/y/z), height above ground |
| Active item          |          2 | One-hot: sword, fishing rod              |
| Opponent stats       |          7 | HP, velocity (x/y/z), relative position  |
| Aim deltas           |          4 | Yaw/pitch offset to target (self + opponent) |
| Swing cooldown       |          1 | Current swing progress                   |
| Wall distances       |          4 | Raycast to front/right/back/left walls   |
| Absolute rotation    |          2 | Current pitch and yaw                    |
| Action history       |         15 | Last 3 ticks of actions (5 per tick)     |

### Action Space (MultiDiscrete)

| Action      | Bins | Description                                          |
|-------------|-----:|------------------------------------------------------|
| Movement    |    9 | Idle, W, WD, WA, S, SA, SD, A, D                    |
| Modifier    |    3 | Normal, Sneak, Jump                                  |
| Combat      |    4 | Idle, Attack, Block, Use Rod                         |
| Mouse X     |   11 | -15° to +15° yaw (3° steps)                         |
| Mouse Y     |    9 | -10° to +10° pitch (2.5° steps)                     |

## Prerequisites

- **Java 8** (JDK) — required for both the Forge mod and the PVP server
- **Python 3.10** with Conda
- **Docker** — for running the PVP practice server
- **Minecraft 1.8.9** with Forge

## Setup

### 1. PVP Server

```bash
cd PVPServer
docker compose up -d
```

This starts a Paper 1.8.8 server on port `25567` with offline mode enabled.

### 2. SteveServer (Python)

Create the Conda environment for your hardware:

```bash
cd SteveServer

# Apple Silicon (Metal)
conda env create -f metal-environment.yml
conda activate steve_server_metal

# NVIDIA GPU (CUDA 12.1)
conda env create -f cuda-environment.yml
conda activate steve_server_cuda

# CPU only
conda env create -f cpu-environment.yml
conda activate steve_server_cpu
```

### 3. SteveClient (Forge Mod)

Build the mod using Java 8:

```bash
cd SteveClient
JAVA_HOME=$(/usr/libexec/java_home -v 1.8) ./gradlew build
```

The compiled mod JAR will be in `build/libs/`. Copy it to your Minecraft Forge `mods/` folder.

## Usage

### Inference (Run the trained agent)

Start the inference server, then launch Minecraft and connect to the PVP server:

```bash
cd SteveServer
python server.py                    # default: easy difficulty
python server.py --difficulty hard   # or: easy, medium, hard
```

The server loads the trained weights from `ppo_minecraft_pvp.zip` and prints real-time telemetry:

```
SELF: HP: 20/20 | Vel: ( +0.00,  -0.08,  +0.00) | Sprint: True  | GroundDist:  0.00m
OPP:  HP: 18/20 | Dist:   3.24m | RelPos: (  +2.1,   +0.0,   -2.4)
COMB: Move: W (Forward)  | Combat: Attack   | Mouse: ( +3.0,  -2.5) | LookOff: (Yaw:   +1.2, Pitch:   -0.8)
```

### Training

Train a new agent or resume from a checkpoint:

```bash
cd SteveServer

# Train from scratch (100k steps)
python train.py --steps 100000

# Resume training from existing checkpoint
python train.py --steps 500000 --resume

# Train with harder bots and no heuristic rewards
python train.py --steps 200000 --resume --difficulty hard --no-action-suggest
```

> [!NOTE]
> Training supports multiple parallel Minecraft clients. Connect multiple game instances before the 5-second countdown to train with more environments simultaneously.

Model checkpoints are saved automatically every 15,000 steps to `backup/` and on exit to `ppo_minecraft_pvp.zip`.

### Training Arguments

| Argument             | Default   | Description                                        |
|----------------------|-----------|----------------------------------------------------|
| `--steps`            | `100000`  | Total environment steps to train for               |
| `--resume`           | `false`   | Resume from existing `ppo_minecraft_pvp.zip`       |
| `--difficulty`       | `easy`    | Bot difficulty: `easy`, `medium`, `hard`           |
| `--no-action-suggest`| `false`   | Disable heuristic shaping rewards (pitch/facing)   |

## Architecture

The PPO agent uses an MLP policy with two hidden layers of 256 units each for both the policy and value networks. Observations are frame-stacked (4 frames) to give the agent temporal context.

### Reward Signal

| Component               | Value            | Trigger                          |
|--------------------------|-----------------|-----------------------------------|
| Aim accuracy             | +0.15 to -0.20  | Every tick, based on crosshair offset |
| Distance shaping         | +0.03 (peak)    | Gaussian peaked at 3 blocks      |
| Damage dealt             | +5.0 per heart  | On hitting the opponent           |
| Damage taken             | -4.0 per heart  | On being hit                      |
| Kill bonus               | +50.0           | Opponent eliminated               |
| Death penalty            | -50.0           | Agent eliminated                  |
| Wall proximity           | -0.05 (compounds) | Within 1 block of a wall        |
| Corner penalty           | -0.25 (compounds) | Within 1 block of two walls     |

## Project Structure

```
Steve/
├── SteveServer/           # Python RL server
│   ├── server.py          # Inference server (WebSocket → model → actions)
│   ├── train.py           # Training loop (multi-env PPO with live clients)
│   ├── mc_env.py          # Gymnasium environment (observation/action/reward)
│   └── *-environment.yml  # Conda environments (Metal / CUDA / CPU)
├── SteveClient/           # Minecraft Forge 1.8.9 mod
│   └── src/main/java/
│       └── com/example/examplemod/
│           ├── ClientTickHandler.java       # Tick loop: state extraction + action execution
│           ├── SteveWebSocketClient.java    # Lock-step WebSocket bridge
│           ├── ExampleMod.java              # Forge mod entry point
│           └── SteveMainMenu.java           # Custom main menu (Rosetta-safe)
└── PVPServer/             # Dockerized practice server
    ├── docker-compose.yml # Paper 1.8.8 + plugins
    ├── StrikePractice/    # Bot duel plugin (config + source)
    └── data/              # Server data volume
```
