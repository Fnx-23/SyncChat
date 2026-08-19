(function () {
  // Global presence client. Loaded on every authenticated page via base.html
  // (which only includes it when the request user is authenticated), so the
  // user's online status reflects the application, not the page they are on.
  //
  // A dedicated /ws/presence/ socket stays open across page navigation:
  // navigating to /settings, /profile, etc. keeps the user Online. The server
  // holds a grace period after the old socket closes, so the brief gap while
  // the next page loads never flips the user to Offline. Heartbeats (ping/pong)
  // keep the connection alive and let the server detect dead links.

  // Guard against double-loading (e.g. hot reload or duplicate inclusion).
  if (window.SyncChatPresence) return;

  const maxRetries = 5;
  const pingIntervalMs = 20000;

  let socket = null;
  let retries = 0;
  let reconnectTimer = null;
  let pingTimer = null;
  // Guards stale sockets/timers when reconnecting.
  let generation = 0;

  // Build a ws:// or wss:// URL matching the current page scheme.
  const urlFor = () =>
    (location.protocol === "https:" ? "wss" : "ws") +
    "://" + location.host + "/ws/presence/";

  // Tell the server whether this tab is backgrounded so it can use a longer
  // heartbeat window (browsers throttle timers in hidden tabs).
  function reportVisibility() {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "visibility", hidden: document.hidden }));
    }
  }

  function dispatch(type, detail) {
    window.dispatchEvent(new CustomEvent(type, { detail }));
  }

  // Open the socket and wire up its handlers. On an unexpected close,
  // reconnect with exponential backoff.
  function open(gen) {
    socket = new WebSocket(urlFor());

    socket.addEventListener("open", () => {
      retries = 0;
      reportVisibility();
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        }
      }, pingIntervalMs);
    });

    // Route server frames to the dashboard events that handle them. "pong"
    // frames need no action; they only confirm the link is alive.
    socket.addEventListener("message", (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (data.type === "presence") {
        dispatch("syncchat:presence", data);
      } else if (data.type === "profile") {
        dispatch("syncchat:profile", data);
      } else if (data.type === "new_message") {
        dispatch("syncchat:new_message", data);
      }
    });

    socket.addEventListener("close", () => {
      if (gen !== generation) return;
      if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
      }
      if (retries < maxRetries) {
        retries += 1;
        reconnectTimer = setTimeout(
          () => open(gen),
          Math.min(1000 * 2 ** retries, 15000)
        );
      }
    });

    socket.addEventListener("error", () => {
      // The close handler drives reconnection.
    });
  }

  window.SyncChatPresence = {
    // (Re)connect the presence socket, tearing down any previous one first.
    connect() {
      generation += 1;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
      }
      if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
      }
      retries = 0;
      open(generation);
    },
    // Explicitly disconnect and stop reconnecting (e.g. before logout).
    disconnect() {
      generation += 1;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
      }
      if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
      }
    }
  };

  document.addEventListener("visibilitychange", reportVisibility);
  window.addEventListener("focus", reportVisibility);

  // Start now: the script is loaded at the end of <body>, so the DOM is ready
  // and the server can start tracking this user's presence immediately.
  window.SyncChatPresence.connect();
})();
