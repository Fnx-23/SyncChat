// Shared UI helpers used by the login, signup, settings, and dashboard pages.
// Loaded from base.html before any page-specific script.
(function () {
  // Escape text before inserting it into innerHTML to prevent XSS.
  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Up to two leading initials, used for avatar placeholders.
  function initials(name) {
    const parts = String(name).split(" ").filter(Boolean);
    if (!parts.length) return "?";
    return parts.map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  }

  // Wire up all .toggle-pw buttons (inside an .input-wrap) to flip the input
  // type between password and text.
  function initPasswordToggles() {
    document.querySelectorAll(".toggle-pw").forEach((toggle) => {
      toggle.addEventListener("click", () => {
        const input = toggle.closest(".input-wrap").querySelector("input");
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        toggle.setAttribute("aria-pressed", String(show));
        toggle.classList.add("visible");
        input.focus({ preventScroll: true });
      });
    });
  }

  // Restrict a username input to the server's allowed charset, lowercased.
  function sanitizeUsernameInput(input) {
    input.addEventListener("input", () => {
      input.value = input.value.toLowerCase().replace(/[^a-z0-9._-]/g, "");
    });
  }

  // Restart the shake animation on an invalid form.
  function shakeForm(form) {
    form.classList.remove("shake");
    void form.offsetWidth;
    form.classList.add("shake");
  }

  window.SyncChatCommon = {
    esc,
    initials,
    initPasswordToggles,
    sanitizeUsernameInput,
    shakeForm,
  };
})();
