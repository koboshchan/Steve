import gymnasium as gym
from gymnasium import spaces
import numpy as np
import json
import asyncio

class MinecraftPvPEnv(gym.Env):
    """
    Custom Gymnasium Environment for Minecraft 1.8.9 PvP.
    This environment acts as a bridge, communicating with the Minecraft Java mod over WebSockets.
    """
    metadata = {"render_modes": ["human"]}

    def __init__(self, websocket_server_queue=None, env_idx=0, difficulty="easy", no_action_suggest=False):
        super(MinecraftPvPEnv, self).__init__()
        self.env_idx = env_idx
        self.difficulty = difficulty
        self.no_action_suggest = no_action_suggest

        # Action Space (5 discrete inputs, MultiDiscrete):
        # 0: Movement -> 9 bins (0: idle, 1: w, 2: wd, 3: wa, 4: s, 5: sa, 6: sd, 7: a, 8: d)
        # 1: Modifier -> 3 bins (0: Normal, 1: Sneak, 2: Jump)
        # 2: Combat Action -> 4 bins (0: Idle, 1: Attack, 2: Block, 3: Use Rod)
        # 3: Mouse Delta X -> 11 bins (0..10) -> (mouse_x_idx - 5) * 3.0 degrees
        # 4: Mouse Delta Y -> 9 bins (0..8) -> (mouse_y_idx - 4) * 2.5 degrees
        self.action_space = spaces.MultiDiscrete([9, 3, 4, 11, 9])

        # Observation Space (24 features):
        # 1. Self HP (0.0 to 1.0)
        # 2-4. Self Velocity X, Y, Z
        # 5. Squashed Height: min(y_ground / 4.0, 1.0)
        # 6-7. One-Hot Active Item (is_sword, is_rod)
        # 8. Opponent HP (0.0 to 1.0)
        # 9-11. Opponent Velocity X, Y, Z
        # 12-14. Opponent Relative Offset X, Y, Z
        # 15. Normalized Target Distance: min(target_dist / 30.0, 1.0)
        # 16-17. Normalized Self look angles: yaw_delta / 180.0, pitch_delta / 90.0
        # 18-19. Normalized Opponent look angles: opp_yaw_offset / 180.0, opp_pitch_offset / 90.0
        # 20. Swing Cooldown (0.0 to 1.0)
        # 21-24. Wall distances (front, right, back, left) normalized: min(dist / 50.0, 1.0)
        # 25-26. Absolute look angles: pitch / 90.0, yaw (normalized to [-1, 1])
        # 27-41. Action history (last 3 ticks, 5 actions per tick): normalized actions
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(41,), dtype=np.float32
        )

        # Communication queues for async WebSocket interaction
        self.ws_queue = websocket_server_queue
        self.current_state = None
        self.last_action_dict = {}
        self.last_reward = 0.0
        self.last_reward_components = {
            "dmg_dealt": 0.0, "wtap_bonus": 0.0, "dmg_taken": 0.0,
            "spacing": 0.0, "miss_penalty": 0.0, "survival": 0.0
        }

        # Action history tracker (3 ticks)
        self.action_history_len = 3
        self.action_history = [[0, 0, 0, 0, 0] for _ in range(self.action_history_len)]

    def _parse_observation(self, state):
        """Converts state dictionary from Java Mod into flattened float32 numpy array of shape (41,)."""
        obs = np.zeros(41, dtype=np.float32)
        
        # Self stats
        obs[0] = float(state.get("hp", 1.0))
        obs[1] = float(state.get("vel_x", 0.0))
        obs[2] = float(state.get("vel_y", 0.0))
        obs[3] = float(state.get("vel_z", 0.0))
        obs[4] = min(float(state.get("y_ground", 0.0)) / 4.0, 1.0)
        
        # One-hot active item
        active_item = int(state.get("active_item", 0))
        obs[5] = 1.0 if active_item == 0 else 0.0 # is_sword
        obs[6] = 1.0 if active_item == 1 else 0.0 # is_rod
        
        # Opponent stats
        obs[7] = float(state.get("opp_hp", 1.0))
        obs[8] = float(state.get("opp_vel_x", 0.0))
        obs[9] = float(state.get("opp_vel_y", 0.0))
        obs[10] = float(state.get("opp_vel_z", 0.0))
        obs[11] = float(state.get("opp_rel_x", 0.0))
        obs[12] = float(state.get("opp_rel_y", 0.0))
        obs[13] = float(state.get("opp_rel_z", 0.0))
        obs[14] = min(float(state.get("target_dist", 999.0)) / 30.0, 1.0)
        
        # Crosshair / Look deltas
        obs[15] = float(state.get("yaw_delta", 0.0)) / 180.0
        obs[16] = float(state.get("pitch_delta", 0.0)) / 90.0
        
        # Opponent Look offsets
        obs[17] = float(state.get("opp_yaw_offset", 0.0)) / 180.0
        obs[18] = float(state.get("opp_pitch_offset", 0.0)) / 90.0
        
        # Swing cooldown
        obs[19] = float(state.get("swing_cooldown", 0.0))
        
        # Wall distances (front, right, back, left)
        obs[20] = min(float(state.get("front_wall_dist", 50.0)) / 50.0, 1.0)
        obs[21] = min(float(state.get("right_wall_dist", 50.0)) / 50.0, 1.0)
        obs[22] = min(float(state.get("back_wall_dist", 50.0)) / 50.0, 1.0)
        obs[23] = min(float(state.get("left_wall_dist", 50.0)) / 50.0, 1.0)
        
        # Absolute rotation angles
        obs[24] = float(state.get("pitch", 0.0)) / 90.0
        obs[25] = (float(state.get("yaw", 0.0)) % 360.0) / 180.0 - 1.0
        
        # Append action history (15 features: 3 ticks * 5 action variables)
        # Normalize actions:
        # act[0] (0..8) / 8.0
        # act[1] (0..2) / 2.0
        # act[2] (0..3) / 3.0
        # act[3] (0..10) / 10.0
        # act[4] (0..8) / 8.0
        idx = 26
        for act in self.action_history:
            obs[idx]     = float(act[0]) / 8.0
            obs[idx + 1] = float(act[1]) / 2.0
            obs[idx + 2] = float(act[2]) / 3.0
            obs[idx + 3] = float(act[3]) / 10.0
            obs[idx + 4] = float(act[4]) / 8.0
            idx += 5
            
        return obs

    def _calculate_reward(self, prev_state, current_state, action_dict):
        """
        Dense reward function for 1.8.9 PvP.

        Every tick the agent receives:
          - Aim reward   : continuous signal for keeping crosshair on target
          - Distance reward : Gaussian peaked at optimal reach (~3 blocks)

        On damage events:
          - Damage dealt / taken : strong +/- signal

        On terminal events:
          - Kill bonus / Death penalty
        """
        if prev_state is None:
            return 0.0

        components = {
            "aim":                     0.0,
            "distance":                0.0,
            "distance_far_penalty":    0.0,
            "wall_proximity_penalty":  0.0,
            "wall_corner_penalty":     0.0,
            "look_pitch_penalty":      0.0,
            "facing_away_penalty":     0.0,
            "dmg_dealt":               0.0,
            "dmg_taken":               0.0,
            "kill":                    0.0,
            "death":                   0.0,
        }

        hp      = current_state.get("hp",      1.0)
        prev_hp = prev_state.get("hp",         1.0)
        opp_hp      = current_state.get("opp_hp",  1.0)
        prev_opp_hp = prev_state.get("opp_hp",     1.0)
        target_dist = current_state.get("target_dist", 999.0)

        # 1. Aim reward/penalty — dense every tick
        # Aiming directly on (0 deg error) -> +0.15 reward
        # 100 degrees away -> 0.0 reward
        # Further than 100 degrees -> punish up to -0.2 (at 180 degrees away)
        yaw_delta   = current_state.get("yaw_delta",   0.0)
        pitch_delta = current_state.get("pitch_delta", 0.0)
        aim_error = np.sqrt(yaw_delta ** 2 + pitch_delta ** 2)
        
        if aim_error <= 100.0:
            # Linear decay from +0.15 (at 0 deg) to 0.0 (at 100 deg)
            components["aim"] = 0.15 * (1.0 - aim_error / 100.0)
        else:
            # Linear penalty scaling from 0.0 (at 100 deg) to -0.2 (at 180 deg)
            components["aim"] = -0.2 * ((aim_error - 100.0) / 80.0)

        if not self.no_action_suggest:
            # 2. Distance shaping — dense every tick
            # Gaussian peaked at OPTIMAL_DIST blocks; zero beyond DIST_CUTOFF.
            OPTIMAL_DIST = 3.0
            DIST_SIGMA   = 1.5
            DIST_CUTOFF  = 20.0
            if target_dist < DIST_CUTOFF:
                components["distance"] = 0.03 * np.exp(
                    -0.5 * ((target_dist - OPTIMAL_DIST) / DIST_SIGMA) ** 2
                )

            # 3. Look extreme pitch penalty (looking too close to sky or ground)
            # Minecraft pitch ranges from -90.0 (up) to 90.0 (down).
            # Punish if looking within 25 degrees of either limit (i.e. abs(pitch) >= 65.0)
            pitch = current_state.get("pitch", 0.0)
            if abs(pitch) >= 65.0:
                components["look_pitch_penalty"] = -0.05

            # 4. Facing away penalty
            # Punish if the agent is looking more than 150 degrees away from the opponent
            if aim_error > 150.0:
                components["facing_away_penalty"] = -0.05

        # No matter what, punish when more than 10 blocks away
        if target_dist > 10.0:
            components["distance_far_penalty"] = -0.075

        # Wall / Corner proximity penalties (no matter what)
        front_wall_dist = float(current_state.get("front_wall_dist", 50.0))
        right_wall_dist = float(current_state.get("right_wall_dist", 50.0))
        back_wall_dist  = float(current_state.get("back_wall_dist", 50.0))
        left_wall_dist  = float(current_state.get("left_wall_dist", 50.0))

        near_wall = (
            front_wall_dist <= 1.0 or
            right_wall_dist <= 1.0 or
            back_wall_dist  <= 1.0 or
            left_wall_dist  <= 1.0
        )
        near_corner = (
            (front_wall_dist <= 1.0 and right_wall_dist <= 1.0) or
            (right_wall_dist <= 1.0 and back_wall_dist  <= 1.0) or
            (back_wall_dist  <= 1.0 and left_wall_dist  <= 1.0) or
            (left_wall_dist  <= 1.0 and front_wall_dist <= 1.0)
        )

        if near_corner:
            components["wall_corner_penalty"] = -0.25  # Extra heavy penalty for corners
        elif near_wall:
            components["wall_proximity_penalty"] = -0.05  # Standard penalty for walls

        # 5. Damage dealt
        if opp_hp < prev_opp_hp:
            dmg = prev_opp_hp - opp_hp          # fraction of HP bar lost
            components["dmg_dealt"] = dmg * 100.0  # ~+5.0 per half-heart (10.0 per full heart)

            # Kill bonus
            if opp_hp <= 0.0:
                components["kill"] = 50.0

        # 6. Damage taken
        if hp < prev_hp:
            dmg = prev_hp - hp
            components["dmg_taken"] = -dmg * 80.0   # ~-4.0 per half-heart

            # Death penalty
            if hp <= 0.0:
                components["death"] = -50.0

        reward = sum(components.values())
        self.last_reward_components = components
        return float(reward)

    def step(self, action):
        # action is a list/array of 5 discrete indexes (MultiDiscrete)
        # 0: Movement (0..8)
        # 1: Modifier (0..2)
        # 2: Combat Action (0..3)
        # 3: Mouse Delta X (0..10)
        # 4: Mouse Delta Y (0..8)
        
        # --- Lobby / Missing Opponent pass-through ---
        # If the previous state shows we are not in a match yet, OR the opponent is missing
        # from the match, send an idle action and wait for the next tick.
        # This keeps the client ticking and pauses training for this client without
        # blocking the parallel thread execution of other environments.
        not_in_match = not self.current_state.get("in_match", True)
        opp_missing = self.current_state.get("in_match", True) and not self.current_state.get("opp_found", True)
        
        if self.ws_queue is not None and (not_in_match or opp_missing):
            idle_action = {
                "forward_back": 0, "strafe": 0, "modifier": 0, "combat_action": 0,
                "mouse_delta_x": 0.0, "mouse_delta_y": 0.0,
                "difficulty": self.difficulty,
                "is_training": True
            }
            new_state = self.ws_queue.step_exchange(idle_action)
            self.current_state = new_state
            obs = self._parse_observation(self.current_state)
            return obs, 0.0, False, False, {"in_lobby": True}
        
        move_idx = int(action[0])
        modifier = int(action[1])
        combat_action = int(action[2])
        mouse_x_idx = int(action[3])
        mouse_y_idx = int(action[4])
        
        # Update action history buffer
        self.action_history.append([move_idx, modifier, combat_action, mouse_x_idx, mouse_y_idx])
        if len(self.action_history) > self.action_history_len:
            self.action_history.pop(0)
  
        # 1. Movement: 9 options mapped from action[0]
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
  
        # 2. Modifier is directly mapped (0: Normal, 1: Sneak, 2: Jump)
        
        # 3. Combat Action is directly mapped (0: Idle, 1: Attack, 2: Block, 3: Use Rod)

        # 4. Mouse Delta X, Y (0..10 mapped to -15.0..15.0 and 0..8 mapped to -10.0..10.0)
        mouse_delta_x = float((mouse_x_idx - 5) * 3.0)
        mouse_delta_y = float((mouse_y_idx - 4) * 2.5)

        response = {
            "forward_back": forward_back,
            "strafe": strafe,
            "modifier": modifier,
            "combat_action": combat_action,
            "mouse_delta_x": mouse_delta_x,
            "mouse_delta_y": mouse_delta_y,
            "difficulty": self.difficulty,
            "is_training": True
        }

        # Send action to client and wait for next tick's observation
        # In a real environment, we would use the self.ws_queue to communicate
        # with the server.py event loop.
        
        # For mock/integration test purposes or training:
        if self.ws_queue is not None:
            # Send response packet and get new tick state
            new_state = self.ws_queue.step_exchange(response)
        else:
            # Fallback mock state if not running live
            new_state = {
                "hp": 1.0, "vel_x": 0.0, "vel_y": 0.0, "vel_z": 0.0,
                "y_ground": 0.0, "active_item": 0.0, "opp_hp": 1.0,
                "opp_vel_x": 0.0, "opp_vel_y": 0.0, "opp_vel_z": 0.0,
                "opp_rel_x": 0.0, "opp_rel_y": 0.0, "opp_rel_z": 3.0,
                "target_dist": 3.0, "yaw_delta": 0.0, "pitch_delta": 0.0,
                "swing_cooldown": 0.0, "is_sprinting": True
            }

        prev_state = self.current_state
        self.current_state = new_state
        
        obs = self._parse_observation(self.current_state)
        reward = self._calculate_reward(prev_state, self.current_state, response)
        
        self.last_action_dict = response
        self.last_reward = reward
        
        # Check termination (player died)
        # Note: in_match=False is NOT a termination here — the lobby pass-through
        # at the top of the next step() call will handle it without resetting.
        terminated = bool(self.current_state.get("hp", 1.0) <= 0.0)
        truncated = False
        
        if terminated and self.ws_queue is not None:
            # Unblock the websocket event loop since we won't call step() again for this episode
            idle_action = {
                "forward_back": 0, "strafe": 0, "modifier": 0, "combat_action": 0,
                "mouse_delta_x": 0.0, "mouse_delta_y": 0.0,
                "is_training": True
            }
            # Clear any stale actions to prevent blocking
            import queue
            while not self.ws_queue.action_queue.empty():
                try:
                    self.ws_queue.action_queue.get_nowait()
                except queue.Empty:
                    break
            try:
                self.ws_queue.action_queue.put_nowait(idle_action)
            except queue.Full:
                pass
            
        info = {}
        
        return obs, reward, terminated, truncated, info

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        # Reset action history
        self.action_history = [[0, 0, 0, 0, 0] for _ in range(self.action_history_len)]
        
        if self.ws_queue is not None:
            # Grab the next state from the client and return immediately.
            # If the client is still in the lobby (in_match=False), the lobby
            # pass-through at the top of step() will handle it tick-by-tick
            # without blocking other parallel environments.
            state = self.ws_queue.reset_exchange(self.env_idx)
            self.current_state = state
        else:
            self.current_state = {
                "hp": 1.0, "vel_x": 0.0, "vel_y": 0.0, "vel_z": 0.0,
                "y_ground": 0.0, "active_item": 0.0, "opp_hp": 1.0,
                "opp_vel_x": 0.0, "opp_vel_y": 0.0, "opp_vel_z": 0.0,
                "opp_rel_x": 0.0, "opp_rel_y": 0.0, "opp_rel_z": 3.0,
                "target_dist": 3.0, "yaw_delta": 0.0, "pitch_delta": 0.0,
                "swing_cooldown": 0.0, "is_sprinting": True
            }
            
        obs = self._parse_observation(self.current_state)
        info = {}
        return obs, info
