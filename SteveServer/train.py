import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import asyncio
import json
import torch
import queue
import threading
import sys
import time
from websockets.server import serve
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv
from tqdm import tqdm
from mc_env import MinecraftPvPEnv

class ConnectionDroppedException(Exception):
    """Raised when the WebSocket client connection is closed during training."""
    pass

# Dynamic slot routing variables
connected_sockets = []
connection_lock = threading.Lock()
num_envs = 0
bridges = []
training_started = False

class ThreadBridge:
    def __init__(self):
        # Queues to pass state/actions between WebSocket event loop and Gymnasium thread
        self.state_queue = queue.Queue(maxsize=1)
        self.action_queue = queue.Queue(maxsize=1)
        self.client_connected = threading.Event()

    def step_exchange(self, action_dict):
        # Called by MinecraftPvPEnv.step() inside the training thread
        self.action_queue.put(action_dict)
        state = self.state_queue.get()
        if state is None:
            raise ConnectionDroppedException("Client disconnected")
        return state

    def reset_exchange(self, env_idx):
        # Called by MinecraftPvPEnv.reset() inside the training thread
        tqdm.write(f"Gymnasium Environment {env_idx} resetting, waiting for client tick data...")
        state = self.state_queue.get()
        if state is None:
            raise ConnectionDroppedException("Client disconnected")
        return state

# Custom Callback for elegant terminal progress and multi-client telemetry reporting
class TqdmCallback(BaseCallback):
    def __init__(self, total_timesteps):
        super().__init__(verbose=0)
        self.total_timesteps = total_timesteps
        self.pbar = None
        self.step_counter = 0

    def _on_training_start(self):
        # Create progress bar using sys.stdout to prevent overlap issues with other stdout prints
        self.pbar = tqdm(total=self.total_timesteps, desc="Training PPO Agent", file=sys.stdout, dynamic_ncols=True)

    def _on_step(self) -> bool:
        self.pbar.update(1)
        self.step_counter += 1
        
        # Update metrics every 5 ticks
        if self.step_counter % 5 == 0:
            try:
                # Accumulate telemetry lines for each environment
                lines = []
                for idx, env in enumerate(self.training_env.envs):
                    unwrapped = env.unwrapped
                    state = unwrapped.current_state or {}
                    action = unwrapped.last_action_dict or {}
                    reward = unwrapped.last_reward or 0.0
                    reward_components = unwrapped.last_reward_components or {}
                    
                    # Format active item
                    active_item_map = {0: "Sword", 1: "Fishing Rod"}
                    active_word = active_item_map.get(state.get("active_item", 0), "Sword")
                    
                    # Format moving inputs
                    move_map = {0: "Idle", 1: "W (Forward)", 2: "S (Backward)"}
                    strafe_map = {0: "Idle", 1: "A (Left)", 2: "D (Right)"}
                    combat_action_map = {0: "Idle", 1: "Attack", 2: "Block", 3: "Cast Rod", 4: "Reel Rod"}
                    
                    move_idx = action.get("forward_back", 0)
                    strafe_idx = action.get("strafe", 0)
                    combat_idx = action.get("combat_action", 0)
                    
                    move_str = move_map.get(move_idx, "Idle")
                    strafe_str = strafe_map.get(strafe_idx, "Idle")
                    combat_word = combat_action_map.get(combat_idx, "Idle")
                    
                    # Line 1: Self Stats (Padded)
                    hp_val = state.get('hp', 1.0) * 10.0
                    vel_x = state.get('vel_x', 0.0)
                    vel_y = state.get('vel_y', 0.0)
                    vel_z = state.get('vel_z', 0.0)
                    sprint_str = str(state.get('is_sprinting', False))
                    y_ground = float(state.get('y_ground', 0.0))
                    l1 = f"C{idx} SELF: HP: {hp_val:>4.1f}/10.0 | Vel: ({vel_x:>+6.2f}, {vel_y:>+6.2f}, {vel_z:>+6.2f}) | Sprint: {sprint_str:<5} | GroundDist: {y_ground:>5.2f}m"
                    
                    # Line 2: Opponent Stats (Padded)
                    opp_hp_val = state.get('opp_hp', 1.0) * 10.0
                    target_dist = state.get('target_dist', 999.0)
                    opp_rel_x = state.get('opp_rel_x', 0.0)
                    opp_rel_y = state.get('opp_rel_y', 0.0)
                    opp_rel_z = state.get('opp_rel_z', 0.0)
                    l2 = f"C{idx} OPP:  HP: {opp_hp_val:>4.1f}/10.0 | Dist: {target_dist:>6.2f}m | RelPos: ({opp_rel_x:>+6.1f}, {opp_rel_y:>+6.1f}, {opp_rel_z:>+6.1f})"
                    
                    # Line 3: Actions & Reward breakdown (Padded)
                    opp_yaw_offset = state.get('opp_yaw_offset', 0.0)
                    opp_pitch_offset = state.get('opp_pitch_offset', 0.0)
                    mouse_delta_x = action.get('mouse_delta_x', 0.0)
                    mouse_delta_y = action.get('mouse_delta_y', 0.0)
                    dmg_dealt = reward_components.get('dmg_dealt', 0.0)
                    dmg_taken = reward_components.get('dmg_taken', 0.0)
                    spacing = reward_components.get('spacing', 0.0)
                    aim_reward = reward_components.get('aim_reward', 0.0)
                    aim_back = reward_components.get('aim_back_penalty', 0.0)
                    far = reward_components.get('dist_far_penalty', 0.0)
                    dur = reward_components.get('rod_durability_penalty', 0.0)
                    l3 = f"C{idx} COMB: Move: {move_str:<12} | Combat: {combat_word:<8} | Mouse: ({mouse_delta_x:>+5.1f}, {mouse_delta_y:>+5.1f}) | LookOff: (Yaw: {opp_yaw_offset:>+6.1f}, Pitch: {opp_pitch_offset:>+6.1f}) | Reward: {reward:>+6.3f} (Dmg: {dmg_dealt:>+4.1f}/{dmg_taken:>+4.1f} | Space: {spacing:>+4.2f} | Aim: {aim_reward:>+4.2f} | Back: {aim_back:>+4.2f} | Far: {far:>+4.2f} | Dur: {dur:>+4.2f})"
                    
                    lines.extend([l1, l2, l3])
                
                # Global stats performance line (Padded)
                rate_val = self.pbar.format_dict['rate']
                rate_str = f"{rate_val:.1f} it/s" if rate_val is not None else "N/A"
                stats_line = f"STATS:    Step Counter: {self.step_counter:>6} | Rate: {rate_str:<10}"
                lines.append(stats_line)
                
                # Print output lines below progress bar and restore cursor position dynamically
                output_str = "".join([f"\n\033[K{line}" for line in lines])
                num_lines = len(lines)
                sys.stdout.write(f"{output_str}\033[{num_lines}A\r")
                sys.stdout.flush()
            except Exception:
                pass
        return True

    def _on_training_end(self):
        if self.pbar:
            self.pbar.close()
        print("\n" * (num_envs * 3 + 2))

