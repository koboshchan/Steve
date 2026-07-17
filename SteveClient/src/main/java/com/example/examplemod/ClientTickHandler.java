package com.example.examplemod;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiMainMenu;
import net.minecraft.client.settings.KeyBinding;
import net.minecraft.entity.player.EntityPlayer;
import net.minecraft.init.Blocks;
import net.minecraft.item.Item;
import net.minecraft.init.Items;
import net.minecraft.item.ItemFishingRod;
import net.minecraft.item.ItemStack;
import net.minecraft.item.ItemSword;
import net.minecraft.util.MathHelper;
import net.minecraft.util.MovingObjectPosition;
import net.minecraft.util.Vec3;
import net.minecraftforge.client.event.GuiOpenEvent;
import net.minecraftforge.fml.common.eventhandler.SubscribeEvent;
import net.minecraftforge.fml.common.gameevent.TickEvent;
import java.net.URI;
import java.util.List;

public class ClientTickHandler {
    private final Minecraft mc = Minecraft.getMinecraft();
    private SteveWebSocketClient ws = null;
    private int reconnectTimer = 0;
    private int rightClickDelay = 0;
    private int commandDelay = 0;
    private String serverDifficulty = "easy";
    private boolean isTrainingServer = false;

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

        try {
        // Auto-use lime dye and command if connected to a training server
        if (isTrainingServer) {
            int limeDyeSlot = findLimeDyeSlot();
            if (limeDyeSlot != -1) {
                if (rightClickDelay <= 0) {
                    mc.thePlayer.inventory.currentItem = limeDyeSlot;
                    mc.playerController.sendUseItem(mc.thePlayer, mc.theWorld, mc.thePlayer.inventory.getCurrentItem());
                    rightClickDelay = 10; // Cooldown of 10 ticks (0.5 seconds)
                } else {
                    rightClickDelay--;
                }
            } else {
                rightClickDelay = 0;
            }

            // Auto-run botduel command if queue items are present in inventory
            if (hasQueueItems()) {
                if (commandDelay <= 0) {
                    System.out.println("[SteveMod] Queue items detected! Sending command: /botduel diamond random " + serverDifficulty);
                    mc.thePlayer.sendChatMessage("/botduel diamond random " + serverDifficulty);
                    commandDelay = 100; // Cooldown of 5 seconds (100 ticks) to prevent spamming
                } else {
                    commandDelay--;
                }
            } else {
                commandDelay = 0; // Reset command delay when not holding queue items
            }
        } else {
            rightClickDelay = 0;
            commandDelay = 0;
        }

        // Auto-reconnect if connection is lost
        if (ws == null || !ws.isOpen()) {
            isTrainingServer = false; // Reset status when connection is lost
            reconnectTimer++;
            if (reconnectTimer >= 100) { // Try to reconnect every 5 seconds (100 ticks)
                reconnectTimer = 0;
                connectToServer();
            }
            return;
        }

        // In-game detection: arrows in inventory = in game, no arrows = lobby
        boolean inMatch = hasArrows();

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
        state.addProperty("pitch", mc.thePlayer.rotationPitch);
        state.addProperty("yaw", mc.thePlayer.rotationYaw);
        
        // Active item
        int activeItemVal = 0; // default 0: Sword
        ItemStack currentItem = mc.thePlayer.inventory.getCurrentItem();
        if (currentItem != null && currentItem.getItem() instanceof ItemFishingRod) {
            activeItemVal = 1;
        }
        state.addProperty("active_item", activeItemVal);

        // Hotbar detection states
        state.addProperty("sword_slot", findSwordSlot());
        state.addProperty("rod_slot", findRodSlot());
        state.addProperty("in_match", inMatch);

        // Get fishing rod durability ratio
        double rodDurability = 1.0;
        int rodSlotIndex = findRodSlot();
        if (rodSlotIndex != -1) {
            ItemStack rodStack = mc.thePlayer.inventory.mainInventory[rodSlotIndex];
            if (rodStack != null && rodStack.isItemStackDamageable()) {
                rodDurability = (double)(rodStack.getMaxDamage() - rodStack.getItemDamage()) / (double)rodStack.getMaxDamage();
            }
        }
        state.addProperty("rod_durability", rodDurability);

        // Map wall distances (front, back, left, right)
        state.addProperty("front_wall_dist", getDistanceToWall(mc.thePlayer.rotationYaw));
        state.addProperty("right_wall_dist", getDistanceToWall(mc.thePlayer.rotationYaw + 90.0));
        state.addProperty("back_wall_dist", getDistanceToWall(mc.thePlayer.rotationYaw + 180.0));
        state.addProperty("left_wall_dist", getDistanceToWall(mc.thePlayer.rotationYaw - 90.0));

        // Find closest opponent player
        double closestDist = 999.0;
        EntityPlayer closestEnemy = null;
        List<EntityPlayer> players = mc.theWorld.playerEntities;
        
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

            // Calculate angle deltas to target eye position (how we look at them)
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

            // Calculate opponent look deltas back to player eye position (how they look at us)
            double oppToPlayerX = mc.thePlayer.posX - closestEnemy.posX;
            double oppToPlayerZ = mc.thePlayer.posZ - closestEnemy.posZ;
            double oppToPlayerY = (mc.thePlayer.posY + mc.thePlayer.getEyeHeight()) - (closestEnemy.posY + closestEnemy.getEyeHeight());
            
            double oppTargetYaw = Math.toDegrees(Math.atan2(oppToPlayerZ, oppToPlayerX)) - 90.0;
            double oppDistXZ = Math.sqrt(oppToPlayerX * oppToPlayerX + oppToPlayerZ * oppToPlayerZ);
            double oppTargetPitch = -Math.toDegrees(Math.atan2(oppToPlayerY, oppDistXZ));
            
            double oppYawDelta = MathHelper.wrapAngleTo180_double(oppTargetYaw - closestEnemy.rotationYaw);
            double oppPitchDelta = MathHelper.wrapAngleTo180_double(oppTargetPitch - closestEnemy.rotationPitch);
            
            state.addProperty("opp_yaw_offset", oppYawDelta);
            state.addProperty("opp_pitch_offset", oppPitchDelta);
        } else {
            state.addProperty("opp_hp", 1.0);
            state.addProperty("opp_vel_x", 0.0);
            state.addProperty("opp_vel_y", 0.0);
            state.addProperty("opp_vel_z", 0.0);
            state.addProperty("opp_rel_x", 0.0);
            state.addProperty("opp_rel_y", 0.0);
            state.addProperty("opp_rel_z", 0.0);
            state.addProperty("target_dist", 999.0);
            state.addProperty("yaw_delta", 0.0);
            state.addProperty("pitch_delta", 0.0);
            state.addProperty("opp_yaw_offset", 0.0);
            state.addProperty("opp_pitch_offset", 0.0);
        }

