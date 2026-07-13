import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import argparse
import asyncio
import concurrent.futures
import json
import numpy as np
import torch
import queue
import threading
import sys
import time
from websockets.server import serve
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack
from copy import deepcopy
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
        # Signals that this client has reported in_match=True at least once
        self.in_match_event = threading.Event()

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

    def _on_training_start(self):
        # Create progress bar using sys.stdout to prevent overlap issues with other stdout prints
        self.pbar = tqdm(total=self.total_timesteps, desc="Training PPO Agent", file=sys.stdout, dynamic_ncols=True)

    def _on_step(self) -> bool:
        # Only count steps from envs that are actually in a match.
        # Lobby pass-through steps set {"in_lobby": True} in their info dict.
        infos = self.locals.get("infos", [{}] * self.training_env.num_envs)
        in_game_count = sum(1 for info in infos if not info.get("in_lobby", False))
        if in_game_count > 0:
            self.pbar.update(in_game_count)
        
        # Update metrics every tick (50 ms)
        if True:
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
                    dmg_dealt  = reward_components.get('dmg_dealt',  0.0)
                    dmg_taken  = reward_components.get('dmg_taken',  0.0)
                    aim        = reward_components.get('aim',        0.0)
                    dist       = reward_components.get('distance',   0.0)
                    pitch_pen  = reward_components.get('look_pitch_penalty', 0.0)
                    away_pen   = reward_components.get('facing_away_penalty', 0.0)
                    kill       = reward_components.get('kill',       0.0)
                    death      = reward_components.get('death',      0.0)
                    l3 = f"C{idx} COMB: Move: {move_str:<12} | Combat: {combat_word:<8} | Mouse: ({mouse_delta_x:>+5.1f}, {mouse_delta_y:>+5.1f}) | LookOff: (Yaw: {opp_yaw_offset:>+6.1f}, Pitch: {opp_pitch_offset:>+6.1f}) | Reward: {reward:>+6.3f} (Aim: {aim:>+5.3f} | Dist: {dist:>+5.3f} | PitchPen: {pitch_pen:>+5.2f} | AwayPen: {away_pen:>+5.2f} | Dmg: {dmg_dealt:>+4.1f}/{dmg_taken:>+4.1f} | Kill: {kill:>+4.1f} | Death: {death:>+4.1f})"
                    
                    front_dist = state.get("front_wall_dist", 50.0)
                    right_dist = state.get("right_wall_dist", 50.0)
                    back_dist = state.get("back_wall_dist", 50.0)
                    left_dist = state.get("left_wall_dist", 50.0)
                    l4 = f"C{idx} MAP:  Front: {front_dist:>5.1f}m | Back: {back_dist:>5.1f}m | Left: {left_dist:>5.1f}m | Right: {right_dist:>5.1f}m | GroundDist: {y_ground:>5.2f}m"
                    
                    lines.extend([l1, l2, l3, l4])
                
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
        print("\n" * (num_envs * 4 + 2))

# 1. Hardware Detection
device = torch.device("cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
print(f"Using Hardware Interface: {device}")

# Parallel vectorized environment: each sub-env steps in its own thread so
# a client that is in the lobby (blocking reset) never stalls the other clients.
class ThreadedVecEnv(DummyVecEnv):
    """
    Drop-in replacement for DummyVecEnv that steps every sub-environment in a
    dedicated thread.  All of DummyVecEnv's buffer / observation machinery is
    reused; only step_wait() and reset() are overridden to run concurrently.

    Result: with N clients both in-game the throughput is N×20 it/s instead of
    the 20 it/s cap that DummyVecEnv's sequential stepping imposes.
    """
    def __init__(self, env_fns):
        super().__init__(env_fns)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(env_fns))

    # step_async just stores the actions (same as DummyVecEnv)
    def step_async(self, actions):
        self.actions = actions

    def step_wait(self):
        """Run each env's step (+ auto-reset on done) in parallel threads."""
        def _step_one(env_idx):
            obs, rew, terminated, truncated, info = self.envs[env_idx].step(self.actions[env_idx])
            done = terminated or truncated
            if truncated and not terminated:
                info["TimeLimit.truncated"] = True
            if done:
                # Store terminal obs so SB3 can bootstrap the value estimate
                info["terminal_observation"] = obs
                # reset() is now non-blocking, so this never freezes other threads
                reset_obs, reset_info = self.envs[env_idx].reset()
                obs = reset_obs
                try:
                    self.reset_infos[env_idx] = reset_info
                except AttributeError:
                    pass  # older SB3 versions don't have reset_infos
            return env_idx, obs, rew, done, info

        futures = [self._executor.submit(_step_one, i) for i in range(self.num_envs)]
        for f in concurrent.futures.as_completed(futures):
            env_idx, obs, rew, done, info = f.result()
            self.buf_rews[env_idx] = rew
            self.buf_dones[env_idx] = done
            self.buf_infos[env_idx] = info
            self._save_obs(env_idx, obs)

        return (
            self._obs_from_buf(),
            np.copy(self.buf_rews),
            np.copy(self.buf_dones),
            deepcopy(self.buf_infos),
        )

    def reset(self):
        """Reset all envs in parallel threads."""
        def _reset_one(env_idx):
            obs, info = self.envs[env_idx].reset()
            return env_idx, obs, info

        futures = [self._executor.submit(_reset_one, i) for i in range(self.num_envs)]
        for f in concurrent.futures.as_completed(futures):
            env_idx, obs, info = f.result()
            self._save_obs(env_idx, obs)
            try:
                self.reset_infos[env_idx] = info
            except AttributeError:
                pass

        return self._obs_from_buf()

    def close(self):
        self._executor.shutdown(wait=False)
        super().close()

