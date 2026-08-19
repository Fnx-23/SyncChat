(function () {
  const TOAST_DURATION = 2500; // 2.5 seconds
  const EXIT_ANIMATION_DURATION = 300; // Must match CSS animation duration

  const container = document.getElementById("toast-container");
  if (!container) return;

  // SVG icons for each toast type
  const icons = {
    success: `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
        <polyline points="22 4 12 14.01 9 11.01"/>
      </svg>
    `,
    error: `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <line x1="15" y1="9" x2="9" y2="15"/>
        <line x1="9" y1="9" x2="15" y2="15"/>
      </svg>
    `,
    warning: `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/>
        <line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
    `,
    info: `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="16" x2="12" y2="12"/>
        <line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>
    `,
  };

  // Close icon (X button)
  const closeIcon = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
      <line x1="18" y1="6" x2="6" y2="18"/>
      <line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  `;

  /**
   * Create and show a toast notification
   * @param {string} text - Message text
   * @param {string} type - Toast type: success, error, warning, info
   */
  function showToast(text, type = "info") {
    // Normalize type
    const normalizedType = normalizeType(type);

    // Create toast element
    const toast = document.createElement("div");
    toast.className = `toast toast-${normalizedType}`;
    toast.setAttribute("role", "alert");
    toast.setAttribute("aria-live", "polite");

    // Build toast HTML
    toast.innerHTML = `
      <div class="toast-icon">${icons[normalizedType] || icons.info}</div>
      <div class="toast-message">${escapeHtml(text)}</div>
      <button type="button" class="toast-close" aria-label="Close notification">
        ${closeIcon}
      </button>
    `;

    // Add to container
    container.appendChild(toast);

    // Setup auto-hide timer
    let hideTimer = null;
    let remainingTime = TOAST_DURATION;
    let startTime = Date.now();

    const startTimer = () => {
      startTime = Date.now();
      hideTimer = setTimeout(() => {
        hideToast(toast);
      }, remainingTime);
    };

    const pauseTimer = () => {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
        remainingTime -= Date.now() - startTime;
      }
    };

    // Start the timer
    startTimer();

    // Pause on hover
    toast.addEventListener("mouseenter", () => {
      pauseTimer();
      toast.classList.add("toast-paused");
    });

    // Resume on leave
    toast.addEventListener("mouseleave", () => {
      toast.classList.remove("toast-paused");
      startTimer();
    });

    // Close button handler
    const closeBtn = toast.querySelector(".toast-close");
    closeBtn.addEventListener("click", () => {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
      hideToast(toast);
    });

    // Cleanup function
    toast._cleanup = () => {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
    };
  }

  /**
   * Hide toast with exit animation
   * @param {HTMLElement} toast - Toast element to hide
   */
  function hideToast(toast) {
    if (!toast || !toast.parentNode) return;

    // Cleanup timer
    if (toast._cleanup) {
      toast._cleanup();
    }

    // Add exit animation class
    toast.classList.add("toast-exit");

    // Remove from DOM after animation completes
    setTimeout(() => {
      if (toast.parentNode) {
        container.removeChild(toast);
      }
    }, EXIT_ANIMATION_DURATION);
  }

  /**
   * Normalize message type from Django's tags
   * @param {string} type - Message type/tag
   * @returns {string} Normalized type
   */
  function normalizeType(type) {
    // Django uses 'error' for errors, but also might use 'danger'
    // Map common Django message tags to our types
    const typeMap = {
      success: "success",
      error: "error",
      danger: "error",
      warning: "warning",
      info: "info",
      debug: "info",
    };

    const normalized = String(type).toLowerCase().trim();
    return typeMap[normalized] || "info";
  }

  /**
   * Escape HTML to prevent XSS
   * @param {string} text - Text to escape
   * @returns {string} Escaped text
   */
  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Load and display Django messages from JSON script tag
   */
  function loadDjangoMessages() {
    const messagesScript = document.getElementById("django-messages");
    if (!messagesScript) return;

    try {
      const messages = JSON.parse(messagesScript.textContent);
      messages.forEach((msg) => {
        showToast(msg.text, msg.type);
      });
    } catch (e) {
      console.error("Failed to parse Django messages:", e);
    }
  }

  // Load Django messages on page load
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadDjangoMessages);
  } else {
    loadDjangoMessages();
  }

  // Expose API for programmatic use
  window.SyncChatToast = {
    show: showToast,
    success: (text) => showToast(text, "success"),
    error: (text) => showToast(text, "error"),
    warning: (text) => showToast(text, "warning"),
    info: (text) => showToast(text, "info"),
  };
})();
