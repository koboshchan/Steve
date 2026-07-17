package com.example.examplemod;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.client.Minecraft;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;
import java.net.URI;
import java.util.concurrent.SynchronousQueue;
import java.util.concurrent.TimeUnit;

public class SteveWebSocketClient extends WebSocketClient {
    private final Minecraft mc = Minecraft.getMinecraft();

    /**
     * Rendezvous queue for lock-step tick synchronization.
     * The WebSocket receiver thread puts each parsed server response here;
     * the client tick thread takes it via sendAndWaitForResponse().
     */
    private final SynchronousQueue<JsonObject> responseQueue = new SynchronousQueue<JsonObject>();

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
            JsonObject action = new JsonParser().parse(message).getAsJsonObject();
            // Offer the response to the waiting tick thread.
            // If no thread is waiting (e.g. stale/duplicate message), it is silently dropped.
            responseQueue.offer(action);
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    /**
     * Sends a state message to the server and blocks until the response
     * arrives or the timeout elapses.
     *
     * @param message   JSON state string to send
     * @param timeoutMs Maximum milliseconds to wait for the server response
     * @return The server's action JsonObject, or null on timeout
     */
    public JsonObject sendAndWaitForResponse(String message, long timeoutMs) {
        // Drain any stale response that arrived between ticks (shouldn't happen,
        // but guards against edge cases like server sending unsolicited messages)
        responseQueue.poll();

        // Send state to server
        send(message);

        // Block until the server responds or timeout
        try {
            return responseQueue.poll(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
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
