import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import asyncio
import json
import torch
import queue
import threading
import sys
from websockets.server import serve
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from tqdm import tqdm
from mc_env import MinecraftPvPEnv

class ConnectionDroppedException(Exception):
    """Raised when the WebSocket client connection is closed during training."""
    pass

# Custom Callback for elegant terminal progress and telemetry reporting
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
                env = self.training_env.envs[0].unwrapped
                state = env.current_state or {}
                action = env.last_action_dict or {}
                reward = env.last_reward
                
                # Format moving inputs
                move_map = {0: "Idle", 1: "W (Forward)", 2: "S (Backward)"}
                strafe_map = {0: "Idle", 1: "A (Left)", 2: "D (Right)"}
                mod_map = {0: "None", 1: "Shift (Sneak)", 2: "Space (Jump)"}
                combat_action_map = {0: "Idle", 1: "Attack", 2: "Block", 3: "Cast Rod", 4: "Reel Rod"}
                active_item_map = {0: "Sword", 1: "Fishing Rod"}
                
                move_str = move_map.get(action.get("forward_back", 0), "Idle")
                strafe_str = strafe_map.get(action.get("strafe", 0), "Idle")
                mod_str = mod_map.get(action.get("modifier", 0), "None")
                combat_word = combat_action_map.get(action.get("combat_action", 0), "Idle")
                active_word = active_item_map.get(state.get("active_item", 0), "Sword")
                
                # Line 1: Self Stats (Padded)
                hp_val = state.get('hp', 1.0) * 10.0
                vel_x = state.get('vel_x', 0.0)
                vel_y = state.get('vel_y', 0.0)
                vel_z = state.get('vel_z', 0.0)
                sprint_str = str(state.get('is_sprinting', False))
                y_ground = float(state.get('y_ground', 0.0))
                line1 = f"SELF:     HP: {hp_val:>4.1f}/10.0 | Vel: ({vel_x:>+6.2f}, {vel_y:>+6.2f}, {vel_z:>+6.2f}) | Sprint: {sprint_str:<5} | GroundDist: {y_ground:>5.2f}m"
                
                # Line 2: Opponent Stats (Padded)
                opp_hp_val = state.get('opp_hp', 1.0) * 10.0
                target_dist = state.get('target_dist', 999.0)
                opp_rel_x = state.get('opp_rel_x', 0.0)
                opp_rel_y = state.get('opp_rel_y', 0.0)
                opp_rel_z = state.get('opp_rel_z', 0.0)
                line2 = f"OPPONENT: HP: {opp_hp_val:>4.1f}/10.0 | Dist: {target_dist:>6.2f}m | RelPos: ({opp_rel_x:>+6.1f}, {opp_rel_y:>+6.1f}, {opp_rel_z:>+6.1f})"
                
                # Line 3: Gaze & Look offsets (Padded)
                yaw_delta = state.get('yaw_delta', 0.0)
                pitch_delta = state.get('pitch_delta', 0.0)
                opp_yaw_offset = state.get('opp_yaw_offset', 0.0)
                opp_pitch_offset = state.get('opp_pitch_offset', 0.0)
                line3 = f"LOOK:     SelfToOpp: (Yaw: {yaw_delta:>+6.1f}, Pitch: {pitch_delta:>+6.1f}) | OppToSelf: (Yaw: {opp_yaw_offset:>+6.1f}, Pitch: {opp_pitch_offset:>+6.1f})"
                
                # Line 4: Hotbar & Match Status (Padded)
                sword_slot = str(state.get('sword_slot', -1))
                rod_slot = str(state.get('rod_slot', -1))
                dye_slot = str(state.get('lime_dye_slot', -1))
                in_match_str = str(state.get('in_match', False))
                line4 = f"HOTBAR:   Active: {active_word:<11} | Sword Slot: {sword_slot:<2} | Rod Slot: {rod_slot:<2} | Dye Slot: {dye_slot:<2} | In Match: {in_match_str:<5}"
                
                # Line 5: Actions (Padded)
                mouse_delta_x = action.get('mouse_delta_x', 0.0)
                mouse_delta_y = action.get('mouse_delta_y', 0.0)
                line5 = f"ACTION:   Move: {move_str:<12} | Strafe: {strafe_str:<10} | Modifier: {mod_str:<14} | Combat: {combat_word:<10} | Mouse: ({mouse_delta_x:>+6.1f}, {mouse_delta_y:>+6.1f})"
                
                # Line 6: Reward Breakdown (Padded)
                reward_components = env.last_reward_components or {}
                dmg_dealt = reward_components.get('dmg_dealt', 0.0)
                dmg_taken = reward_components.get('dmg_taken', 0.0)
                spacing = reward_components.get('spacing', 0.0)
                miss_penalty = reward_components.get('miss_penalty', 0.0)
                wtap_bonus = reward_components.get('wtap_bonus', 0.0)
                line6 = f"REWARD:   Total: {reward:>+8.5f} | DmgDealt: {dmg_dealt:>+6.2f} | DmgTaken: {dmg_taken:>+6.2f} | Space: {spacing:>+6.2f} | MissPen: {miss_penalty:>+6.2f} | WTap: {wtap_bonus:>+6.2f}"
                
                # Line 7: Performance Stats (Padded)
                rate_val = self.pbar.format_dict['rate']
                rate_str = f"{rate_val:.1f} it/s" if rate_val is not None else "N/A"
                line7 = f"STATS:    Step Counter: {self.step_counter:>6} | Rate: {rate_str:<10}"
                
                # Print metrics below progress bar and restore cursor position back to progress bar line
                sys.stdout.write(f"\n\033[K{line1}\n\033[K{line2}\n\033[K{line3}\n\033[K{line4}\n\033[K{line5}\n\033[K{line6}\n\033[K{line7}\033[7A\r")
                sys.stdout.flush()
            except Exception:
                pass
        return True

    def _on_training_end(self):
        if self.pbar:
            self.pbar.close()
        print("\n\n\n")

