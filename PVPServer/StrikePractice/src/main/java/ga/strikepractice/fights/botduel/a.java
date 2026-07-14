/*
 * Decompiled with CFR 0.152.
 * 
 * Could not load the following classes:
 *  org.bukkit.Bukkit
 *  org.bukkit.ChatColor
 *  org.bukkit.command.Command
 *  org.bukkit.command.CommandExecutor
 *  org.bukkit.command.CommandSender
 *  org.bukkit.entity.HumanEntity
 *  org.bukkit.entity.Player
 *  org.bukkit.event.EventHandler
 *  org.bukkit.event.Listener
 *  org.bukkit.event.inventory.ClickType
 *  org.bukkit.event.inventory.InventoryClickEvent
 *  org.bukkit.inventory.InventoryHolder
 *  org.bukkit.inventory.ItemStack
 *  org.bukkit.inventory.meta.ItemMeta
 */
package ga.strikepractice.fights.botduel;

import ga.strikepractice.StrikePractice;
import ga.strikepractice.arena.Arena;
import ga.strikepractice.arena.d;
import ga.strikepractice.battlekit.BattleKit;
import ga.strikepractice.battlekit.BattleKitType;
import ga.strikepractice.fights.AbstractFight;
import ga.strikepractice.fights.botduel.BotDuel;
import ga.strikepractice.fights.botduel.b;
import ga.strikepractice.fights.duel.BestOf;
import ga.strikepractice.hostedevents.PvPEvent;
import ga.strikepractice.kotlin.Metadata;
import ga.strikepractice.kotlin.collections.ArraysKt;
import ga.strikepractice.kotlin.jvm.internal.Intrinsics;
import ga.strikepractice.kotlin.text.StringsKt;
import ga.strikepractice.npc.CitizensNPC;
import ga.strikepractice.npc.e;
import ga.strikepractice.party.Party;
import ga.strikepractice.utils.H;
import ga.strikepractice.utils.i;
import ga.strikepractice.utils.v;
import java.util.logging.Logger;
import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.HumanEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.inventory.ClickType;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.inventory.InventoryHolder;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.jetbrains.annotations.NotNull;

