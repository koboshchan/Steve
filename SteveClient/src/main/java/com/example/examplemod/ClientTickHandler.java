package com.example.examplemod;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.client.settings.KeyBinding;
import net.minecraft.entity.player.EntityPlayer;
import net.minecraft.item.ItemFishingRod;
import net.minecraft.item.ItemStack;
import net.minecraft.item.ItemSword;
import net.minecraft.util.MathHelper;
import net.minecraft.util.MovingObjectPosition;
import net.minecraftforge.fml.common.eventhandler.SubscribeEvent;
import net.minecraftforge.fml.common.gameevent.TickEvent;
import java.net.URI;
import java.util.List;

public class ClientTickHandler {
    private final Minecraft mc = Minecraft.getMinecraft();
    private SteveWebSocketClient ws = null;
    private int reconnectTimer = 0;

    public ClientTickHandler() {
        connectToServer();
    }

    private void connectToServer() {
        try {
            System.out.println("[SteveMod] Attempting to connect to Python server at ws://localhost:8765...");
            ws = new SteveWebSocketClient(new URI("ws://localhost:8765"));
            ws.connect();
        } catch (Exception e) {
            System.out.println("[SteveMod] Failed to connect: " + e.getMessage());
        }
    }

    @SubscribeEvent
    public void onClientTick(TickEvent.ClientTickEvent event) {
        // Run exactly once per complete tick loop during phase start, and verify player / world exist
        if (event.phase != TickEvent.Phase.START || mc.thePlayer == null || mc.theWorld == null) {
            return;
        }

        // Auto-reconnect if connection is lost
        if (ws == null || !ws.isOpen()) {
            reconnectTimer++;
            if (reconnectTimer >= 100) { // Try to reconnect every 5 seconds (100 ticks)
                reconnectTimer = 0;
                connectToServer();
            }
            return;
        }

        // 1. GATHER STATE VARIABLES
        JsonObject state = new JsonObject();
        
        // Self stats
        state.addProperty("hp", mc.thePlayer.getHealth() / mc.thePlayer.getMaxHealth());
        state.addProperty("vel_x", mc.thePlayer.motionX);
        state.addProperty("vel_y", mc.thePlayer.motionY);
        state.addProperty("vel_z", mc.thePlayer.motionZ);
        state.addProperty("y_ground", mc.thePlayer.posY - Math.floor(mc.thePlayer.posY));
        state.addProperty("is_sprinting", mc.thePlayer.isSprinting());
        state.addProperty("is_grounded", mc.thePlayer.onGround);
        
        // Active item
        int activeItemVal = 0; // default 0: Sword
        ItemStack currentItem = mc.thePlayer.inventory.getCurrentItem();
        if (currentItem != null && currentItem.getItem() instanceof ItemFishingRod) {
            activeItemVal = 1;
        }
        state.addProperty("active_item", activeItemVal);

        // Find closest opponent player
        double closestDist = 999.0;
        EntityPlayer closestEnemy = null;
        List<EntityPlayer> players = mc.theWorld.getEntitiesWithinAABB(EntityPlayer.class, 
                mc.thePlayer.getEntityBoundingBox().expand(15.0, 8.0, 15.0));
        
        for (EntityPlayer enemy : players) {
            if (enemy.getEntityId() == mc.thePlayer.getEntityId()) continue;
            double dist = mc.thePlayer.getDistanceToEntity(enemy);
            if (dist < closestDist) {
                closestDist = dist;
                closestEnemy = enemy;
            }
        }

        // Target stats
        if (closestEnemy != null) {
            state.addProperty("opp_hp", closestEnemy.getHealth() / closestEnemy.getMaxHealth());
            state.addProperty("opp_vel_x", closestEnemy.motionX);
            state.addProperty("opp_vel_y", closestEnemy.motionY);
            state.addProperty("opp_vel_z", closestEnemy.motionZ);
            state.addProperty("opp_rel_x", closestEnemy.posX - mc.thePlayer.posX);
            state.addProperty("opp_rel_y", closestEnemy.posY - mc.thePlayer.posY);
            state.addProperty("opp_rel_z", closestEnemy.posZ - mc.thePlayer.posZ);
            state.addProperty("target_dist", closestDist);

            // Calculate angle deltas to target eye position
            double diffX = closestEnemy.posX - mc.thePlayer.posX;
            double diffZ = closestEnemy.posZ - mc.thePlayer.posZ;
            double diffY = (closestEnemy.posY + closestEnemy.getEyeHeight()) - (mc.thePlayer.posY + mc.thePlayer.getEyeHeight());
            
            double targetYaw = Math.toDegrees(Math.atan2(diffZ, diffX)) - 90.0;
            double distXZ = Math.sqrt(diffX * diffX + diffZ * diffZ);
            double targetPitch = -Math.toDegrees(Math.atan2(diffY, distXZ));
            
            double yawDelta = MathHelper.wrapAngleTo180_double(targetYaw - mc.thePlayer.rotationYaw);
            double pitchDelta = MathHelper.wrapAngleTo180_double(targetPitch - mc.thePlayer.rotationPitch);
            
            state.addProperty("yaw_delta", yawDelta);
            state.addProperty("pitch_delta", pitchDelta);
        } else {
            state.addProperty("opp_hp", 0.0);
            state.addProperty("opp_vel_x", 0.0);
            state.addProperty("opp_vel_y", 0.0);
            state.addProperty("opp_vel_z", 0.0);
            state.addProperty("opp_rel_x", 0.0);
            state.addProperty("opp_rel_y", 0.0);
            state.addProperty("opp_rel_z", 0.0);
            state.addProperty("target_dist", 999.0);
            state.addProperty("yaw_delta", 0.0);
            state.addProperty("pitch_delta", 0.0);
        }

        // Swing cooldown/progress
        state.addProperty("swing_cooldown", mc.thePlayer.swingProgress);

        // 2. DISPATCH STATE DATA VECTOR TO PYTHON
        ws.send(state.toString());

        // 3. RETRIEVE AND ENFORCE RECEIVED DECISIONS
        if (ws.latestServerAction != null) {
            JsonObject actions = ws.latestServerAction;
            try {
                // Movement Overrides
                int move = actions.get("forward_back").getAsInt();
                int strafe = actions.get("strafe").getAsInt();
                int modifier = actions.get("modifier").getAsInt();
                int combat = actions.get("combat_action").getAsInt();

                // Apply keybind inputs using static KeyBinding method since 'pressed' field is private
                KeyBinding.setKeyBindState(mc.gameSettings.keyBindForward.getKeyCode(), (move == 1));
                KeyBinding.setKeyBindState(mc.gameSettings.keyBindBack.getKeyCode(), (move == 2));
                KeyBinding.setKeyBindState(mc.gameSettings.keyBindLeft.getKeyCode(), (strafe == 1));
                KeyBinding.setKeyBindState(mc.gameSettings.keyBindRight.getKeyCode(), (strafe == 2));
                KeyBinding.setKeyBindState(mc.gameSettings.keyBindJump.getKeyCode(), (modifier == 2));
                KeyBinding.setKeyBindState(mc.gameSettings.keyBindSneak.getKeyCode(), (modifier == 1));

                // Hotbar sword slot selection logic
                if (combat == 1 || combat == 2) {
                    int swordSlot = findHotbarSlot(ItemSword.class);
                    if (swordSlot != -1) {
                        mc.thePlayer.inventory.currentItem = swordSlot;
                    }
                }

                // Handle combat action
                if (combat == 1) { // Attack
                    KeyBinding.setKeyBindState(mc.gameSettings.keyBindUseItem.getKeyCode(), false);
                    mc.thePlayer.swingItem();
                    if (mc.objectMouseOver != null && mc.objectMouseOver.typeOfHit == MovingObjectPosition.MovingObjectType.ENTITY) {
                        mc.playerController.attackEntity(mc.thePlayer, mc.objectMouseOver.entityHit);
                    }
                } else if (combat == 2) { // Block
                    KeyBinding.setKeyBindState(mc.gameSettings.keyBindUseItem.getKeyCode(), true);
                } else if (combat == 3 || combat == 4) { // Cast or Reel Rod
                    KeyBinding.setKeyBindState(mc.gameSettings.keyBindUseItem.getKeyCode(), false);
                    int rodSlot = findHotbarSlot(ItemFishingRod.class);
                    if (rodSlot != -1) {
                        mc.thePlayer.inventory.currentItem = rodSlot;
                        // Trigger item use
                        mc.playerController.sendUseItem(mc.thePlayer, mc.theWorld, mc.thePlayer.inventory.getCurrentItem());
                    }
                } else {
                    KeyBinding.setKeyBindState(mc.gameSettings.keyBindUseItem.getKeyCode(), false);
                }

                // Apply mouse look deltas
                double mouseDeltaX = actions.get("mouse_delta_x").getAsDouble();
                double mouseDeltaY = actions.get("mouse_delta_y").getAsDouble();
                
                mc.thePlayer.rotationYaw += mouseDeltaX;
                mc.thePlayer.rotationPitch += mouseDeltaY;
                
                // Keep pitch in range
                if (mc.thePlayer.rotationPitch > 90.0F) mc.thePlayer.rotationPitch = 90.0F;
                if (mc.thePlayer.rotationPitch < -90.0F) mc.thePlayer.rotationPitch = -90.0F;

            } catch (Exception e) {
                e.printStackTrace();
            }
        }
    }

    private int findHotbarSlot(Class<?> itemClass) {
        for (int i = 0; i < 9; i++) {
            ItemStack stack = mc.thePlayer.inventory.mainInventory[i];
            if (stack != null && itemClass.isInstance(stack.getItem())) {
                return i;
            }
        }
        return -1;
    }
}
