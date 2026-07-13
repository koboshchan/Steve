import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import asyncio
import json
import torch
import numpy as np
import gymnasium as gym
from websockets.server import serve
from stable_baselines3 import PPO
from mc_env import MinecraftPvPEnv

# 1. Hardware Detection System
device_name = "cpu"
if torch.cuda.is_available():
    device = torch.device("cuda")
    device_name = "cuda"
    print("Using Hardware Interface: CUDA (Nvidia GPU)")
elif torch.backends.mps.is_available():
    device = torch.device("mps")
    device_name = "mps"
    print("Using Hardware Interface: Metal (Apple Silicon)")
else:
    device = torch.device("cpu")
    print("Using Hardware Interface: CPU")

# 2. Initialize Gym Environment and Model
dummy_env = MinecraftPvPEnv()
model_path = "ppo_minecraft_pvp"

if os.path.exists(model_path + ".zip"):
    print(f"Loading trained weights from '{model_path}.zip'...")
    model = PPO.load(model_path, env=dummy_env, device=device)
else:
    print("WARNING: No trained model ('ppo_minecraft_pvp.zip') was found.")
    print("Initializing a brand-new model with RANDOM weights.")
    print("To train the model, run: python train.py")
    model = PPO("MlpPolicy", dummy_env, verbose=1, device=device)

class WebSocketCoordinator:
    """Coordinates between the async WebSocket loop and gym environment step calls."""
    def __init__(self):
        self.websocket = None
        self.latest_state = None
        self.state_received = asyncio.Event()

    async def handle_client(self, websocket):
        self.websocket = websocket
        self.state_received.clear()
        print("Minecraft Client Successfully Connected!")
        
        try:
            async for message in websocket:
                # 1. Parse client state JSON
                state = json.loads(message)
                self.latest_state = state
                self.state_received.set()
                
                # 2. Extract features for model inference
                obs = dummy_env._parse_observation(state)
                
                # 3. Model Predict (forward pass)
                action, _states = model.predict(obs, deterministic=True)
                
                # 4. Convert model action space outputs to WebSocket response commands
                move_idx = int(action[0])
                modifier = int(action[1])
                combat_action = int(action[2])
                mouse_x_idx = int(action[3])
                mouse_y_idx = int(action[4])

                # 0: idle, 1: w, 2: wd, 3: wa, 4: s, 5: sa, 6: sd, 7: a, 8: d
                move_mappings = {
                    0: (0, 0),  # Idle
                    1: (1, 0),  # W
                    2: (1, 2),  # W + D
                    3: (1, 1),  # W + A
                    4: (2, 0),  # S
                    5: (2, 1),  # S + A
                    6: (2, 2),  # S + D
                    7: (0, 1),  # A
                    8: (0, 2),  # D
                }
                forward_back, strafe = move_mappings.get(move_idx, (0, 0))

                # Scale mouse delta back to degrees/pixels
                mouse_delta_x = float((mouse_x_idx - 5) * 3.0)
                mouse_delta_y = float((mouse_y_idx - 4) * 2.5)

                response = {
                    "forward_back": forward_back,
                    "strafe": strafe,
                    "modifier": modifier,
                    "combat_action": combat_action,
                    "mouse_delta_x": mouse_delta_x,
                    "mouse_delta_y": mouse_delta_y
                }
                
                # 5. Send actions back to Forge Client
                await websocket.send(json.dumps(response))
                
        except Exception as e:
            print(f"Connection Dropped or Error: {e}")
        finally:
            self.websocket = None

coordinator = WebSocketCoordinator()

async def main():
    print("Awaiting connection from Minecraft on ws://localhost:8765...")
    async with serve(coordinator.handle_client, "localhost", 8765, ping_interval=None, ping_timeout=None):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
