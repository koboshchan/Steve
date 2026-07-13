import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import asyncio
import json
import torch
import queue
import threading
from websockets.server import serve
from stable_baselines3 import PPO
from mc_env import MinecraftPvPEnv

# 1. Hardware Detection
device = torch.device("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
print(f"🚀 Using Hardware Interface: {device}")

# 2. Threading Bridge for Sync-Async Coordination
class ThreadBridge:
    def __init__(self):
        # Queues to pass state/actions between WebSocket event loop and Gymnasium thread
        self.state_queue = queue.Queue(maxsize=1)
        self.action_queue = queue.Queue(maxsize=1)
        self.client_connected = threading.Event()

    def step_exchange(self, action_dict):
        # Called by MinecraftPvPEnv.step() inside the training thread
        # 1. Push action to the event loop
        self.action_queue.put(action_dict)
        # 2. Block until the next tick state is received from the event loop
        return self.state_queue.get()

    def reset_exchange(self):
        # Called by MinecraftPvPEnv.reset() inside the training thread
        # Block until client connects and sends the initial tick state
        print("⏳ Gymnasium Environment resetting, waiting for client tick data...")
        return self.state_queue.get()

bridge = ThreadBridge()

# 3. Training Thread Worker
def training_worker():
    # Instantiate custom env with the bridge
    env = MinecraftPvPEnv(websocket_server_queue=bridge)
    
    print("🤖 Initializing PPO agent...")
    # Initialize PPO model
    model = PPO(
        policy="MlpPolicy",
        env=env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        verbose=1,
        device=device
    )
    
    print("🏋️ Starting actual RL learning loop (total_timesteps=100000)...")
    try:
        model.learn(total_timesteps=100000)
        model.save("ppo_minecraft_pvp")
        print("💾 Training completed! Saved model to 'ppo_minecraft_pvp.zip'")
    except Exception as e:
        print(f"❌ Training interrupted: {e}")

# 4. WebSocket Event Loop Handler
async def tick_handler(websocket):
    print("🔌 Minecraft Client connected to Training Server!")
    bridge.client_connected.set()
    
    try:
        async for message in websocket:
            # A. Receive state packet from Forge client
            state = json.loads(message)
            
            # B. Forward state to Gymnasium env (blocks if gym is not ready)
            bridge.state_queue.put(state)
            
            # C. Wait for Gymnasium env to step and return the action
            loop = asyncio.get_running_loop()
            action = await loop.run_in_executor(None, bridge.action_queue.get)
            
            # D. Send the selected action back to Forge client
            await websocket.send(json.dumps(action))
            
    except Exception as e:
        print(f"❌ WebSocket connection closed: {e}")
    finally:
        bridge.client_connected.clear()
        # Clean queues to prevent deadlock on disconnect
        while not bridge.state_queue.empty():
            bridge.state_queue.get_nowait()
        while not bridge.action_queue.empty():
            bridge.action_queue.get_nowait()

async def main():
    # Start the training loop in a background thread
    t = threading.Thread(target=training_worker, daemon=True)
    t.start()
    
    print("⏳ Awaiting connection from Minecraft on ws://localhost:8765...")
    async with serve(tick_handler, "localhost", 8765):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
