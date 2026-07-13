import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import asyncio
import json
import sys
import torch
import numpy as np
import gymnasium as gym
from websockets.server import serve
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack
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
raw_env = MinecraftPvPEnv()
dummy_env = DummyVecEnv([lambda: raw_env])
dummy_env = VecFrameStack(dummy_env, n_stack=4)
model_path = "ppo_minecraft_pvp"

if os.path.exists(model_path + ".zip"):
    print(f"Loading trained weights from '{model_path}.zip'...")
    model = PPO.load(model_path, env=dummy_env, device=device)
else:
    print("WARNING: No trained model ('ppo_minecraft_pvp.zip') was found.")
    print("Initializing a brand-new model with RANDOM weights.")
    print("To train the model, run: python train.py")
    policy_kwargs = dict(
        net_arch=dict(pi=[256, 256], vf=[256, 256])
    )
    model = PPO("MlpPolicy", dummy_env, verbose=1, device=device, policy_kwargs=policy_kwargs)

class WebSocketCoordinator:
    """Coordinates between the async WebSocket loop and gym environment step calls."""
    def __init__(self):
        self.websocket = None
        self.latest_state = None
        self.prev_state = None
        self.state_received = asyncio.Event()
        self.obs_history = []
        self.n_stack = 4

    async def handle_client(self, websocket):
        self.websocket = websocket
        self.state_received.clear()
        self.prev_state = None
        self.obs_history = []
        # Reset action history on raw_env for a fresh client session
        raw_env.action_history = [[0, 0, 0, 0, 0] for _ in range(raw_env.action_history_len)]
        print("Minecraft Client Successfully Connected!")
        
        try:
            async for message in websocket:
                # 1. Parse client state JSON
                state = json.loads(message)
                self.latest_state = state
                self.state_received.set()
                
                # 2. Extract features for model inference
                obs = raw_env._parse_observation(state)
                
                # Stack observations to match training frame stacking
                if not self.obs_history:
                    # Initial tick: repeat the first observation vector 4 times
                    self.obs_history = [obs] * self.n_stack
                else:
                    self.obs_history.append(obs)
                    self.obs_history.pop(0)
                stacked_obs = np.concatenate(self.obs_history)
                
                # 3. Model Predict (forward pass using stacked observations)
                action, _states = model.predict(stacked_obs, deterministic=True)
                
                # 4. Convert model action space outputs to WebSocket response commands
                move_idx = int(action[0])
                modifier = int(action[1])
                combat_action = int(action[2])
                mouse_x_idx = int(action[3])
                mouse_y_idx = int(action[4])

                # Update raw_env's action history for next tick's parse_observation
                raw_env.action_history.append([move_idx, modifier, combat_action, mouse_x_idx, mouse_y_idx])
                if len(raw_env.action_history) > raw_env.action_history_len:
                    raw_env.action_history.pop(0)

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
                
                # Calculate reward metrics
                reward = 0.0
                reward_components = {}
                if self.prev_state is not None:
                    reward = raw_env._calculate_reward(self.prev_state, state, response)
                    reward_components = raw_env.last_reward_components
                self.prev_state = state

                # Print telemetry info (dynamically updating in terminal)
                # Format active item
                active_item_map = {0: "Sword", 1: "Fishing Rod"}
                active_word = active_item_map.get(state.get("active_item", 0), "Sword")

                # Format moving inputs
                move_map = {0: "Idle", 1: "W (Forward)", 2: "S (Backward)"}
                strafe_map = {0: "Idle", 1: "A (Left)", 2: "D (Right)"}
                combat_action_map = {0: "Idle", 1: "Attack", 2: "Block", 3: "Cast Rod", 4: "Reel Rod"}

                move_str = move_map.get(forward_back, "Idle")
                strafe_str = strafe_map.get(strafe, "Idle")
                combat_word = combat_action_map.get(combat_action, "Idle")

                # Line 1: Self Stats (Padded)
                hp_val = state.get('hp', 1.0) * 10.0
                vel_x = state.get('vel_x', 0.0)
                vel_y = state.get('vel_y', 0.0)
                vel_z = state.get('vel_z', 0.0)
                sprint_str = str(state.get('is_sprinting', False))
                y_ground = float(state.get('y_ground', 0.0))
                l1 = f"SELF: HP: {hp_val:>4.1f}/10.0 | Vel: ({vel_x:>+6.2f}, {vel_y:>+6.2f}, {vel_z:>+6.2f}) | Sprint: {sprint_str:<5} | GroundDist: {y_ground:>5.2f}m"

                # Line 2: Opponent Stats (Padded)
                opp_hp_val = state.get('opp_hp', 1.0) * 10.0
                target_dist = state.get('target_dist', 999.0)
                opp_rel_x = state.get('opp_rel_x', 0.0)
                opp_rel_y = state.get('opp_rel_y', 0.0)
                opp_rel_z = state.get('opp_rel_z', 0.0)
                l2 = f"OPP:  HP: {opp_hp_val:>4.1f}/10.0 | Dist: {target_dist:>6.2f}m | RelPos: ({opp_rel_x:>+6.1f}, {opp_rel_y:>+6.1f}, {opp_rel_z:>+6.1f})"

                # Line 3: Actions & Reward breakdown (Padded)
                opp_yaw_offset = state.get('opp_yaw_offset', 0.0)
                opp_pitch_offset = state.get('opp_pitch_offset', 0.0)
                dmg_dealt  = reward_components.get('dmg_dealt',  0.0)
                dmg_taken  = reward_components.get('dmg_taken',  0.0)
                aim        = reward_components.get('aim',        0.0)
                pitch_pen  = reward_components.get('look_pitch_penalty', 0.0)
                away_pen   = reward_components.get('facing_away_penalty', 0.0)
                kill       = reward_components.get('kill',       0.0)
                death      = reward_components.get('death',      0.0)
                l3 = f"COMB: Move: {move_str:<12} | Combat: {combat_word:<8} | Mouse: ({mouse_delta_x:>+5.1f}, {mouse_delta_y:>+5.1f}) | LookOff: (Yaw: {opp_yaw_offset:>+6.1f}, Pitch: {opp_pitch_offset:>+6.1f})"
                l4 = f"REWD: Reward: {reward:>+6.3f} (Aim: {aim:>+5.3f} | PitchPen: {pitch_pen:>+5.2f} | AwayPen: {away_pen:>+5.2f} | Dmg: {dmg_dealt:>+4.1f}/{dmg_taken:>+4.1f} | Kill: {kill:>+4.1f} | Death: {death:>+4.1f})"

                # Line 5: Map info
                front_dist = state.get("front_wall_dist", 50.0)
                right_dist = state.get("right_wall_dist", 50.0)
                back_dist = state.get("back_wall_dist", 50.0)
                left_dist = state.get("left_wall_dist", 50.0)
                l5 = f"MAP:  Front: {front_dist:>5.1f}m | Back: {back_dist:>5.1f}m | Left: {left_dist:>5.1f}m | Right: {right_dist:>5.1f}m | GroundDist: {y_ground:>5.2f}m"

                lines = [l1, l2, l3, l4, l5]
                output_str = "".join([f"\n\033[K{line}" for line in lines])
                num_lines = len(lines)
                sys.stdout.write(f"{output_str}\033[{num_lines}A\r")
                sys.stdout.flush()

                # 5. Send actions back to Forge Client
                await websocket.send(json.dumps(response))
                
        except Exception as e:
            print(f"Connection Dropped or Error: {e}")
        finally:
            self.websocket = None
            self.prev_state = None
            self.obs_history = []

coordinator = WebSocketCoordinator()

async def main():
    print("Awaiting connection from Minecraft on ws://localhost:8765...")
    async with serve(coordinator.handle_client, "localhost", 8765, ping_interval=None, ping_timeout=None):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