# 1. Hardware Detection
device = torch.device("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
print(f"Using Hardware Interface: {device}")

# 2. WebSocket Event Loop Handler
async def tick_handler(websocket):
    global connected_sockets, num_envs, training_started, bridges
    
    with connection_lock:
        if training_started:
            print("Connection refused: Training loop has already initialized.")
            return
        connected_sockets.append(websocket)
        env_idx = len(connected_sockets) - 1
        
    print(f"Minecraft Client {env_idx} connected! (Waiting for training initialization...)")
    
    try:
        # Await countdown phase completion
        while not training_started:
            await asyncio.sleep(0.1)
            
        bridge = bridges[env_idx]
        bridge.client_connected.set()
        
        async for message in websocket:
            # A. Receive state packet from Forge client
            state = json.loads(message)
            
            # B. Forward state to corresponding Gym environment bridge queue
            bridge.state_queue.put(state)
            
            # C. Wait for corresponding environment to step and push the action
            loop = asyncio.get_running_loop()
            action = await loop.run_in_executor(None, bridge.action_queue.get)
            
            # D. Send response actions back to client
            await websocket.send(json.dumps(action))
            
    except Exception as e:
        print(f"WebSocket closed/error for client {env_idx}: {e}")
    finally:
        with connection_lock:
            if not training_started:
                if websocket in connected_sockets:
                    connected_sockets.remove(websocket)
                    print(f"Client disconnected before training started. Remaining count: {len(connected_sockets)}")
            else:
                bridge.client_connected.clear()
                try:
                    bridge.state_queue.put_nowait(None)
                except queue.Full:
                    pass
                # Clean bridge queues
                while not bridge.state_queue.empty():
                    try:
                        bridge.state_queue.get_nowait()
                    except queue.Empty:
                        break
                while not bridge.action_queue.empty():
                    try:
                        bridge.action_queue.get_nowait()
                    except queue.Empty:
                        break

def run_websocket_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def start_server():
        async with serve(tick_handler, "localhost", 8765, ping_interval=None, ping_timeout=None):
            await asyncio.Future()
            
    loop.run_until_complete(start_server())

# 3. Training Worker
def training_worker():
    global num_envs, bridges, training_started
    
    print("Awaiting connection from Minecraft on ws://localhost:8765...")
    
    # Wait until at least one client has connected
    while True:
        with connection_lock:
            if len(connected_sockets) > 0:
                break
        time.sleep(0.1)
        
    print("Client detected! Waiting 5 seconds for any other clients to connect...")
    time.sleep(5.0)
    
    with connection_lock:
        num_envs = len(connected_sockets)
        training_started = True
        bridges = [ThreadBridge() for _ in range(num_envs)]
        
    print(f"Initializing PPO agent with {num_envs} environment(s) in parallel...")
    
    # Recreate vectorized environments matching exact client slot indexes
    def make_env(env_idx):
        return lambda: MinecraftPvPEnv(websocket_server_queue=bridges[env_idx], env_idx=env_idx)
        
    envs = DummyVecEnv([make_env(i) for i in range(num_envs)])
    
    model = PPO(
        policy="MlpPolicy",
        env=envs,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        verbose=0,
        device=device
    )
    
    print(f"Starting actual RL learning loop (total_timesteps=100000) for {num_envs} environments...")
    try:
        model.learn(total_timesteps=100000, callback=TqdmCallback(100000), reset_num_timesteps=False)
        model.save("ppo_minecraft_pvp")
        print("Training completed! Saved model to 'ppo_minecraft_pvp.zip'")
    except ConnectionDroppedException:
        print("One or more clients disconnected. Saving model progress...")
        model.save("ppo_minecraft_pvp")
    except KeyboardInterrupt:
        print("\nTraining interrupted by user (Ctrl+C). Saving model progress...")
        model.save("ppo_minecraft_pvp")
        print("Model saved successfully to 'ppo_minecraft_pvp.zip'. Exiting.")
    except Exception as e:
        print(f"Training interrupted due to error: {e}")
        model.save("ppo_minecraft_pvp")

def main():
    # Start the WebSocket server in a background daemon thread
    ws_thread = threading.Thread(target=run_websocket_server, daemon=True)
    ws_thread.start()
    
    # Run the training loop in the main thread so it captures Ctrl+C (KeyboardInterrupt)
    training_worker()

if __name__ == "__main__":
    main()