        state.addProperty("opp_found", closestEnemy != null);

        // Swing cooldown/progress
        state.addProperty("swing_cooldown", mc.thePlayer.swingProgress);

        // 2. DISPATCH STATE AND SYNCHRONOUSLY WAIT FOR SERVER RESPONSE
        // This blocks the tick thread until the Python server responds (or 40ms timeout).
        // Lock-step ensures actions are computed on the CURRENT tick's state, not stale data.
        JsonObject actions = ws.sendAndWaitForResponse(state.toString(), 40);

        // 3. RETRIEVE AND ENFORCE RECEIVED DECISIONS
        if (actions != null) {
            try {
                // Parse difficulty if provided by the server
                if (actions.has("difficulty")) {
                    serverDifficulty = actions.get("difficulty").getAsString();
                }

                // Parse is_training status if provided by the server, defaulting to false
                if (actions.has("is_training")) {
                    isTrainingServer = actions.get("is_training").getAsBoolean();
                } else {
                    isTrainingServer = false;
                }

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

                // Force Auto-Sprint if moving forward, not sneaking, and not blocking
                if (move == 1 && modifier != 1 && combat != 2) {
                    mc.thePlayer.setSprinting(true);
                    KeyBinding.setKeyBindState(mc.gameSettings.keyBindSprint.getKeyCode(), true);
                } else {
                    KeyBinding.setKeyBindState(mc.gameSettings.keyBindSprint.getKeyCode(), false);
                }

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
        } else {
            // Stop everything if no action was received from server (e.g. training epoch is updating)
            KeyBinding.setKeyBindState(mc.gameSettings.keyBindForward.getKeyCode(), false);
            KeyBinding.setKeyBindState(mc.gameSettings.keyBindBack.getKeyCode(), false);
            KeyBinding.setKeyBindState(mc.gameSettings.keyBindLeft.getKeyCode(), false);
            KeyBinding.setKeyBindState(mc.gameSettings.keyBindRight.getKeyCode(), false);
            KeyBinding.setKeyBindState(mc.gameSettings.keyBindJump.getKeyCode(), false);
            KeyBinding.setKeyBindState(mc.gameSettings.keyBindSneak.getKeyCode(), false);
            KeyBinding.setKeyBindState(mc.gameSettings.keyBindUseItem.getKeyCode(), false);
        }
        } catch (Exception e) {
            System.out.println("[SteveMod] Exception in client tick: " + e.getMessage());
            e.printStackTrace();
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

    private int findLimeDyeSlot() {
        for (int i = 0; i < 9; i++) {
            ItemStack stack = mc.thePlayer.inventory.mainInventory[i];
            if (stack != null && stack.getItem() == Items.dye && stack.getItemDamage() == 10) {
                return i;
            }
        }
        return -1;
    }

    private int findSwordSlot() {
        for (int i = 0; i < 9; i++) {
            ItemStack stack = mc.thePlayer.inventory.mainInventory[i];
            if (stack != null && (stack.getItem() == Items.diamond_sword || stack.getItem() == Items.iron_sword)) {
                return i;
            }
        }
        return -1;
    }

    private int findRodSlot() {
        for (int i = 0; i < 9; i++) {
            ItemStack stack = mc.thePlayer.inventory.mainInventory[i];
            if (stack != null && stack.getItem() == Items.fishing_rod) {
                return i;
            }
        }
        return -1;
    }

    @SubscribeEvent
    public void onGuiOpen(GuiOpenEvent event) {
        if (event.gui instanceof GuiMainMenu && !(event.gui instanceof SteveMainMenu)) {
            event.gui = new SteveMainMenu();
        }
    }

    private double getDistanceToWall(double yaw) {
        try {
            double rad = Math.toRadians(yaw);
            double dx = -Math.sin(rad);
            double dz = Math.cos(rad);
            
            Vec3 start = new Vec3(mc.thePlayer.posX, mc.thePlayer.posY + mc.thePlayer.getEyeHeight(), mc.thePlayer.posZ);
            Vec3 end = new Vec3(mc.thePlayer.posX + dx * 50.0, mc.thePlayer.posY + mc.thePlayer.getEyeHeight(), mc.thePlayer.posZ + dz * 50.0);
            
            MovingObjectPosition mop = mc.theWorld.rayTraceBlocks(start, end, false, true, false);
            if (mop != null && mop.typeOfHit == MovingObjectPosition.MovingObjectType.BLOCK) {
                return start.distanceTo(mop.hitVec);
            }
        } catch (Exception e) {
            // Safe fallback
        }
        return 50.0;
    }

    private boolean hasArrows() {
        if (mc.thePlayer == null || mc.thePlayer.inventory == null) return false;
        for (ItemStack stack : mc.thePlayer.inventory.mainInventory) {
            if (stack != null && stack.getItem() == Items.arrow) {
                return true;
            }
        }
        return false;
    }

    private boolean hasQueueItems() {
        if (mc.thePlayer == null || mc.thePlayer.inventory == null) return false;
        boolean hasAnvil = false;
        boolean hasBlazePowder = false;
        boolean hasEnderEye = false;
        
        for (ItemStack stack : mc.thePlayer.inventory.mainInventory) {
            if (stack == null) continue;
            
            // Check anvil (which is block-based)
            if (stack.getItem() == Item.getItemFromBlock(Blocks.anvil)) {
                hasAnvil = true;
            }
            // Check blaze powder
            if (stack.getItem() == Items.blaze_powder) {
                hasBlazePowder = true;
            }
            // Check ender eye
            if (stack.getItem() == Items.ender_eye) {
                hasEnderEye = true;
            }
        }
        return hasAnvil && hasBlazePowder && hasEnderEye;
    }
}