@Metadata(mv={1, 6, 0}, k=1, xi=48, d1={"\u0000B\n\u0002\u0018\u0002\n\u0002\u0018\u0002\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0002\b\u0002\n\u0002\u0010\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0010\u000b\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0010\u000e\n\u0000\n\u0002\u0010\u0011\n\u0002\b\u0002\u0018\u00002\u00020\u00012\u00020\u0002B\r\u0012\u0006\u0010\u0003\u001a\u00020\u0004\u00a2\u0006\u0002\u0010\u0005J\u0010\u0010\u0006\u001a\u00020\u00072\u0006\u0010\b\u001a\u00020\tH\u0007J3\u0010\n\u001a\u00020\u000b2\u0006\u0010\f\u001a\u00020\r2\u0006\u0010\u000e\u001a\u00020\u000f2\u0006\u0010\u0010\u001a\u00020\u00112\f\u0010\u0012\u001a\b\u0012\u0004\u0012\u00020\u00110\u0013H\u0016\u00a2\u0006\u0002\u0010\u0014R\u000e\u0010\u0003\u001a\u00020\u0004X\u0082\u0004\u00a2\u0006\u0002\n\u0000\u00a8\u0006\u0015"}, d2={"Lga/strikepractice/fights/botduel/BotDuelCommand;", "Lorg/bukkit/command/CommandExecutor;", "Lorg/bukkit/event/Listener;", "plugin", "Lga/strikepractice/StrikePractice;", "(Lga/strikepractice/StrikePractice;)V", "onClick", "", "e", "Lorg/bukkit/event/inventory/InventoryClickEvent;", "onCommand", "", "p", "Lorg/bukkit/command/CommandSender;", "cmd", "Lorg/bukkit/command/Command;", "label", "", "args", "", "(Lorg/bukkit/command/CommandSender;Lorg/bukkit/command/Command;Ljava/lang/String;[Ljava/lang/String;)Z", "strikepractice-core"})
public final class a
implements CommandExecutor,
Listener {
    @NotNull
    private final StrikePractice plugin;

    public a(@NotNull StrikePractice strikePractice) {
        Intrinsics.checkNotNullParameter((Object)strikePractice, "plugin");
        this.plugin = strikePractice;
    }

    @EventHandler
    public final void a(@NotNull InventoryClickEvent inventoryClickEvent) {
        Intrinsics.checkNotNullParameter(inventoryClickEvent, "e");
        if (!(inventoryClickEvent.getWhoClicked() instanceof Player)) {
            return;
        }
        HumanEntity humanEntity = inventoryClickEvent.getWhoClicked();
        if (humanEntity == null) {
            throw new NullPointerException("null cannot be cast to non-null type org.bukkit.entity.Player");
        }
        Player player = (Player)humanEntity;
        InventoryHolder inventoryHolder = inventoryClickEvent.getInventory().getHolder();
        if (inventoryHolder instanceof b) {
            String string = inventoryClickEvent.getView().getTitle();
            String string2 = this.plugin.getConfig().getString("inventory-title");
            Intrinsics.checkNotNullExpressionValue(string2, "plugin.config.getString(\"inventory-title\")");
            if (Intrinsics.areEqual(string, i.K(string2))) {
                if (inventoryClickEvent.getClickedInventory() == null || Intrinsics.areEqual(inventoryClickEvent.getClickedInventory(), player.getInventory())) {
                    return;
                }
                if (v.i(inventoryClickEvent.getCurrentItem())) {
                    ItemStack clickedItem = inventoryClickEvent.getCurrentItem();
                    inventoryClickEvent.setCancelled(true);
                    ItemMeta itemMeta = clickedItem.getItemMeta();
                    boolean bl = itemMeta != null ? itemMeta.hasDisplayName() : false;
                    if (bl && inventoryClickEvent.getSlot() == inventoryClickEvent.getInventory().getSize() - 1 && this.plugin.getConfig().getBoolean("kit-editor-in-kit-selector")) {
                        this.plugin.aa().aj(player);
                        return;
                    }
                    BattleKit battleKit = BattleKit.getKit(player, clickedItem, false);
                    BattleKit battleKit2 = this.plugin.aa().al(player).dZ();
                    
                    String clickedDisplayName = (itemMeta != null && itemMeta.hasDisplayName()) ? itemMeta.getDisplayName() : null;
                    if (battleKit2 != null && Intrinsics.areEqual(battleKit2.getName(), clickedDisplayName)) {
                        battleKit = battleKit2;
                    }
                    if (battleKit == null) {
                        player.sendMessage(ChatColor.RED.toString() + "Error: invalid kit.. please try another kit and contact admins!");
                        return;
                    }
                    if ((inventoryClickEvent.getClick() == ClickType.SHIFT_LEFT || inventoryClickEvent.getClick() == ClickType.SHIFT_RIGHT) && this.plugin.getConfig().getBoolean("preview.shift-click-preview")) {
                        ga.strikepractice.o.a.a(player, battleKit, this.plugin);
                        return;
                    }
                    int n2 = ((b)inventoryHolder).getRounds();
                    BotDuel botDuel = new BotDuel(this.plugin, player.getName(), battleKit);
                    if (n2 > 0) {
                        botDuel.setBestOf(new BestOf(n2));
                    }
                    
                    // Instantiate ga.strikepractice.fights.a.b via reflection to avoid compiler conflicts
                    try {
                        Class<?> clazz = Class.forName("ga.strikepractice.fights.a.b");
                        java.lang.reflect.Constructor<?> constructor = clazz.getConstructor(Player.class, BattleKit.class, java.util.function.Consumer.class);
                        constructor.newInstance(player, battleKit, (java.util.function.Consumer<Arena>) (arena -> a.a(botDuel, player, arena)));
                    } catch (Exception ex) {
                        ex.printStackTrace();
                    }
                }
            }
        }
    }

    public boolean onCommand(@NotNull CommandSender commandSender, @NotNull Command command, @NotNull String string, @NotNull String[] stringArray) {
        Intrinsics.checkNotNullParameter((Object)commandSender, "p");
        Intrinsics.checkNotNullParameter((Object)command, "cmd");
        Intrinsics.checkNotNullParameter((Object)string, "label");
        Intrinsics.checkNotNullParameter((Object)stringArray, "args");

        if (!(commandSender instanceof Player)) {
            commandSender.sendMessage(ChatColor.RED + "Only players can run this command.");
            return true;
        }
        Player player = (Player)commandSender;
        if (PvPEvent.isInEvent(player) || AbstractFight.getCurrentFight(player) != null) {
            this.plugin.a(player, "you-can-not-duel-now");
            return true;
        }
        if (Party.getParty(player) != null) {
            this.plugin.a(player, "can-not-do-while-in-party");
            return true;
        }
        if (!this.plugin.I) {
            player.sendMessage(ChatColor.RED.toString() + "Bot fights are disabled because Citizens plugin is not installed!");
            return true;
        }

        // If they provided 3 or more arguments, we run direct queue
        if (stringArray.length >= 3) {
            String kitName = stringArray[0];
            String mapName = stringArray[1];
            String diffStr = stringArray[2];

            BattleKit battleKit = StrikePractice.getAPI().getKit(kitName);
            if (battleKit == null) {
                player.sendMessage(ChatColor.RED + "Error: BattleKit '" + kitName + "' not found!");
                return true;
            }

            // Determine Arena
            Arena arena = null;
            if (!mapName.equalsIgnoreCase("random")) {
                arena = d.getArena(mapName);
            }
            if (arena == null) {
                if (battleKit.isBuild()) {
                    arena = d.b(player, battleKit);
                } else {
                    arena = d.d(player, battleKit);
                }
            }
            if (arena == null) {
                player.sendMessage(ChatColor.RED + "Error: No suitable arena found!");
                return true;
            }

            // Determine Difficulty
            CitizensNPC.a difficulty = CitizensNPC.a.lX;
            if (diffStr.equalsIgnoreCase("normal") || diffStr.equalsIgnoreCase("medium")) {
                difficulty = CitizensNPC.a.lY;
            } else if (diffStr.equalsIgnoreCase("hard")) {
                difficulty = CitizensNPC.a.lZ;
            } else if (diffStr.equalsIgnoreCase("hacker")) {
                difficulty = CitizensNPC.a.ma;
            }

            BotDuel botDuel = new BotDuel(this.plugin, player.getName(), battleKit);
            botDuel.setDifficulty(difficulty);
            botDuel.setArena(arena);

            if (botDuel.canStart()) {
                botDuel.start();
            } else {
                d.c(player);
            }
            return true;
        }

        // Under 3 arguments: open the GUI normally
        this.plugin.L.a(player, new b(-1), BattleKitType.BOT_FIGHT);
        return true;
    }

    private static final void a(BotDuel botDuel, Player player, Arena arena) {
        Intrinsics.checkNotNullParameter(botDuel, "$botDuel");
        Intrinsics.checkNotNullParameter(player, "$p");
        botDuel.setArena(arena);
        e.a(player, botDuel);
    }

    private static final void a(BotDuel botDuel, CommandSender commandSender, Arena arena) {
        Intrinsics.checkNotNullParameter(botDuel, "$botDuel");
        Intrinsics.checkNotNullParameter(commandSender, "$p");
        botDuel.setArena(arena);
        e.a((Player)commandSender, botDuel);
    }
}

