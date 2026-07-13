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
    print("🚀 Using Hardware Interface: CUDA (Nvidia GPU)")
elif torch.backends.mps.is_available():
    device = torch.device("mps")
    device_name = "mps"
    print("🚀 Using Hardware Interface: Metal (Apple Silicon)")
else:
    device = torch.device("cpu")
    print("🚀 Using Hardware Interface: CPU")

# 2. Initialize Gym Environment and Model
# We create a dummy model for inference. In a real workflow, you would load a saved model:
# model = PPO.load("ppo_minecraft_pvp", device=device)
dummy_env = MinecraftPvPEnv()
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
        print("🔌 Minecraft Client Successfully Connected!")
        
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
                fb_val = action[0]
                if fb_val < -0.3:
                    forward_back = 2 # S (Backward)
                elif fb_val > 0.3:
                    forward_back = 1 # W (Forward)
                else:
                    forward_back = 0 # Idle
                    
                str_val = action[1]
                if str_val < -0.3:
                    strafe = 2 # D (Right)
                elif str_val > 0.3:
                    strafe = 1 # A (Left)
                else:
                    strafe = 0 # Idle

                mod_val = action[2]
                if mod_val < -0.3:
                    modifier = 1 # Shift (Sneak)
                elif mod_val > 0.3:
                    modifier = 2 # Space (Jump)
                else:
                    modifier = 0 # Normal

                comb_val = action[3]
                if comb_val < -0.6:
                    combat_action = 0 # Idle
                elif comb_val < -0.2:
                    combat_action = 1 # Attack
                elif comb_val < 0.2:
                    combat_action = 2 # Block
                elif comb_val < 0.6:
                    combat_action = 3 # Cast Rod
                else:
                    combat_action = 4 # Reel Rod In

                # Scale mouse delta back to degrees/pixels
                mouse_delta_x = float(action[4] * 15.0)
                mouse_delta_y = float(action[5] * 10.0)

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
            print(f"❌ Connection Dropped or Error: {e}")
        finally:
            self.websocket = None

coordinator = WebSocketCoordinator()

async def main():
    print("⏳ Awaiting connection from Minecraft on ws://localhost:8765...")
    async with serve(coordinator.handle_client, "localhost", 8765):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
