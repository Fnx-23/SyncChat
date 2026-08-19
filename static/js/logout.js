(function () {
  const logoutBtn = document.getElementById("logout-btn");
  const logoutModal = document.getElementById("logout-modal");
  const logoutCancelBtn = document.getElementById("logout-cancel-btn");
  const logoutConfirmBtn = document.getElementById("logout-confirm-btn");

  if (!logoutBtn || !logoutModal) return;

  // Show logout confirmation modal
  logoutBtn.addEventListener("click", (e) => {
    e.preventDefault();
    logoutModal.hidden = false;
    // Close user dropdown if open
    const userDropdown = document.getElementById("user-dropdown");
    if (userDropdown) userDropdown.hidden = true;
  });

  // Cancel logout - close modal
  logoutCancelBtn.addEventListener("click", () => {
    logoutModal.hidden = true;
  });

  // Close modal when clicking outside
  logoutModal.addEventListener("click", (e) => {
    if (e.target === logoutModal) {
      logoutModal.hidden = true;
    }
  });

  // Close modal on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !logoutModal.hidden) {
      logoutModal.hidden = true;
    }
  });

  // Confirm logout - disconnect websocket and submit logout form
  logoutConfirmBtn.addEventListener("click", () => {
    // Disable button to prevent double-clicks
    logoutConfirmBtn.disabled = true;
    logoutConfirmBtn.textContent = "Logging out...";

    // Close any active websocket connections
    if (window.SyncChatSocket && typeof window.SyncChatSocket.disconnect === "function") {
      window.SyncChatSocket.disconnect();
    }
    if (window.SyncChatPresence && typeof window.SyncChatPresence.disconnect === "function") {
      window.SyncChatPresence.disconnect();
    }

    // Get CSRF token from cookie
    function getCookie(name) {
      let cookieValue = null;
      if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let i = 0; i < cookies.length; i++) {
          const cookie = cookies[i].trim();
          if (cookie.substring(0, name.length + 1) === name + "=") {
            cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
            break;
          }
        }
      }
      return cookieValue;
    }

    const csrftoken = getCookie("csrftoken");

    // Create and submit logout form via POST
    const form = document.createElement("form");
    form.method = "POST";
    form.action = "/accounts/logout/";

    const csrfInput = document.createElement("input");
    csrfInput.type = "hidden";
    csrfInput.name = "csrfmiddlewaretoken";
    csrfInput.value = csrftoken;

    form.appendChild(csrfInput);
    document.body.appendChild(form);
    form.submit();
  });
})();
