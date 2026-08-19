(function () {
  const esc = SyncChatCommon.esc;
  const initials = SyncChatCommon.initials;

  const AVATARS = [
    { bg: "#dfe9f7", fg: "#1d3b6e" },
    { bg: "#e5ecf2", fg: "#2c3e50" },
    { bg: "#f0e8dd", fg: "#5a4a33" },
    { bg: "#e2efe6", fg: "#1f4d36" },
    { bg: "#f2e4e4", fg: "#5d3131" },
    { bg: "#e8e4f0", fg: "#3f3461" }
  ];

  let users = [];
  let me = "";
  let meProfile = null;
  const dataEl = document.getElementById("syncchat-data");
  if (dataEl) {
    try {
      const payload = JSON.parse(dataEl.textContent);
      users = payload.conversations || [];
      me = payload.me || "";
      meProfile = payload.me_profile || null;
    } catch (e) {
      users = [];
    }
  }

  const app = document.getElementById("app");
  const convoList = document.getElementById("convo-list");
  const searchInput = document.getElementById("search");
  const chatBody = document.getElementById("chat-body");
  const msgInput = document.getElementById("msg-input");
  const sendBtn = document.getElementById("send-btn");
  const chatAvatar = document.getElementById("chat-avatar");
  const chatName = document.getElementById("chat-name");
  const chatStatus = document.getElementById("chat-status");
  const chatStatusText = document.getElementById("chat-status-text");
  const msgSearch = document.getElementById("msg-search");
  const msgSearchInput = document.getElementById("msg-search-input");
  const msgSearchBtn = document.getElementById("msg-search-btn");
  const msgSearchClear = document.getElementById("msg-search-clear");
  const attachBtn = document.getElementById("attach-btn");
  const imgInput = document.getElementById("img-input");
  const msgPreview = document.getElementById("msg-preview");
  const previewImg = document.getElementById("preview-img");
  const previewRemove = document.getElementById("preview-remove");
  const unreadTotal = document.getElementById("unread-total");
  const notifBtn = document.getElementById("notif-btn");
  const themeBtn = document.getElementById("theme-btn");
  const userMenuBtn = document.getElementById("user-menu-btn");
  const userDropdown = document.getElementById("user-dropdown");
  const userAvatar = document.getElementById("user-avatar");
  const dropdownThemeBtn = document.getElementById("dropdown-theme-btn");
  const composer = document.getElementById("composer");
  const blockPanel = document.getElementById("block-panel");
  const blockUnblockBtn = document.getElementById("block-panel-unblock-btn");
  const blockDeleteBtn = document.getElementById("block-panel-delete-btn");
  const chatBlockedFlag = document.getElementById("chat-blocked-flag");
  const restrictedPanel = document.getElementById("restricted-panel");
  const detailsEl = document.getElementById("details");
  const restrictedProfile = document.getElementById("restricted-profile");
  const profileHeader = document.getElementById("profile-header");

  let currentId = null;
  let query = "";
  let msgQuery = "";
  // Selected image waiting to be sent: { file, url (object URL) }.
  let pendingImage = null;
  // Whether desktop notifications are on (persisted per user in localStorage).
  let notifEnabled = localStorage.getItem("syncchat:notify") !== "off";
  const baseTitle = document.title;

  const userById = (id) => users.find((u) => u.id === id);
  const avatarStyle = (i) => `background:${AVATARS[i % AVATARS.length].bg};color:${AVATARS[i % AVATARS.length].fg}`;
  const current = () => userById(currentId);

  // Render an avatar (image if set, otherwise initials on a colored circle).
  function avatarHtml(u, cls) {
    if (u.blockedMe) {
      // A user who blocked us is anonymous: neutral gray person icon, no
      // initials, no identity cues.
      return `<span class="${cls} default-avatar">` +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
        '<circle cx="12" cy="7" r="4"/>' +
        '<path d="M5.5 21a6.5 6.5 0 0 1 13 0"/>' +
        "</svg></span>";
    }
    if (u.avatar) {
      return `<span class="${cls}" style="background-image:url('${esc(u.avatar)}');background-size:cover;background-position:center"></span>`;
    }
    return `<span class="${cls}" style="${avatarStyle(u.id - 1)}">${initials(u.name)}</span>`;
  }

  /* ---------- Block / Restricted composer states ---------- */
  // Three states, mirroring how the composer area is replaced:
  //   blockedByMe → Instagram-style Unblock/Delete panel.
  //   blockedMe    → restricted panel ("You cannot message this user").
  //   normal       → the regular composer.
  function updateComposerForBlock() {
    const u = current();
    if (!u || !composer) return;

    const blockedByMe = !!u.blockedByMe;
    const blockedMe = !!u.blockedMe;

    composer.classList.toggle("blocked", blockedByMe || blockedMe);
    if (blockPanel) blockPanel.hidden = !blockedByMe;
    if (restrictedPanel) restrictedPanel.hidden = !blockedMe;

    // Header: the "Blocked" flag shows only to the blocker. The blocked user
    // sees an anonymous header rendered by renderChat().
    if (chatBlockedFlag) chatBlockedFlag.hidden = !blockedByMe;
    if (chatStatus) chatStatus.hidden = blockedByMe || blockedMe;

    updateSend();
  }

  // Unblock from the block panel: remove the relationship, restore the composer
  // and header immediately, and refresh the list without reloading the page.
  function handleUnblock(u) {
    if (!u || !u.userId || !blockUnblockBtn) return;
    const originalLabel = blockUnblockBtn.textContent;
    blockUnblockBtn.disabled = true;
    blockUnblockBtn.textContent = "Unblocking...";

    fetch(`/chat/users/${u.userId}/unblock/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      credentials: "same-origin"
    })
      .then((res) => {
        if (res.ok) return res.json();
        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
          return res.json().then((d) => Promise.reject(new Error(d.error || "Failed to unblock user.")));
        }
        return Promise.reject(new Error(`Failed to unblock user (${res.status})`));
      })
      .then(() => {
        u.blockedByMe = false;
        renderList();
        updateComposerForBlock();
        renderDetails();
        blockUnblockBtn.disabled = false;
        blockUnblockBtn.textContent = originalLabel;
      })
      .catch((err) => {
        alert(err.message);
        blockUnblockBtn.disabled = false;
        blockUnblockBtn.textContent = originalLabel;
      });
  }

  if (blockUnblockBtn) {
    blockUnblockBtn.addEventListener("click", () => {
      const u = current();
      if (u) handleUnblock(u);
    });
  }

  // Re-fetch a conversation and re-render, used when the block relationship
  // changes so both sides reflect the new state without a page reload.
  function refreshConversation(conversationId) {
    if (!conversationId) return;
    fetch(`/chat/conversations/${conversationId}/detail/`, {
      method: "GET",
      credentials: "same-origin"
    })
      .then((res) => {
        if (res.ok) return res.json();
        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
          return res.json().then((d) => Promise.reject(new Error(d.error || "Failed to refresh conversation.")));
        }
        return Promise.reject(new Error(`Failed to refresh conversation (${res.status})`));
      })
      .then((data) => {
        const conv = data && data.conversation;
        if (!conv) return;
        const idx = users.findIndex((x) => x.id === conv.id);
        if (idx !== -1) users[idx] = conv;
        else users.push(conv);

        const active = currentId === conv.id;
        renderList();
        if (active) {
          renderChat();
          renderDetails();
          updateComposerForBlock();
        }
        updateUnread();
      })
      .catch(() => {
        /* Keep the current view on transient refresh failures. */
      });
  }

  /* ---------- Conversations list ---------- */
  // Escape HTML and highlight matching text.
  function highlightMatch(text, query) {
    if (!query) return esc(text);
    const escaped = esc(text);
    const lowerText = text.toLowerCase();
    const lowerQuery = query.toLowerCase();
    const index = lowerText.indexOf(lowerQuery);
    if (index === -1) return escaped;

    const before = esc(text.substring(0, index));
    const match = esc(text.substring(index, index + query.length));
    const after = esc(text.substring(index + query.length));
    return `${before}<mark class="search-highlight">${match}</mark>${after}`;
  }

  // Render the sidebar: conversations sorted by last activity, filtered by the
  // search query (matches username, full name, or last message), newest activity first, with unread badges.
  function renderList() {
    const q = query.toLowerCase();
    const list = users
      .slice()
      .sort((a, b) => b.ts - a.ts)
      .filter((u) => {
        if (!q) return true;
        return (
          u.name.toLowerCase().includes(q) ||
          u.username.toLowerCase().includes(q) ||
          u.lastMessage.toLowerCase().includes(q)
        );
      });

    if (!list.length) {
      convoList.innerHTML = '<div class="empty-list">No conversations found.</div>';
      return;
    }

    convoList.innerHTML = list.map((u) => {
      const active = u.id === currentId ? " active" : "";
      const badge = u.unread > 0 ? `<span class="badge">${u.unread > 9 ? "9+" : u.unread}</span>` : "";
      // Only the blocker sees the badge; the blocked user never learns they
      // were blocked (Instagram behavior).
      const blockedBadge = u.blockedByMe ? '<span class="blocked-badge">Blocked</span>' : "";
      const nameHtml = highlightMatch(u.name, query);
      const previewHtml = highlightMatch(u.lastMessage, query);
      return `
        <button class="convo-item${active}" role="listitem" data-id="${u.id}">
          ${avatarHtml(u, "avatar")}
          <span class="convo-body">
            <span class="convo-top">
              <span class="name">${nameHtml}${blockedBadge}</span>
              <span class="time">${u.ts ? fmtListTime(u.ts) : esc(u.time)}</span>
            </span>
            <span class="convo-bottom">
              <span class="preview">${previewHtml}</span>
              ${badge}
            </span>
          </span>
        </button>`;
    }).join("");
  }

  /* ---------- Chat window ---------- */
  let typingState = false;
  let typingClearTimer = null;

  // Show typing or online/offline in the chat header status line.
  function setStatusLine(u) {
    if (typingState) {
      chatStatus.classList.add("typing");
      chatStatusText.textContent = `${u.name} is typing...`;
      return;
    }
    chatStatus.classList.remove("typing");
    chatStatusText.textContent = u.online ? "Online" : "Offline";
  }

  // Format an ISO timestamp as a human "Last seen" label.
  function lastSeenLabel(iso) {
    if (!iso) return "Offline";
    const then = new Date(iso);
    if (isNaN(then.getTime())) return "Offline";
    const diffMin = Math.round((Date.now() - then.getTime()) / 60000);
    if (diffMin < 1) return "Last seen just now";
    if (diffMin < 60) return `Last seen ${diffMin} min ago`;
    const diffH = Math.round(diffMin / 60);
    if (diffH < 24 && then.toDateString() === new Date().toDateString()) {
      return `Last seen today at ${then.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
    }
    if (diffH < 24) return `Last seen ${diffH} hr ago`;
    return `Last seen ${then.toLocaleDateString([], { month: "short", day: "numeric" })}`;
  }

  // Format a join date (ISO string or date object) as "Month YYYY".
  function formatJoined(value) {
    const d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString([], { month: "long", year: "numeric" });
  }

  // Format a date as a separator label (e.g., "Today", "Yesterday", "Jan 15").
  function dateSeparator(timestamp) {
    if (!timestamp) return "";
    const date = new Date(timestamp);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (date.toDateString() === today.toDateString()) {
      return "Today";
    }
    if (date.toDateString() === yesterday.toDateString()) {
      return "Yesterday";
    }
    if (today - date < 7 * 24 * 60 * 60 * 1000) {
      return date.toLocaleDateString([], { weekday: "long" });
    }
    return date.toLocaleDateString([], { month: "short", day: "numeric", year: today.getFullYear() !== date.getFullYear() ? "numeric" : undefined });
  }

  // Check if two timestamps are on different days.
  function isDifferentDay(ts1, ts2) {
    if (!ts1 || !ts2) return true;
    const d1 = new Date(ts1);
    const d2 = new Date(ts2);
    return d1.toDateString() !== d2.toDateString();
  }

  // Format a message timestamp in the browser's local timezone. The server
  // also sends pre-formatted labels, but they are in the server's timezone
  // (UTC), so raw timestamps are preferred whenever available.
  function fmtTime(ts) {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  // Sidebar "time" column label for a conversation (epoch seconds).
  function fmtListTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    if (isNaN(d.getTime())) return "";
    const today = new Date();
    const start = new Date(d);
    start.setHours(0, 0, 0, 0);
    today.setHours(0, 0, 0, 0);
    const dayDiff = Math.round((today - start) / (24 * 60 * 60 * 1000));
    if (dayDiff === 0) return fmtTime(d);
    if (dayDiff === 1) return "Yesterday";
    if (dayDiff < 7) return d.toLocaleDateString([], { weekday: "short" });
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  // Render the message thread and header for the currently selected chat.
  // When scrollToBottom is false (loading older messages) the existing
  // scroll position is preserved by the caller.
  function renderChat(scrollToBottom) {
    const u = current();
    if (!u) return;

    // Privacy: a user who blocked us is shown anonymously. No avatar, no
    // name, no status, no typing — the history is unavailable as well.
    if (u.blockedMe) {
      chatAvatar.classList.add("default-avatar");
      chatAvatar.style.cssText = "";
      chatAvatar.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="7" r="4"/><path d="M5.5 21a6.5 6.5 0 0 1 13 0"/></svg>';
      chatName.textContent = "Unknown User";
      chatStatus.classList.remove("offline", "typing");
      chatStatus.hidden = true;
      chatBody.innerHTML =
        '<div class="restricted-chat-body"><div class="restricted-chat-icon">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>' +
        '</div><span>This conversation is unavailable.</span></div>';
      if (scrollToBottom !== false) forceScrollChat();
      return;
    }
    chatAvatar.classList.remove("default-avatar");
    if (u.avatar) {
      chatAvatar.style.background = `url("${u.avatar}") center/cover no-repeat`;
      chatAvatar.innerHTML = "";
    } else {
      chatAvatar.innerHTML = initials(u.name);
      chatAvatar.style.cssText = avatarStyle(u.id - 1);
    }
    chatName.textContent = u.name;
    chatStatus.classList.toggle("offline", !u.online);
    setStatusLine(u);

    // Apply the active message search query if any, showing only matches.
    const needle = msgQuery.trim().toLowerCase();
    const visible = needle
      ? u.messages.filter((m) => m.text.toLowerCase().includes(needle))
      : u.messages;
    if (needle && !visible.length) {
      chatBody.innerHTML = '<div class="empty-list">No matching messages.</div>';
      forceScrollChat();
      return;
    }

    // A message with an image gets a framed card with an optional caption.
    const bubbleFor = (m) => {
      if (!m.image) return `<div class="bubble">${esc(m.text)}</div>`;
      const caption = m.text ? `<span class="img-caption">${esc(m.text)}</span>` : "";
      return `<div class="bubble bubble-img"><img class="msg-img" src="${esc(m.image)}" alt="Shared image" loading="lazy" />${caption}</div>`;
    };

    // Fetch older history on demand; the server returns messages before the
    // oldest one currently loaded.
    const loadEarlier = u.hasMore && !needle
      ? '<button class="load-earlier" id="load-earlier" type="button">Load earlier messages</button>'
      : "";

    // Build messages with date separators.
    let html = loadEarlier;
    let lastDate = null;

    visible.forEach((m, idx) => {
      const msgDate = m.created_at || m.timestamp || Date.now();
      if (idx === 0 || isDifferentDay(lastDate, msgDate)) {
        html += `<div class="date-separator"><span>${dateSeparator(msgDate)}</span></div>`;
      }
      lastDate = msgDate;

      html += `
        <div class="msg ${m.from === "me" ? "sent" : "received"}">
          ${bubbleFor(m)}
          <span class="time">${esc(m.created_at ? fmtTime(m.created_at) : m.time)}${m.from === "me" && m.read ? '<span class="read-state">Seen</span>' : ""}</span>
        </div>`;
    });

    // Add typing indicator if the other user is typing.
    if (typingState) {
      html += `
        <div class="msg received typing-indicator-msg">
          <div class="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
          </div>
        </div>`;
    }

    chatBody.innerHTML = html;
    if (scrollToBottom !== false) forceScrollChat();
    else scrollChat();
  }

  // Render the right-hand contact details panel for the current chat.
  function renderDetails() {
    const u = current();
    if (!u) return;

    // Privacy: a user who blocked us is shown as a restricted, anonymous
    // profile. No avatar, no name, no bio, no media, no actions.
    if (u.blockedMe) {
      if (detailsEl) detailsEl.classList.add("restricted");
      if (restrictedProfile) restrictedProfile.hidden = false;
      return;
    }
    if (detailsEl) detailsEl.classList.remove("restricted");
    if (restrictedProfile) restrictedProfile.hidden = true;
    if (profileHeader) profileHeader.hidden = false;

    const pa = document.getElementById("profile-avatar");
    if (u.avatar) {
      pa.style.background = `url("${u.avatar}") center/cover no-repeat`;
      pa.innerHTML = "";
    } else {
      pa.innerHTML = initials(u.name);
      pa.style.cssText = avatarStyle(u.id - 1);
    }
    document.getElementById("profile-name").textContent = u.name;
    document.getElementById("profile-handle").textContent = u.handle;
    document.getElementById("profile-status").textContent = u.online ? "Online" : lastSeenLabel(u.last_seen);

    // Online/offline badge in the profile header.
    const statusBadge = document.getElementById("profile-status-badge");
    const statusBadgeText = document.getElementById("profile-status-text");
    statusBadge.classList.toggle("online", u.online);
    statusBadgeText.textContent = u.online ? "Online" : "Offline";

    // Mute button label and state reflect the persisted mute flag.
    const muted = !!u.muted;
    if (muteBtn) {
      muteBtn.classList.toggle("is-muted", muted);
      muteBtn.setAttribute("aria-pressed", String(muted));
      muteBtn.setAttribute("aria-label", muted ? "Unmute notifications" : "Mute notifications");
    }
    const muteLabel = document.getElementById("mute-btn-label");
    if (muteLabel) muteLabel.textContent = muted ? "Unmute" : "Mute";

    // Bio section
    const bioSection = document.getElementById("bio-section");
    const bioValue = document.getElementById("profile-bio");
    if (u.bio && u.bio.trim()) {
      bioValue.textContent = u.bio;
      bioSection.hidden = false;
    } else {
      bioSection.hidden = true;
    }

    // Phone section
    const phoneSection = document.getElementById("phone-section");
    const phoneValue = document.getElementById("profile-phone");
    if (u.phone && u.phone.trim()) {
      phoneValue.textContent = u.phone;
      phoneSection.hidden = false;
    } else {
      phoneSection.hidden = true;
    }

    // Email section
    const emailSection = document.getElementById("email-section");
    const emailValue = document.getElementById("profile-email");
    if (u.email && u.email.trim()) {
      emailValue.textContent = u.email;
      emailSection.hidden = false;
    } else {
      emailSection.hidden = true;
    }

    // Joined section
    const joinedSection = document.getElementById("joined-section");
    const joinedValue = document.getElementById("profile-joined");
    if (u.joined) {
      joinedValue.textContent = formatJoined(u.joined);
      joinedSection.hidden = false;
    } else {
      joinedSection.hidden = true;
    }

    // Media section
    const mediaSection = document.getElementById("media-section");
    const mediaCountEl = document.getElementById("media-count");
    const mediaViewAll = document.getElementById("media-view-all");
    const grid = document.getElementById("media-grid");
    const images = u.media || [];

    if (u.mediaCount > 0) {
      mediaCountEl.textContent = u.mediaCount;
      mediaSection.hidden = false;

      // Show at most 6 thumbnails. A "View All" button appears when there
      // are more than 6 (gallery preview not implemented yet).
      const shown = images.slice(0, 6);
      if (shown.length) {
        grid.innerHTML = shown.map((url) => `
          <img class="media-thumb" src="${esc(url)}" alt="Shared image" loading="lazy" />`).join("");
      } else {
        grid.innerHTML = `<span class="media-thumb media-more">${u.mediaCount}</span>`;
      }
      const hasMore = u.mediaCount > 6;
      mediaViewAll.hidden = !hasMore;
      mediaCountEl.hidden = hasMore;
    } else {
      mediaSection.hidden = true;
    }

    // Files and Links sections remain hidden (no data yet)
    document.getElementById("files-section").hidden = true;
    document.getElementById("links-section").hidden = true;
  }

  // Open a conversation: connect the WebSocket, mark it read, clear the unread
  // badge, and re-render all panels.
  function select(id) {
    currentId = id;
    const u = userById(id);
    if (!u) return;
    typingState = false;
    if (typingClearTimer) {
      clearTimeout(typingClearTimer);
      typingClearTimer = null;
    }
    // Reset any active message search when switching conversations.
    msgQuery = "";
    msgSearchInput.value = "";
    msgSearch.hidden = true;
    removePendingImage();
    u.unread = 0;
    app.dataset.conversationId = id;
    if (window.SyncChatSocket) window.SyncChatSocket.connect(id);
    markRead(id);
    renderList();
    renderChat();
    renderDetails();
    updateComposerForBlock();
    updateUnread();
    if (window.innerWidth <= 860) {
      app.classList.remove("list-open");
      app.classList.add("chat-open");
    }
  }

  // Keep the thread scrolled to the newest message, but only if the user
  // is already near the bottom (within 150px). This prevents interrupting
  // users who are reading older messages.
  function scrollChat() {
    const isNearBottom = chatBody.scrollHeight - chatBody.scrollTop - chatBody.clientHeight < 150;
    if (isNearBottom) {
      chatBody.scrollTop = chatBody.scrollHeight;
    }
  }

  // Force scroll to bottom (used when switching conversations or sending).
  function forceScrollChat() {
    chatBody.scrollTop = chatBody.scrollHeight;
  }

  /* ---------- Reading ---------- */
  // Read a cookie value (used for the CSRF token).
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  // Tell the server the conversation was viewed so it marks messages as read.
  function markRead(id) {
    // Privacy: opening a blocked conversation never signals read receipts to
    // the blocker, so they can't tell the blocked user opened the chat.
    const u = userById(id);
    if (u && u.blockedMe) return;
    fetch(`/chat/conversations/${id}/read/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      credentials: "same-origin"
    }).catch(() => {});
  }

  /* ---------- Unread badge & notifications ---------- */
  // Refresh the total-unread badge and the document title from all chats.
  function updateUnread() {
    const total = users.reduce((s, u) => s + (u.unread || 0), 0);
    if (total > 0) {
      unreadTotal.textContent = total > 99 ? "99+" : String(total);
      unreadTotal.hidden = false;
      document.title = `(${total}) ${baseTitle}`;
    } else {
      unreadTotal.hidden = true;
      document.title = baseTitle;
    }
  }

  const notificationsSupported = () => "Notification" in window;

  // Reflect the notification preference in the bell button's active state.
  function renderNotifState() {
    const on = notifEnabled && notificationsSupported() && Notification.permission === "granted";
    notifBtn.classList.toggle("on", on);
    notifBtn.setAttribute("aria-pressed", String(on));
    const label = on ? "Disable notifications" : "Enable notifications";
    notifBtn.setAttribute("aria-label", label);
    notifBtn.title = label;
  }

  // Toggle desktop notifications, requesting permission on first enable.
  function toggleNotifications() {
    if (!notificationsSupported()) {
      alert("This browser does not support notifications.");
      return;
    }
    if (Notification.permission === "denied") {
      alert("Notifications are blocked. Allow them in your browser settings.");
      return;
    }
    if (Notification.permission === "granted") {
      notifEnabled = !notifEnabled;
      localStorage.setItem("syncchat:notify", notifEnabled ? "on" : "off");
      renderNotifState();
      return;
    }
    Notification.requestPermission().then((permission) => {
      notifEnabled = permission === "granted";
      localStorage.setItem("syncchat:notify", notifEnabled ? "on" : "off");
      renderNotifState();
    });
  }

  // Per-type notification preferences set on the Settings page (localStorage,
  // default on when the key is absent).
  const notifyPref = (kind) => localStorage.getItem(`syncchat:notify:${kind}`) !== "off";

  // Show a desktop notification for an incoming message, but only when the
  // page is in the background so the live chat is not interrupted.
  function notifyIncoming(data) {
    // "Message" is the master switch for incoming-message alerts.
    if (!notifyPref("message")) return;
    if (!notifEnabled || !notificationsSupported() || Notification.permission !== "granted") return;
    if (!document.hidden && currentId === Number(data.conversation_id)) return;
    // "Desktop" gates the OS notification; "Sound" silences it when off.
    if (!notifyPref("desktop")) return;
    const u = users.find((x) => x.id === Number(data.conversation_id));
    const title = u ? u.name : data.sender;
    const body = data.image ? "Shared a photo" : (data.content || "New message");
    const n = new Notification(title, { body, tag: `chat-${data.conversation_id}`, silent: !notifyPref("sound") });
    n.onclick = () => {
      window.focus();
      if (u && currentId !== u.id) select(u.id);
    };
  }

  notifBtn.addEventListener("click", toggleNotifications);

  /* ---------- Dark mode ---------- */
  // Theme is owned by the shared SyncChatTheme module (base.html loads
  // theme.js). Here we just wire the dashboard's sun/moon button and the
  // dropdown item to it, and keep the button's accessible label in sync.
  function labelButton(resolved) {
    const label = resolved === "dark" ? "Switch to light mode" : "Switch to dark mode";
    themeBtn.setAttribute("aria-label", label);
    themeBtn.title = label;
  }

  function syncThemeIcon() {
    labelButton(SyncChatTheme.getResolved());
  }

  syncThemeIcon();
  document.addEventListener("syncchat:themechange", syncThemeIcon);

  themeBtn.addEventListener("click", () => SyncChatTheme.toggle());

  /* ---------- User Menu Dropdown ---------- */
  // Toggle the user dropdown menu.
  function toggleUserMenu() {
    const isOpen = !userDropdown.hidden;
    userDropdown.hidden = isOpen;
    userMenuBtn.setAttribute("aria-expanded", String(!isOpen));
  }

  // Close the dropdown when clicking outside.
  function closeUserMenu(e) {
    if (!userDropdown.hidden && !userDropdown.contains(e.target) && !userMenuBtn.contains(e.target)) {
      userDropdown.hidden = true;
      userMenuBtn.setAttribute("aria-expanded", "false");
    }
  }

  // Initialize the current user's avatar in the sidebar footer. Uses the real
  // avatar/name from me_profile (populated by the dashboard payload) so the
  // footer reflects what other clients see, and updates live on profile events.
  function renderOwnAvatar() {
    if (!me && !meProfile) return;
    const p = meProfile || {};
    if (p.avatar) {
      userAvatar.style.background = `url("${esc(p.avatar)}") center/cover no-repeat`;
      userAvatar.innerHTML = "";
    } else {
      userAvatar.innerHTML = initials(p.name || me);
      userAvatar.style.cssText = avatarStyle((p.id || 0) - 1);
    }
  }

  function initUserAvatar() {
    if (!me && !meProfile) return;
    renderOwnAvatar();
  }

  userMenuBtn.addEventListener("click", toggleUserMenu);
  document.addEventListener("click", closeUserMenu);

  // Theme toggle in dropdown.
  if (dropdownThemeBtn) {
    dropdownThemeBtn.addEventListener("click", () => {
      SyncChatTheme.toggle();
      userDropdown.hidden = true;
      userMenuBtn.setAttribute("aria-expanded", "false");
    });
  }

  // Close dropdown when pressing Escape.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !userDropdown.hidden) {
      userDropdown.hidden = true;
      userMenuBtn.setAttribute("aria-expanded", "false");
    }
  });

  /* ---------- Profile Action Buttons ---------- */
  const muteBtn = document.getElementById("mute-btn");
  const blockBtn = document.getElementById("block-btn");
  const deleteConversationBtn = document.getElementById("delete-conversation-btn");

  // Toggle mute for this conversation; the backend persists the state and the
  // button label updates to "Mute" / "Unmute" accordingly.
  if (muteBtn) {
    muteBtn.addEventListener("click", () => {
      const u = current();
      if (!u) return;
      fetch(`/chat/conversations/${u.id}/mute/`, {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken") },
        credentials: "same-origin"
      })
        .then((res) => (res.ok ? res.json() : Promise.reject(new Error("Failed to update mute."))))
        .then((data) => {
          u.muted = data.muted;
          renderDetails();
        })
        .catch((err) => alert(err.message));
    });
  }

  // Block user: confirm via modal, then block through the backend. Once the
  // block is stored the conversation is hidden, so reload to refresh the list.
  const blockModal = document.getElementById("block-modal");
  const blockModalText = document.getElementById("block-modal-text");
  const blockCancelBtn = document.getElementById("block-cancel-btn");
  const blockConfirmBtn = document.getElementById("block-confirm-btn");
  let blockTarget = null;

  const closeBlockModal = () => {
    blockModal.hidden = true;
    blockTarget = null;
    blockConfirmBtn.disabled = false;
    blockConfirmBtn.textContent = "Block";
  };

  if (blockBtn && blockModal) {
    blockBtn.addEventListener("click", () => {
      const u = current();
      if (!u) return;
      blockTarget = u;
      blockModalText.textContent =
        `Block ${u.name} (${u.handle})? You will not be able to send or ` +
        `receive messages from this user, and the conversation will be hidden.`;
      blockModal.hidden = false;
    });

    blockCancelBtn.addEventListener("click", closeBlockModal);
    blockModal.addEventListener("click", (e) => {
      if (e.target === blockModal) closeBlockModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !blockModal.hidden) closeBlockModal();
    });

    blockConfirmBtn.addEventListener("click", () => {
      const u = blockTarget;
      if (!u) return;
      blockConfirmBtn.disabled = true;
      blockConfirmBtn.textContent = "Blocking...";
      fetch(`/chat/users/${u.userId}/block/`, {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken") },
        credentials: "same-origin"
      })
        .then((res) => {
          if (res.ok) {
            return res.json();
          }
          // Check if response is JSON before trying to parse it
          const contentType = res.headers.get("content-type");
          if (contentType && contentType.includes("application/json")) {
            return res.json().then((d) => Promise.reject(new Error(d.error || "Failed to block user.")));
          }
          // Non-JSON error (404, 500, etc.)
          return Promise.reject(new Error(`Failed to block user (${res.status})`));
        })
        .then(() => {
          // Update local state instead of reloading
          u.blockedByMe = true;
          closeBlockModal();
          renderList();
          updateComposerForBlock();
          renderDetails();
        })
        .catch((err) => {
          alert(err.message);
          closeBlockModal();
        });
    });
  }

  // Delete conversation: confirm via modal, then soft-delete through the
  // backend. Only the current user's view is removed — messages and the other
  // user's conversation stay intact, and a future message (e.g. after an
  // unblock) brings the conversation back.
  const deleteModal = document.getElementById("delete-modal");
  const deleteModalText = document.getElementById("delete-modal-text");
  const deleteCancelBtn = document.getElementById("delete-cancel-btn");
  const deleteConfirmBtn = document.getElementById("delete-confirm-btn");
  let deleteTarget = null;

  const closeDeleteModal = () => {
    deleteModal.hidden = true;
    deleteTarget = null;
    deleteConfirmBtn.disabled = false;
    deleteConfirmBtn.textContent = "Delete";
  };

  // Clear the chat pane back to its empty state when the active conversation
  // is removed locally.
  function resetChatView() {
    currentId = null;
    chatName.textContent = "";
    chatStatus.classList.remove("offline", "typing");
    chatStatus.hidden = false;
    chatStatusText.textContent = "Offline";
    if (chatBlockedFlag) chatBlockedFlag.hidden = true;
    if (composer) composer.classList.remove("blocked");
    msgInput.value = "";
    msgInput.disabled = false;
    attachBtn.disabled = false;
    removePendingImage();
    chatBody.innerHTML = '<div class="empty-list">No conversation selected.</div>';
    app.classList.remove("details-open");
  }

  const openDeleteModalFor = (u) => {
    if (!u) return;
    deleteTarget = u;
    deleteModalText.textContent =
      `Delete the conversation with ${u.name}? This only removes it for you — ` +
      `the other person keeps the conversation and messages.`;
    deleteModal.hidden = false;
  };

  if (deleteConversationBtn && deleteModal) {
    deleteConversationBtn.addEventListener("click", () => {
      openDeleteModalFor(current());
    });

    // The Instagram-style block panel's "Delete Chat" button reuses the same
    // confirmation modal.
    if (blockDeleteBtn) {
      blockDeleteBtn.addEventListener("click", () => {
        openDeleteModalFor(current());
      });
    }

    deleteCancelBtn.addEventListener("click", closeDeleteModal);
    deleteModal.addEventListener("click", (e) => {
      if (e.target === deleteModal) closeDeleteModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !deleteModal.hidden) closeDeleteModal();
    });

    deleteConfirmBtn.addEventListener("click", () => {
      const u = deleteTarget;
      if (!u) return;
      deleteConfirmBtn.disabled = true;
      deleteConfirmBtn.textContent = "Deleting...";
      fetch(`/chat/conversations/${u.id}/delete/`, {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken") },
        credentials: "same-origin"
      })
        .then((res) => {
          if (res.ok) {
            return res.json();
          }
          // Check if response is JSON before trying to parse it
          const contentType = res.headers.get("content-type");
          if (contentType && contentType.includes("application/json")) {
            return res.json().then((d) => Promise.reject(new Error(d.error || "Failed to delete conversation.")));
          }
          // Non-JSON error (404, 500, etc.)
          return Promise.reject(new Error(`Failed to delete conversation (${res.status})`));
        })
        .then(() => {
          // Remove the conversation locally and reset the chat pane without a
          // reload. Only the current user's view is affected.
          const idx = users.findIndex((x) => x.id === u.id);
          if (idx !== -1) users.splice(idx, 1);
          closeDeleteModal();
          if (currentId === u.id) resetChatView();
          renderList();
          updateUnread();
          // If a socket is open for the deleted chat, disconnect it.
          if (window.SyncChatSocket) window.SyncChatSocket.disconnect();
        })
        .catch((err) => {
          alert(err.message);
          closeDeleteModal();
        });
    });
  }

  /* ---------- Image Viewer Modal ---------- */
  const imageViewer = document.getElementById("image-viewer");
  const imageViewerImg = document.getElementById("image-viewer-img");
  const imageCloseBtn = document.getElementById("image-close-btn");
  const imagePrevBtn = document.getElementById("image-prev-btn");
  const imageNextBtn = document.getElementById("image-next-btn");
  const imageZoomInBtn = document.getElementById("image-zoom-in-btn");
  const imageZoomOutBtn = document.getElementById("image-zoom-out-btn");
  const imageResetBtn = document.getElementById("image-reset-btn");
  const imageZoomLevel = document.getElementById("image-zoom-level");
  const imageCounter = document.getElementById("image-counter");
  const imageCurrent = document.getElementById("image-current");
  const imageTotal = document.getElementById("image-total");

  let currentImageIndex = 0;
  let imageList = [];
  let imageZoom = 1;
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let scrollStartX = 0;
  let scrollStartY = 0;

  // Collect all images from the current conversation.
  function getConversationImages() {
    const u = current();
    if (!u) return [];
    return u.messages
      .filter((m) => m.image)
      .map((m) => m.image);
  }

  // Open image viewer with the clicked image.
  function openImageViewer(imageSrc) {
    imageList = getConversationImages();
    currentImageIndex = imageList.indexOf(imageSrc);
    if (currentImageIndex === -1) {
      imageList = [imageSrc];
      currentImageIndex = 0;
    }
    showImage(currentImageIndex);
    imageViewer.hidden = false;
    document.body.style.overflow = "hidden";
  }

  // Close image viewer.
  function closeImageViewer() {
    imageViewer.hidden = true;
    document.body.style.overflow = "";
    resetZoom();
  }

  // Show image at the given index.
  function showImage(index) {
    if (index < 0 || index >= imageList.length) return;
    currentImageIndex = index;
    imageViewerImg.src = imageList[index];
    resetZoom();

    // Update counter.
    if (imageList.length > 1) {
      imageCurrent.textContent = index + 1;
      imageTotal.textContent = imageList.length;
      imageCounter.hidden = false;
      imagePrevBtn.hidden = false;
      imageNextBtn.hidden = false;
    } else {
      imageCounter.hidden = true;
      imagePrevBtn.hidden = true;
      imageNextBtn.hidden = true;
    }
  }

  // Navigate to previous image.
  function prevImage() {
    if (currentImageIndex > 0) {
      showImage(currentImageIndex - 1);
    }
  }

  // Navigate to next image.
  function nextImage() {
    if (currentImageIndex < imageList.length - 1) {
      showImage(currentImageIndex + 1);
    }
  }

  // Zoom in.
  function zoomIn() {
    imageZoom = Math.min(imageZoom + 0.25, 3);
    applyZoom();
  }

  // Zoom out.
  function zoomOut() {
    imageZoom = Math.max(imageZoom - 0.25, 0.5);
    applyZoom();
  }

  // Reset zoom to 100%.
  function resetZoom() {
    imageZoom = 1;
    applyZoom();
  }

  // Apply zoom transformation.
  function applyZoom() {
    imageViewerImg.style.transform = `scale(${imageZoom})`;
    imageZoomLevel.textContent = `${Math.round(imageZoom * 100)}%`;
  }

  // Image viewer event handlers.
  imageCloseBtn.addEventListener("click", closeImageViewer);
  imagePrevBtn.addEventListener("click", prevImage);
  imageNextBtn.addEventListener("click", nextImage);
  imageZoomInBtn.addEventListener("click", zoomIn);
  imageZoomOutBtn.addEventListener("click", zoomOut);
  imageResetBtn.addEventListener("click", resetZoom);

  // Click on background to close.
  imageViewer.addEventListener("click", (e) => {
    if (e.target === imageViewer || e.target.classList.contains("image-viewer-body")) {
      closeImageViewer();
    }
  });

  // Keyboard navigation.
  document.addEventListener("keydown", (e) => {
    if (imageViewer.hidden) return;

    if (e.key === "Escape") {
      closeImageViewer();
    } else if (e.key === "ArrowLeft") {
      prevImage();
    } else if (e.key === "ArrowRight") {
      nextImage();
    } else if (e.key === "+" || e.key === "=") {
      zoomIn();
    } else if (e.key === "-" || e.key === "_") {
      zoomOut();
    } else if (e.key === "0") {
      resetZoom();
    }
  });

  // Mouse wheel zoom.
  imageViewerImg.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (e.deltaY < 0) {
      zoomIn();
    } else {
      zoomOut();
    }
  });

  // Drag to pan when zoomed.
  const imageViewerContent = document.querySelector(".image-viewer-content");
  imageViewerContent.addEventListener("mousedown", (e) => {
    if (imageZoom <= 1) return;
    isDragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    scrollStartX = imageViewerContent.scrollLeft;
    scrollStartY = imageViewerContent.scrollTop;
    imageViewerContent.classList.add("dragging");
  });

  document.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    imageViewerContent.scrollLeft = scrollStartX - dx;
    imageViewerContent.scrollTop = scrollStartY - dy;
  });

  document.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      imageViewerContent.classList.remove("dragging");
    }
  });

  // Touch support for mobile.
  let touchStartX = 0;
  let touchStartY = 0;
  let touchStartDist = 0;
  let touchZoomStart = 1;

  imageViewerContent.addEventListener("touchstart", (e) => {
    if (e.touches.length === 1) {
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
      scrollStartX = imageViewerContent.scrollLeft;
      scrollStartY = imageViewerContent.scrollTop;
    } else if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      touchStartDist = Math.sqrt(dx * dx + dy * dy);
      touchZoomStart = imageZoom;
    }
  });

  imageViewerContent.addEventListener("touchmove", (e) => {
    if (e.touches.length === 1 && imageZoom > 1) {
      e.preventDefault();
      const dx = e.touches[0].clientX - touchStartX;
      const dy = e.touches[0].clientY - touchStartY;
      imageViewerContent.scrollLeft = scrollStartX - dx;
      imageViewerContent.scrollTop = scrollStartY - dy;
    } else if (e.touches.length === 2) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const scale = dist / touchStartDist;
      imageZoom = Math.min(Math.max(touchZoomStart * scale, 0.5), 3);
      applyZoom();
    }
  });

  // Click on images in chat to open viewer.
  chatBody.addEventListener("click", (e) => {
    const img = e.target.closest(".msg-img, .media-thumb");
    if (img && img.src) {
      openImageViewer(img.src);
    }
  });

  // Click on images in profile panel to open viewer.
  document.addEventListener("click", (e) => {
    if (e.target.matches("#media-grid .media-thumb")) {
      openImageViewer(e.target.src);
    }
  });

  /* ---------- Sending ---------- */
  const nowTime = () => new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  // Sidebar preview text for a message (image-only messages read "Photo").
  const previewLabel = (m) => (m.image && !m.text ? "Photo" : m.text);

  // Upload a message with an attached image over HTTP (multipart/form-data).
  // Text goes over the WebSocket, but binary payloads are sent this way; the
  // server then broadcasts the stored message to the conversation group.
  function sendWithImage(text) {
    const fd = new FormData();
    if (text) fd.append("content", text);
    fd.append("image", pendingImage.file);
    const optimisticUrl = pendingImage.url;
    removePendingImage();
    fetch(`/chat/conversations/${currentId}/messages/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      credentials: "same-origin",
      body: fd
    })
      .then((res) => {
        if (res.ok) return res.json();
        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
          return res.json().then((j) => Promise.reject(new Error(j.error || "Image upload failed.")));
        }
        return Promise.reject(new Error(`Image upload failed (${res.status})`));
      })
      .catch((err) => {
        // Roll back the optimistic message if the upload was rejected.
        const u = current();
        if (u) {
          const i = u.messages.findIndex((m) => m.image === optimisticUrl);
          if (i !== -1) u.messages.splice(i, 1);
          const last = u.messages[u.messages.length - 1];
          u.lastMessage = last ? previewLabel(last) : "No messages yet";
          u.time = last ? last.time : "";
        }
        renderList();
        renderChat();
        alert(err.message);
      });
  }

  // Send the typed message: optimistically render it, then push it over the
  // WebSocket. If no live socket exists, fall back to the HTTP send endpoint.
  function send() {
    const text = msgInput.value.trim();
    const u = current();
    if ((!text && !pendingImage) || !u) return;

    // The composer is replaced in both blocked directions, so this only guards
    // against a stale keystroke or a forged UI. The backend rejects sends with
    // 403 as well, but never optimistically render a message that won't send.
    if (u.blockedByMe || u.blockedMe) return;

    u.messages.push({ from: "me", text, image: pendingImage ? pendingImage.url : null, time: nowTime(), read: false });
    u.lastMessage = text || "Photo";
    u.time = nowTime();
    u.ts = Date.now() / 1000;
    u.unread = 0;
    msgInput.value = "";
    updateSend();
    notifyTyping(false);
    renderList();
    renderChat();
    updateUnread();
    msgInput.focus();
    if (pendingImage) {
      sendWithImage(text);
      return;
    }
    const sentOverSocket = window.SyncChatSocket && window.SyncChatSocket.send(text);
    if (sentOverSocket) return;
    fetch(`/chat/conversations/${currentId}/messages/`, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "Content-Type": "application/x-www-form-urlencoded"
      },
      credentials: "same-origin",
      body: new URLSearchParams({ content: text })
    })
      .then((res) => {
        if (!res.ok) {
          const contentType = res.headers.get("content-type");
          if (contentType && contentType.includes("application/json")) {
            return res.json().then((d) => {
              // Remove optimistic message on error
              const idx = u.messages.findIndex((m) => m.from === "me" && m.text === text && !m.id);
              if (idx !== -1) u.messages.splice(idx, 1);
              renderChat();
              throw new Error(d.error || "Failed to send message.");
            });
          }
          throw new Error(`Failed to send message (${res.status})`);
        }
        return res.json();
      })
      .catch((err) => {
        alert(err.message);
      });
  }

  // Enable/disable the send button based on whether there is text or an
  // attached image to send.
  function updateSend() {
    sendBtn.disabled = !msgInput.value.trim() && !pendingImage;
  }

  /* ---------- Image attach & preview ---------- */
  // Open the file picker; the hidden input triggers the change handler.
  attachBtn.addEventListener("click", () => imgInput.click());

  // Show a preview of the chosen image and hold it until the user sends or
  // removes it. Rejects oversized or non-image files client-side before upload.
  imgInput.addEventListener("change", () => {
    const file = imgInput.files[0];
    imgInput.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      alert("Only image files can be attached.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      alert("Image is too large. Maximum size is 5 MB.");
      return;
    }
    removePendingImage();
    pendingImage = { file, url: URL.createObjectURL(file) };
    previewImg.src = pendingImage.url;
    msgPreview.hidden = false;
    updateSend();
  });

  // Clear the pending image, releasing its object URL.
  function removePendingImage() {
    if (pendingImage) {
      URL.revokeObjectURL(pendingImage.url);
      pendingImage = null;
    }
    previewImg.removeAttribute("src");
    msgPreview.hidden = true;
    updateSend();
  }

  previewRemove.addEventListener("click", removePendingImage);

  let typingOn = false;
  let typingStopTimer = null;

  // Broadcast the typing state over the socket, auto-stopping after 2.5s.
  function notifyTyping(on) {
    if (on === typingOn) {
      if (on && typingStopTimer) {
        clearTimeout(typingStopTimer);
        typingStopTimer = setTimeout(() => notifyTyping(false), 2500);
      }
      return;
    }
    typingOn = on;
    if (typingStopTimer) clearTimeout(typingStopTimer);
    if (on) {
      typingStopTimer = setTimeout(() => notifyTyping(false), 2500);
    } else {
      typingStopTimer = null;
    }
    if (window.SyncChatSocket) window.SyncChatSocket.sendTyping(on);
  }

  msgInput.addEventListener("input", () => {
    updateSend();
    notifyTyping(!!msgInput.value.trim());
  });
  msgInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); send(); }
  });
  sendBtn.addEventListener("click", send);

  /* ---------- Incoming messages ---------- */
  // Receive a message from the other participant in the open chat and re-render.
  window.addEventListener("syncchat:message", (event) => {
    const data = event.detail;
    const u = current();
    if (!u || !data || data.sender === me) return;
    const msg = { from: "them", text: data.content, image: data.image || null, time: nowTime(), created_at: data.created_at };
    u.messages.push(msg);
    u.lastMessage = previewLabel(msg);
    u.time = nowTime();
    u.ts = Date.now() / 1000;
    notifyIncoming(data);
    renderList();
    renderChat();
    updateUnread();
    markRead(currentId);
  });

  /* ---------- New message notifications (from presence socket) ---------- */
  // When a message arrives for a conversation that is NOT the active chat,
  // update the unread badge in the sidebar and fire a desktop notification.
  window.addEventListener("syncchat:new_message", (event) => {
    const data = event.detail;
    if (!data || data.sender === me) return;
    const convId = data.conversation_id;
    const u = users.find((x) => x.id === Number(convId));
    if (u) {
      u.unread = (u.unread || 0) + 1;
      u.lastMessage = data.content || "New message";
      u.time = nowTime();
      u.ts = Date.now() / 1000;
      renderList();
      updateUnread();
    } else {
      refreshConversation(convId);
    }
    notifyIncoming(data);
  });

  /* ---------- Typing indicator ---------- */
  // Show "typing..." in the header while the other participant is typing.
  window.addEventListener("syncchat:typing", (event) => {
    const data = event.detail;
    if (!data || data.username === me) return;
    const u = users.find((x) => x.username === data.username);
    if (!u || currentId !== Number(data.conversation_id)) return;
    // Privacy: no typing indicator while the conversation is blocked.
    if (u.blockedMe || u.blockedByMe) return;
    typingState = !!data.typing;
    if (typingClearTimer) clearTimeout(typingClearTimer);
    if (typingState) {
      typingClearTimer = setTimeout(() => {
        typingState = false;
        renderChat(false);
      }, 4000);
    }
    renderChat(false);
  });

  /* ---------- Read receipts ---------- */
  // Mark my sent messages as seen when the other participant reads them.
  window.addEventListener("syncchat:read", (event) => {
    const data = event.detail;
    if (!data || !data.conversation_id || data.reader === me) return;
    const u = users.find((x) => x.id === Number(data.conversation_id));
    if (!u) return;
    u.messages.forEach((m) => {
      if (m.from === "me") m.read = true;
    });
    if (currentId === u.id) renderChat();
  });

  /* ---------- Block status changes ---------- */
  // When either side blocks or unblocks, both participants re-fetch the
  // conversation so the blocker and blocked user see the correct state.
  window.addEventListener("syncchat:block", (event) => {
    const data = event.detail;
    if (data && data.conversation_id) refreshConversation(data.conversation_id);
  });

  /* ---------- Presence ---------- */
  // Update a contact's online status when the server broadcasts presence.
  window.addEventListener("syncchat:presence", (event) => {
    const data = event.detail;
    if (!data || !data.username) return;
    const u = users.find((x) => x.username === data.username);
    if (!u || u.online === data.online) return;
    // Privacy: never surface presence for a user who blocked us.
    if (u.blockedMe) return;
    u.online = data.online;
    if (!data.online && data.last_seen) u.last_seen = data.last_seen;

    // Update sidebar list instantly.
    renderList();

    // Update chat header and details panel if this is the current chat.
    if (currentId === u.id) {
      chatStatus.classList.toggle("offline", !u.online);
      setStatusLine(u);
      renderDetails();
    }
  });

  /* ---------- Profile updates (name / avatar) ---------- */
  // When the current user or a contact changes their full name or avatar,
  // every open client updates the sidebar, chat header and details panel
  // instantly without a refresh.
  window.addEventListener("syncchat:profile", (event) => {
    const data = event.detail;
    if (!data || !data.username) return;
    const isMe = meProfile && data.user_id === meProfile.id;
    if (isMe) {
      meProfile = {
        id: meProfile.id,
        username: data.username,
        name: data.name,
        handle: data.handle,
        avatar: data.avatar,
      };
      renderOwnAvatar();
    }
    const u = users.find((x) => x.username === data.username || x.id === data.user_id);
    if (!u) return;
    // Privacy: never surface identity for a user who blocked us.
    if (u.blockedMe) return;
    u.name = data.name;
    u.handle = data.handle;
    if ("avatar" in data) u.avatar = data.avatar;
    renderList();
    if (currentId === u.id) {
      renderChat(false);
      renderDetails();
    }
  });

  /* ---------- Search ---------- */
  let searchTimer = null;

  // Search input: filter the current list with debounce.
  searchInput.addEventListener("input", () => {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      query = searchInput.value.trim();
      renderList();
    }, 300);
  });

  /* ---------- Compose / start a conversation ---------- */
  const composeBtn = document.getElementById("new-convo-btn");
  const newChatModal = document.getElementById("new-chat-modal");
  const closeModalBtn = document.getElementById("close-modal-btn");
  const modalSearch = document.getElementById("modal-search");
  const recentUsersSection = document.getElementById("recent-users-section");
  const recentUsersList = document.getElementById("recent-users-list");
  const suggestedUsersSection = document.getElementById("suggested-users-section");
  const suggestedUsersList = document.getElementById("suggested-users-list");
  const searchResultsSection = document.getElementById("search-results-section");
  const searchResultsList = document.getElementById("search-results-list");
  const modalEmpty = document.getElementById("modal-empty");

  let modalSearchTimer = null;

  // Render a user item in the modal.
  function renderModalUser(u) {
    const avatarHtml = u.avatar
      ? `<span class="avatar" style="background-image:url('${esc(u.avatar)}');background-size:cover;background-position:center"></span>`
      : `<span class="avatar" style="${avatarStyle(u.id - 1)}">${initials(u.name)}</span>`;

    return `
      <button class="modal-user-item" data-user-id="${u.userId ?? u.id}">
        ${avatarHtml}
        <div class="modal-user-body">
          <div class="modal-user-name">${esc(u.name)}</div>
          <div class="modal-user-handle">${esc(u.handle)}</div>
        </div>
      </button>`;
  }

  // Open the new chat modal.
  function openNewChatModal() {
    newChatModal.hidden = false;
    modalSearch.value = "";
    modalSearch.focus();
    loadRecentUsers();
    loadSuggestedUsers();
    searchResultsSection.hidden = true;
    modalEmpty.hidden = true;
  }

  // Close the new chat modal.
  function closeNewChatModal() {
    newChatModal.hidden = true;
    modalSearch.value = "";
  }

  // Load recent users (users with existing conversations).
  function loadRecentUsers() {
    // Show the 5 most recent conversations as "Recent". Conversations where
    // the other participant blocked us are excluded: they are anonymized and
    // their userId is null, so they cannot be used to start a new chat.
    const recent = users
      .slice()
      .filter((u) => !u.blockedMe)
      .sort((a, b) => b.ts - a.ts)
      .slice(0, 5);
    if (recent.length) {
      recentUsersList.innerHTML = recent.map(renderModalUser).join("");
      recentUsersSection.hidden = false;
    } else {
      recentUsersSection.hidden = true;
    }
  }

  // Load suggested users (fetch from backend).
  function loadSuggestedUsers() {
    fetch("/chat/users/?suggested=1")
      .then((r) => r.json())
      .then((data) => {
        const suggested = data.users || [];
        if (suggested.length) {
          suggestedUsersList.innerHTML = suggested.map(renderModalUser).join("");
          suggestedUsersSection.hidden = false;
        } else {
          suggestedUsersSection.hidden = true;
        }
      })
      .catch(() => {
        suggestedUsersSection.hidden = true;
      });
  }

  // Search users via backend.
  function searchModalUsers(q) {
    if (!q.trim()) {
      searchResultsSection.hidden = true;
      recentUsersSection.hidden = false;
      suggestedUsersSection.hidden = false;
      modalEmpty.hidden = true;
      loadRecentUsers();
      loadSuggestedUsers();
      return;
    }

    fetch(`/chat/users/?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then((data) => {
        const results = data.users || [];
        recentUsersSection.hidden = true;
        suggestedUsersSection.hidden = true;

        if (results.length) {
          searchResultsList.innerHTML = results.map(renderModalUser).join("");
          searchResultsSection.hidden = false;
          modalEmpty.hidden = true;
        } else {
          searchResultsSection.hidden = true;
          modalEmpty.hidden = false;
        }
      })
      .catch(() => {
        searchResultsSection.hidden = true;
        modalEmpty.hidden = false;
      });
  }

  // Start a conversation with the selected user.
  function startConversationFromModal(userId) {
    fetch("/chat/start/", {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      credentials: "same-origin",
      body: new URLSearchParams({ user_id: String(userId) })
    })
      .then((r) => r.json())
      .then((data) => {
        if (!data.conversation) return;
        const existing = userById(data.conversation.id);
        if (existing) {
          Object.assign(existing, data.conversation);
        } else {
          users.push(data.conversation);
        }
        closeNewChatModal();
        select(data.conversation.id);
      })
      .catch(() => {
        alert("Failed to start conversation. Please try again.");
      });
  }

  // Modal event handlers.
  composeBtn.addEventListener("click", openNewChatModal);
  closeModalBtn.addEventListener("click", closeNewChatModal);

  // Close modal when clicking outside.
  newChatModal.addEventListener("click", (e) => {
    if (e.target === newChatModal) {
      closeNewChatModal();
    }
  });

  // Close modal on Escape key.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !newChatModal.hidden) {
      closeNewChatModal();
    }
  });

  // Search input with debounce.
  modalSearch.addEventListener("input", () => {
    const q = modalSearch.value.trim();
    if (modalSearchTimer) clearTimeout(modalSearchTimer);
    modalSearchTimer = setTimeout(() => searchModalUsers(q), 300);
  });

  // Handle user selection in modal.
  newChatModal.addEventListener("click", (e) => {
    const item = e.target.closest(".modal-user-item");
    if (!item) return;
    const userId = Number(item.dataset.userId);
    if (userId) startConversationFromModal(userId);
  });

  /* ---------- List clicks ---------- */
  // Sidebar click: open a conversation.
  convoList.addEventListener("click", (e) => {
    const item = e.target.closest(".convo-item");
    if (!item) return;
    select(Number(item.dataset.id));
  });

  /* ---------- Panel toggles ---------- */
  const backBtn = document.getElementById("back-btn");
  const infoBtn = document.getElementById("info-btn");
  const closeDetails = document.getElementById("close-details");

  // Toggle the details panel.
  function toggleDetails() {
    app.classList.toggle("details-open");
  }

  // Open the details panel.
  function openDetails() {
    app.classList.add("details-open");
  }

  backBtn.addEventListener("click", () => {
    app.classList.add("list-open");
    app.classList.remove("chat-open");
  });

  // Info button, avatar, and name all toggle the details panel.
  infoBtn.addEventListener("click", toggleDetails);
  chatAvatar.addEventListener("click", openDetails);
  chatName.addEventListener("click", openDetails);
  closeDetails.addEventListener("click", () => app.classList.remove("details-open"));

  /* ---------- Message search ---------- */
  // Toggle the search bar for the current thread; open + focus or clear.
  msgSearchBtn.addEventListener("click", () => {
    if (msgSearch.hidden) {
      msgSearch.hidden = false;
      msgSearchInput.focus();
    } else {
      clearMsgSearch();
    }
  });
  // Filter the thread live as the query changes.
  msgSearchInput.addEventListener("input", () => {
    msgQuery = msgSearchInput.value;
    renderChat();
  });
  msgSearchInput.addEventListener("keydown", (e) => {
    if (e.key === "Escape") clearMsgSearch();
  });
  msgSearchClear.addEventListener("click", clearMsgSearch);

  // Reset the query, hide the bar, and restore the full thread.
  function clearMsgSearch() {
    msgQuery = "";
    msgSearchInput.value = "";
    msgSearch.hidden = true;
    renderChat();
  }

  /* ---------- Older history (lazy load) ---------- */
  let loadingOlder = false;

  // Fetch messages older than the oldest one currently in the thread and
  // prepend them, preserving the viewport position.
  function loadOlder() {
    const u = current();
    if (!u || !u.hasMore || loadingOlder || !u.messages.length) return;
    loadingOlder = true;
    const before = u.messages[0].id;
    const prevHeight = chatBody.scrollHeight;
    fetch(`/chat/conversations/${u.id}/history/?before=${before}`)
      .then((r) => r.json())
      .then((data) => {
        const older = data.messages || [];
        if (older.length) u.messages = older.concat(u.messages);
        u.hasMore = !!data.has_more;
        renderChat(false);
        chatBody.scrollTop = chatBody.scrollHeight - prevHeight;
      })
      .catch(() => {})
      .finally(() => {
        loadingOlder = false;
      });
  }

  // Both the "Load earlier messages" button and scrolling near the top
  // trigger the history fetch.
  chatBody.addEventListener("click", (e) => {
    if (e.target && e.target.id === "load-earlier") loadOlder();
  });
  chatBody.addEventListener("scroll", () => {
    if (chatBody.scrollTop < 60) loadOlder();
  });

  /* ---------- Responsive ---------- */
  // Apply the correct panel layout for the current viewport width.
  function applyResponsive() {
    const w = window.innerWidth;
    if (w > 860) {
      app.classList.add("list-open");
      app.classList.remove("chat-open");
      // Details panel is always hidden by default, only opens on interaction
    } else {
      app.classList.add("list-open");
      app.classList.remove("chat-open");
      app.classList.remove("details-open");
    }
  }
  window.addEventListener("resize", applyResponsive);

  /* ---------- Init ---------- */
  // The theme is already applied by the inline no-flash script in base.html
  // and kept in sync by SyncChatTheme (theme.js); the button icon is set above
  // via syncThemeIcon(). Note: there is deliberately no `applyTheme` call here —
  // a dangling call to an undefined function aborted init and left the
  // conversation list empty until an event re-rendered it.
  applyResponsive();
  renderNotifState();
  updateUnread();
  initUserAvatar();
  if (users.length) select(users[0].id);
})();
