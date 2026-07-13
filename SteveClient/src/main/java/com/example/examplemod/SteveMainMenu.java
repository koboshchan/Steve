package com.example.examplemod;

import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiButton;
import net.minecraft.client.gui.GuiMainMenu;
import net.minecraft.client.renderer.GlStateManager;
import net.minecraft.util.MathHelper;
import net.minecraft.util.ResourceLocation;

public class SteveMainMenu extends GuiMainMenu {
    private static final ResourceLocation minecraftTitleTextures = new ResourceLocation("textures/gui/title/minecraft.png");
    private String splashTextVal = "";

    public SteveMainMenu() {
        super();
        try {
            // Obfuscation-safe extraction of splash text String field
            for (java.lang.reflect.Field field : GuiMainMenu.class.getDeclaredFields()) {
                if (field.getType() == String.class && !java.lang.reflect.Modifier.isStatic(field.getModifiers())) {
                    field.setAccessible(true);
                    String val = (String) field.get(this);
                    if (val != null && !val.isEmpty()) {
                        splashTextVal = val;
                        break;
                    }
                }
            }
        } catch (Exception e) {
            splashTextVal = "Steve PvP Mod!";
        }
    }

    @Override
    public void drawScreen(int mouseX, int mouseY, float partialTicks) {
        // Draw default background instead of the panorama which crashes in glCopyTexSubImage2D under Rosetta
        this.drawDefaultBackground();
        
        // Draw title texture
        this.mc.getTextureManager().bindTexture(minecraftTitleTextures);
        GlStateManager.color(1.0F, 1.0F, 1.0F, 1.0F);
        int short1 = 274;
        int k = this.width / 2 - short1 / 2;
        byte b0 = 30;
        this.drawTexturedModalRect(k, b0 + 0, 0, 0, 155, 44);
        this.drawTexturedModalRect(k + 155, b0 + 0, 0, 45, 155, 44);
        
        // Draw copyright and version text
        String s = "Minecraft 1.8.9";
        if (this.mc.isDemo()) {
            s = s + " Demo";
        }
        this.drawString(this.fontRendererObj, s, 2, this.height - 10, -1);
        
        String s1 = "Copyright Mojang AB. Do not distribute!";
        this.drawString(this.fontRendererObj, s1, this.width - this.fontRendererObj.getStringWidth(s1) - 2, this.height - 10, -1);
        
        // Draw yellow splash text
        if (splashTextVal != null && !splashTextVal.isEmpty()) {
            GlStateManager.pushMatrix();
            GlStateManager.translate((float)(this.width / 2 + 90), 70.0F, 0.0F);
            GlStateManager.rotate(-20.0F, 0.0F, 0.0F, 1.0F);
            float f = 1.8F - MathHelper.abs(MathHelper.sin((float)(Minecraft.getSystemTime() % 1000L) / 1000.0F * (float)Math.PI * 2.0F) * 0.1F);
            f = f * 100.0F / (float)(this.fontRendererObj.getStringWidth(splashTextVal) + 32);
            GlStateManager.scale(f, f, f);
            this.drawCenteredString(this.fontRendererObj, splashTextVal, 0, -8, -256);
            GlStateManager.popMatrix();
        }

        // Draw buttons
        for (int i = 0; i < this.buttonList.size(); ++i) {
            ((GuiButton)this.buttonList.get(i)).drawButton(this.mc, mouseX, mouseY);
        }
    }
}
