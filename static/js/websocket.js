(function () {
  // WebSocket client for live messaging.
  // dashboard.js picks the active conversation and calls SyncChatSocket.connect(id).
  // Server frames are JSON and are re-dispatched as CustomEvents that dashboard.js
  // listens to: syncchat:message, syncchat:typing, syncchat:read,
  // syncchat:presence, syncchat:profile, syncchat:block.

  const app = document.getElementById("app");
  if (!app) return;

  // Max reconnect attempts before giving up and marking the connection offline.
  const maxRetries = 5;
  let socket = null;
  let retries = 0;
  let reconnectTimer = null;
  let conversationId = null;
  // Guards stale sockets/timers when switching conversations quickly.
  let generation = 0;

  // Build a ws:// or wss:// URL matching the current page scheme.
  const urlFor = (id) =>
    (location.protocol === "https:" ? "wss" : "ws") +
    "://" + location.host + "/ws/chat/" + id + "/";

  // Reflect the connection state on <app data-ws> so CSS can react to
  // connection changes. The chat header's presence dot under the username is a
  // separate signal driven by the syncchat:presence event.
  function setState(state) {
    app.dataset.ws = state;
  }

  // Open a socket for the current conversation and wire up its handlers.
  // On an unexpected close, schedule a reconnection with exponential backoff.
  function open(gen) {
    setState("connecting");
    socket = new WebSocket(urlFor(conversationId));

    socket.addEventListener("open", () => {
      retries = 0;
      setState("connected");
    });

    // Route each server frame to the dashboard event that handles it.
    socket.addEventListener("message", (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (data.type === "presence") {
        window.dispatchEvent(
          new CustomEvent("syncchat:presence", { detail: data })
        );
        return;
      }
      if (data.type === "typing") {
        window.dispatchEvent(
          new CustomEvent("syncchat:typing", { detail: data })
        );
        return;
      }
      if (data.type === "read") {
        window.dispatchEvent(
          new CustomEvent("syncchat:read", { detail: data })
        );
        return;
      }
      if (data.type === "block_change") {
        window.dispatchEvent(
          new CustomEvent("syncchat:block", { detail: data })
        );
        return;
      }
      if (data.type === "profile") {
        window.dispatchEvent(
          new CustomEvent("syncchat:profile", { detail: data })
        );
        return;
      }
      window.dispatchEvent(
        new CustomEvent("syncchat:message", { detail: data })
      );
    });

    // Handle disconnect: retry with backoff, or show Offline when exhausted.
    socket.addEventListener("close", () => {
      // Ignore close events from a socket superseded by a newer connect(id).
      if (gen !== generation) return;
      if (retries < maxRetries) {
        setState("reconnecting");
        retries += 1;
        reconnectTimer = setTimeout(
          () => open(gen),
          Math.min(1000 * 2 ** retries, 15000)
        );
      } else {
        setState("offline");
      }
    });
  }

  // Point the socket at a conversation, tearing down any previous one first.
  // Re-calling connect() with the same live socket is a no-op. Called by
  // dashboard.js whenever a chat is opened.
  function connect(id) {
    if (!id) return;
    if (id === conversationId && socket && socket.readyState <= WebSocket.OPEN) return;
    conversationId = id;
    generation += 1;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (socket) {
      socket.onclose = null;
      socket.close();
      socket = null;
    }
    retries = 0;
    open(generation);
  }

  // Send a message over the socket. Returns false when there is no live socket,
  // so dashboard.js can fall back to the HTTP send endpoint instead.
  function send(text) {
    const value = String(text).trim();
    if (!value || !socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify({ content: value }));
    return true;
  }

  // Send a typing indicator (true = typing, false = stopped).
  function sendTyping(value) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify({ type: "typing", value: !!value }));
    return true;
  }

  // Explicitly disconnect and cleanup the socket (e.g., before logout).
  function disconnect() {
    generation += 1;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (socket) {
      socket.onclose = null;
      socket.close();
      socket = null;
    }
    conversationId = null;
    setState("offline");
  }

  window.SyncChatSocket = { connect, send, sendTyping, disconnect };

  // If a conversation is already selected on load, connect to it right away.
  const initial = app.dataset.conversationId;
  if (initial) connect(initial);
})();
