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

    def __init__(self, websocket_server_queue=None):
        super(MinecraftPvPEnv, self).__init__()

        # Action Space (5 discrete inputs, MultiDiscrete):
        # 0: Movement -> 9 bins (0: idle, 1: w, 2: wd, 3: wa, 4: s, 5: sa, 6: sd, 7: a, 8: d)
        # 1: Modifier -> 3 bins (0: Normal, 1: Sneak, 2: Jump)
        # 2: Combat Action -> 5 bins (0: Idle, 1: Attack, 2: Block, 3: Cast Rod, 4: Reel Rod)
        # 3: Mouse Delta X -> 11 bins (0..10) -> (mouse_x_idx - 5) * 3.0 degrees
        # 4: Mouse Delta Y -> 9 bins (0..8) -> (mouse_y_idx - 4) * 2.5 degrees
        self.action_space = spaces.MultiDiscrete([9, 3, 5, 11, 9])

        # Observation Space (20 features):
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
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(20,), dtype=np.float32
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

    def _parse_observation(self, state):
        """Converts state dictionary from Java Mod into flattened float32 numpy array of shape (20,)."""
        obs = np.zeros(20, dtype=np.float32)
        
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
        
        return obs

    def _calculate_reward(self, prev_state, current_state):
        """
        Calculates rewards based on the transition between prev_state and current_state.
        Optimized for 1.8.9 PvP: spacing, hitting, avoiding damage, sprint resetting.
        """
        if prev_state is None:
            return 0.0

        components = {
            "dmg_dealt": 0.0,
            "wtap_bonus": 0.0,
            "dmg_taken": 0.0,
            "spacing": 0.0,
            "miss_penalty": 0.0,
            "survival": 0.0
        }

        # Extract values
        hp = current_state.get("hp", 1.0)
        prev_hp = prev_state.get("hp", 1.0)
        opp_hp = current_state.get("opp_hp", 1.0)
        prev_opp_hp = prev_state.get("opp_hp", 1.0)
        target_dist = current_state.get("target_dist", 999.0)
        
        # 1. Dealing damage (large positive reward)
        if opp_hp < prev_opp_hp:
            damage_dealt_ratio = prev_opp_hp - opp_hp
            components["dmg_dealt"] = damage_dealt_ratio * 20.0 * 1.0 # 1.0 reward for full heart dealt (2 HP)
            
            # Bonus for sprint-hitting (W-tapping)
            is_sprinting = current_state.get("is_sprinting", False)
            if is_sprinting:
                components["wtap_bonus"] = 0.1

        # 2. Taking damage (large negative reward)
        if hp < prev_hp:
            damage_taken_ratio = prev_hp - hp
            components["dmg_taken"] = -damage_taken_ratio * 20.0 * 0.8

        # 3. Spacing reward (Maintaining 2.8 - 3.0 block reach)
        if 2.7 <= target_dist <= 3.1:
            components["spacing"] = 0.05
        elif target_dist < 2.7:
            # Too close, vulnerable to trade hits
            components["spacing"] = -0.01

        # 4. Missed swing penalty
        swing_cooldown = current_state.get("swing_cooldown", 0.0)
        prev_swing_cooldown = prev_state.get("swing_cooldown", 0.0)
        # If swing has just started and opponent is too far, penalize blind spamming
        if swing_cooldown > 0.8 and prev_swing_cooldown <= 0.1:
            if target_dist > 4.5:
                components["miss_penalty"] = -0.02

        reward = sum(components.values())
        self.last_reward_components = components
        return float(reward)

    def step(self, action):
        # action is a list/array of 5 discrete indexes (MultiDiscrete)
        # 0: Movement (0..8)
        # 1: Modifier (0..2)
        # 2: Combat Action (0..4)
        # 3: Mouse Delta X (0..10)
        # 4: Mouse Delta Y (0..8)
        move_idx = int(action[0])
        modifier = int(action[1])
        combat_action = int(action[2])
        mouse_x_idx = int(action[3])
        mouse_y_idx = int(action[4])
        
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
        
        # 3. Combat Action is directly mapped (0: Idle, 1: Attack, 2: Block, 3: Cast Rod, 4: Reel Rod)

        # 4. Mouse Delta X, Y (0..10 mapped to -15.0..15.0 and 0..8 mapped to -10.0..10.0)
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
        reward = self._calculate_reward(prev_state, self.current_state)
        
        self.last_action_dict = response
        self.last_reward = reward
        
        # Check termination (e.g. if player dies or the match ends)
        terminated = bool(self.current_state.get("hp", 1.0) <= 0.0 or not self.current_state.get("in_match", True))
        truncated = False
        
        if terminated and self.ws_queue is not None:
            # Unblock the websocket event loop since we won't call step() again for this episode
            idle_action = {
                "forward_back": 0, "strafe": 0, "modifier": 0, "combat_action": 0,
                "mouse_delta_x": 0.0, "mouse_delta_y": 0.0
            }
            self.ws_queue.action_queue.put(idle_action)
            
        info = {}
        
        return obs, reward, terminated, truncated, info

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        if self.ws_queue is not None:
            # Wait for client to connect and send initial state
            state = self.ws_queue.reset_exchange()
            # If we are in the lobby (lime dye is present), wait for the click and match start
            idle_action = {
                "forward_back": 0,
                "strafe": 0,
                "modifier": 0,
                "combat_action": 0,
                "mouse_delta_x": 0.0,
                "mouse_delta_y": 0.0
            }
            while not state.get("in_match", False):
                state = self.ws_queue.step_exchange(idle_action)
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
