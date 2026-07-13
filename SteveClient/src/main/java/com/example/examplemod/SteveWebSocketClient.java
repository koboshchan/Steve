package com.example.examplemod;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.client.Minecraft;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;
import java.net.URI;

public class SteveWebSocketClient extends WebSocketClient {
    private final Minecraft mc = Minecraft.getMinecraft();
    public JsonObject latestServerAction = null;

    public SteveWebSocketClient(URI serverUri) {
        super(serverUri);
    }

    @Override
    public void onOpen(ServerHandshake handshakedata) {
        System.out.println("[SteveMod] WebSocket Pipe Opened!");
    }

    @Override
    public void onMessage(String message) {
        try {
            latestServerAction = new JsonParser().parse(message).getAsJsonObject();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    @Override
    public void onClose(int code, String reason, boolean remote) {
        System.out.println("[SteveMod] WebSocket Closed: " + reason);
    }

    @Override
    public void onError(Exception ex) {
        ex.printStackTrace();
    }
}