# 1. Hardware Detection
device = torch.device("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
print(f"Using Hardware Interface: {device}")

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
        state = self.state_queue.get()
        if state is None:
            raise ConnectionDroppedException("Client disconnected")
        return state

    def reset_exchange(self):
        # Called by MinecraftPvPEnv.reset() inside the training thread
        # Block until client connects and sends the initial tick state
        tqdm.write("Gymnasium Environment resetting, waiting for client tick data...")
        state = self.state_queue.get()
        if state is None:
            raise ConnectionDroppedException("Client disconnected")
        return state

bridge = ThreadBridge()

# 3. Training Worker
def training_worker():
    print("Initializing PPO agent...")
    
    model = None
    
    while True:
        # Recreate env to reset websocket queues cleanly for each new connection session
        env = MinecraftPvPEnv(websocket_server_queue=bridge)
        
        if model is None:
            # Initialize PPO model (verbose=0 to let TqdmCallback handle custom telemetry)
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
                verbose=0,
                device=device
            )
        else:
            model.set_env(env)
            
        print("Awaiting connection from Minecraft on ws://localhost:8765...")
        bridge.client_connected.wait()
        
        print("Starting actual RL learning loop (total_timesteps=100000)...")
        try:
            model.learn(total_timesteps=100000, callback=TqdmCallback(100000), reset_num_timesteps=False)
            model.save("ppo_minecraft_pvp")
            print("Training completed! Saved model to 'ppo_minecraft_pvp.zip'")
            break
        except ConnectionDroppedException:
            print("Client disconnected. Saving model progress and awaiting reconnect...")
            model.save("ppo_minecraft_pvp")
        except KeyboardInterrupt:
            print("\nTraining interrupted by user (Ctrl+C). Saving model progress...")
            model.save("ppo_minecraft_pvp")
            print("Model saved successfully to 'ppo_minecraft_pvp.zip'. Exiting.")
            break
        except Exception as e:
            print(f"Training interrupted due to error: {e}")
            model.save("ppo_minecraft_pvp")
            break

# 4. WebSocket Event Loop Handler
async def tick_handler(websocket):
    print("Minecraft Client connected to Training Server!")
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
        print(f"WebSocket connection closed: {e}")
    finally:
        bridge.client_connected.clear()
        # Push None sentinel to state_queue to wake up and terminate training thread loop safely
        try:
            bridge.state_queue.put_nowait(None)
        except queue.Full:
            pass
        # Clean queues
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

def main():
    # Start the WebSocket server in a background daemon thread
    ws_thread = threading.Thread(target=run_websocket_server, daemon=True)
    ws_thread.start()
    
    # Run the training loop in the main thread so it captures Ctrl+C (KeyboardInterrupt)
    training_worker()

if __name__ == "__main__":
    main()
