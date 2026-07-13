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

        # Action Space:
        # action[0]: Forward/Backward -> Continuous mapped to [-1, 1]
        #           [-1.0 to -0.3] -> Backward (2)
        #           [-0.3 to 0.3]  -> Idle (0)
        #           [0.3 to 1.0]   -> Forward (1)
        # action[1]: Strafe -> Continuous mapped to [-1, 1]
        #           [-1.0 to -0.3] -> Right (2)
        #           [-0.3 to 0.3]  -> Idle (0)
        #           [0.3 to 1.0]   -> Left (1)
        # action[2]: Modifier -> Continuous mapped to [-1, 1]
        #           [-1.0 to -0.3] -> Sneak (1)
        #           [-0.3 to 0.3]  -> Normal (0)
        #           [0.3 to 1.0]   -> Jump (2)
        # action[3]: Combat Action -> Continuous mapped to [-1, 1]
        #           Mapped into 5 equal bins:
        #           [-1.0 to -0.6] -> Idle (0)
        #           [-0.6 to -0.2] -> Attack (1)
        #           [-0.2 to 0.2]  -> Block (2)
        #           [0.2 to 0.6]   -> Cast Rod (3)
        #           [0.6 to 1.0]   -> Reel Rod In (4)
        # action[4]: Mouse Delta X -> Continuous degree change per tick
        # action[5]: Mouse Delta Y -> Continuous degree change per tick
        self.action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(6,), dtype=np.float32
        )

        # Observation Space (17 features):
        # 1. Self HP (0.0 to 1.0)
        # 2-4. Self Velocity X, Y, Z
        # 5. Y-height above ground
        # 6. Active Item Index (0: Sword, 1: Rod)
        # 7. Opponent HP (0.0 to 1.0)
        # 8-10. Opponent Velocity X, Y, Z
        # 11-13. Opponent Relative Offset X, Y, Z
        # 14. Distance to target
        # 15-16. Angle Delta X (Yaw), Y (Pitch)
        # 17. Swing Cooldown/Animation active (0.0 to 1.0)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(17,), dtype=np.float32
        )

        # Communication queues for async WebSocket interaction
        self.ws_queue = websocket_server_queue
        self.current_state = None

    def _parse_observation(self, state):
        """Converts state dictionary from Java Mod into flattened float32 numpy array."""
        obs = np.zeros(17, dtype=np.float32)
        
        # Self stats
        obs[0] = float(state.get("hp", 1.0))
        obs[1] = float(state.get("vel_x", 0.0))
        obs[2] = float(state.get("vel_y", 0.0))
        obs[3] = float(state.get("vel_z", 0.0))
        obs[4] = float(state.get("y_ground", 0.0))
        obs[5] = float(state.get("active_item", 0.0)) # 0: Sword, 1: Rod
        
        # Opponent stats
        obs[6] = float(state.get("opp_hp", 1.0))
        obs[7] = float(state.get("opp_vel_x", 0.0))
        obs[8] = float(state.get("opp_vel_y", 0.0))
        obs[9] = float(state.get("opp_vel_z", 0.0))
        obs[10] = float(state.get("opp_rel_x", 0.0))
        obs[11] = float(state.get("opp_rel_y", 0.0))
        obs[12] = float(state.get("opp_rel_z", 0.0))
        obs[13] = float(state.get("target_dist", 999.0))
        
        # Crosshair / Cooldowns
        obs[14] = float(state.get("yaw_delta", 0.0))
        obs[15] = float(state.get("pitch_delta", 0.0))
        obs[16] = float(state.get("swing_cooldown", 0.0))
        
        return obs

    def _calculate_reward(self, prev_state, current_state):
        """
        Calculates rewards based on the transition between prev_state and current_state.
        Optimized for 1.8.9 PvP: spacing, hitting, avoiding damage, sprint resetting.
        """
        if prev_state is None:
            return 0.0

        reward = 0.0

        # Extract values
        hp = current_state.get("hp", 1.0)
        prev_hp = prev_state.get("hp", 1.0)
        opp_hp = current_state.get("opp_hp", 1.0)
        prev_opp_hp = prev_state.get("opp_hp", 1.0)
        target_dist = current_state.get("target_dist", 999.0)
        
        # 1. Dealing damage (large positive reward)
        if opp_hp < prev_opp_hp:
            damage_dealt_ratio = prev_opp_hp - opp_hp
            reward += damage_dealt_ratio * 20.0 * 1.0 # 1.0 reward for full heart dealt (2 HP)
            
            # Bonus for sprint-hitting (W-tapping)
            is_sprinting = current_state.get("is_sprinting", False)
            if is_sprinting:
                reward += 0.1

        # 2. Taking damage (large negative reward)
        if hp < prev_hp:
            damage_taken_ratio = prev_hp - hp
            reward -= damage_taken_ratio * 20.0 * 0.8

        # 3. Spacing reward (Maintaining 2.8 - 3.0 block reach)
        if 2.7 <= target_dist <= 3.1:
            reward += 0.05
        elif target_dist < 2.7:
            # Too close, vulnerable to trade hits
            reward -= 0.01

        # 4. Missed swing penalty
        swing_cooldown = current_state.get("swing_cooldown", 0.0)
        prev_swing_cooldown = prev_state.get("swing_cooldown", 0.0)
        # If swing has just started and opponent is too far, penalize blind spamming
        if swing_cooldown > 0.8 and prev_swing_cooldown <= 0.1:
            if target_dist > 4.5:
                reward -= 0.02

        # 5. Small survival bonus
        reward += 0.001

        return float(reward)

    def step(self, action):
        # Map continuous actions to the specific format expected by Java client
        
        # Forward/Backward
        fb_val = action[0]
        if fb_val < -0.3:
            forward_back = 2 # S (Backward)
        elif fb_val > 0.3:
            forward_back = 1 # W (Forward)
        else:
            forward_back = 0 # Idle
            
        # Strafe
        str_val = action[1]
        if str_val < -0.3:
            strafe = 2 # D (Right)
        elif str_val > 0.3:
            strafe = 1 # A (Left)
        else:
            strafe = 0 # Idle

        # Modifier
        mod_val = action[2]
        if mod_val < -0.3:
            modifier = 1 # Shift (Sneak)
        elif mod_val > 0.3:
            modifier = 2 # Space (Jump)
        else:
            modifier = 0 # Normal

        # Combat Action
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

        # Mouse Delta X, Y (scaling appropriately, e.g., max 15 degrees change per tick)
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
        
        # Check termination (e.g. if player or opponent dies)
        terminated = bool(self.current_state.get("hp", 1.0) <= 0.0 or self.current_state.get("opp_hp", 1.0) <= 0.0)
        truncated = False
        
        info = {}
        
        return obs, reward, terminated, truncated, info

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        if self.ws_queue is not None:
            # Wait for client to connect and send initial state
            self.current_state = self.ws_queue.reset_exchange()
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