# 2. WebSocket Event Loop Handler
async def tick_handler(websocket):
    global connected_sockets, num_envs, training_started, bridges
    
    with connection_lock:
        if not training_started:
            connected_sockets.append(websocket)
            print("Minecraft Client connected! (Waiting for training initialization...)")
        else:
            env_idx = None
            for idx in range(num_envs):
                if not bridges[idx].client_connected.is_set():
                    env_idx = idx
                    break
            if env_idx is None:
                print("Connection refused: All training slots are currently active.")
                return
            print(f"Minecraft Client {env_idx} reconnected to Training Server!")
    
    try:
        if not training_started:
            # Await countdown phase completion
            while not training_started:
                await asyncio.sleep(0.1)
            
            with connection_lock:
                if websocket in connected_sockets:
                    env_idx = connected_sockets.index(websocket)
                else:
                    print("Connection lost before training started.")
                    return
        
        # env_idx is now guaranteed to be a valid and correct index inside bridges list
        bridge = bridges[env_idx]
        bridge.client_connected.set()
        
        async for message in websocket:
            # A. Receive state packet from Forge client
            state = json.loads(message)
            
            # B. Update this bridge's in_match event independently of the training thread
            if state.get("in_match", False):
                bridge.in_match_event.set()
            else:
                bridge.in_match_event.clear()
            
            # C. Forward state to corresponding Gym environment bridge queue
            bridge.state_queue.put(state)
            
            # D. Wait for corresponding environment to step and push the action
            loop = asyncio.get_running_loop()
            action = await loop.run_in_executor(None, bridge.action_queue.get)
            
            # E. Send response actions back to client
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
def training_worker(total_steps, resume=False):
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
    
    # Wait for ALL clients to independently report in_match=True before creating envs.
    # This runs concurrently so each client's lobby wait does not block the others.
    # Without this, DummyVecEnv would reset envs sequentially, causing env 0's
    # in-match wait to block env 1, env 2, etc. from starting their own check.
    print("Waiting for all clients to enter a match (concurrent per-client check)...")
    idle_action = {
        "forward_back": 0, "strafe": 0, "modifier": 0,
        "combat_action": 0, "mouse_delta_x": 0.0, "mouse_delta_y": 0.0
    }

    def wait_for_in_match(bridge_idx):
        """Spin-loop for one bridge: drain ticks until in_match=True, then stop.
        Each call runs in its own thread so all bridges wait in parallel."""
        bridge = bridges[bridge_idx]
        while True:
            state = bridge.state_queue.get()      # blocks until client sends a tick
            if state is None:
                raise ConnectionDroppedException(f"Client {bridge_idx} disconnected before match start")
            if state.get("in_match", False):
                # Put the in-match state back so reset_exchange() can consume it
                bridge.state_queue.put(state)
                tqdm.write(f"Client {bridge_idx} is in a match — ready for training.")
                return
            # Not yet in game: ack the tick with an idle action so the client keeps ticking
            bridge.action_queue.put(idle_action)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_envs) as pool:
        futures = {pool.submit(wait_for_in_match, i): i for i in range(num_envs)}
        for future in concurrent.futures.as_completed(futures):
            future.result()   # re-raise any ConnectionDroppedException

    def make_env(env_idx):
        return lambda: MinecraftPvPEnv(websocket_server_queue=bridges[env_idx], env_idx=env_idx)
        
    envs = ThreadedVecEnv([make_env(i) for i in range(num_envs)])
    envs = VecFrameStack(envs, n_stack=4)
    
    model_path = "ppo_minecraft_pvp"
    
    if resume and os.path.exists(model_path + ".zip"):
        print(f"Resuming training: Loading existing model weights from '{model_path}.zip'...")
        model = PPO.load(model_path, env=envs, device=device)
    else:
        if resume:
            print(f"WARNING: '--resume' was set, but no existing model checkpoint '{model_path}.zip' was found.")
            print("Starting a brand-new model from scratch.")
        else:
            print("Starting a brand-new model from scratch.")
            
        policy_kwargs = dict(
            net_arch=dict(pi=[256, 256], vf=[256, 256])
        )
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
            device=device,
            policy_kwargs=policy_kwargs
        )
    
    print(f"Starting actual RL learning loop (total_timesteps={total_steps}) for {num_envs} environments...")
    try:
        model.learn(total_timesteps=total_steps, callback=TqdmCallback(total_steps), reset_num_timesteps=False)
        model.save(model_path)
        print(f"Training completed! Saved model to '{model_path}.zip'")
        os._exit(0)
    except ConnectionDroppedException:
        print("One or more clients disconnected. Saving model progress...")
        model.save(model_path)
        os._exit(0)
    except KeyboardInterrupt:
        print("\nTraining interrupted by user (Ctrl+C). Saving model progress...")
        model.save(model_path)
        print(f"Model saved successfully to '{model_path}.zip'. Exiting.")
        os._exit(0)
    except Exception as e:
        print(f"Training interrupted due to error: {e}")
        model.save(model_path)
        os._exit(1)

def main():
    parser = argparse.ArgumentParser(description="Train the Steve Minecraft PvP PPO agent.")
    parser.add_argument(
        "--steps",
        type=int,
        default=100_000,
        help="Total number of environment steps to train for (default: 100000)."
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume training from the existing model checkpoint ('ppo_minecraft_pvp.zip') if it exists."
    )
    args = parser.parse_args()

    # Start the WebSocket server in a background daemon thread
    ws_thread = threading.Thread(target=run_websocket_server, daemon=True)
    ws_thread.start()

    # Run the training loop in the main thread so it captures Ctrl+C (KeyboardInterrupt)
    training_worker(total_steps=args.steps, resume=args.resume)

if __name__ == "__main__":
    main()
