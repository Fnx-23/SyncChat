(function () {
  const navItems = document.querySelectorAll(".nav-item");
  const sections = document.querySelectorAll(".settings-section");
  const profileForm = document.getElementById("profile-form");
  const passwordForm = document.getElementById("password-form");
  const autoSaveIndicator = document.getElementById("auto-save-indicator");
  const autoSaveText = document.getElementById("auto-save-text");
  const avatarBtn = document.getElementById("avatar-btn");
  const avatarImg = document.getElementById("avatar-img");
  const avatarInitials = document.getElementById("avatar-initials");
  const photoInput = document.getElementById("photo-input");
  const themeOptions = document.querySelectorAll(".theme-option");

  const fields = {
    displayName: document.getElementById("fullname"),
    username: document.getElementById("username"),
    email: document.getElementById("email"),
    bio: document.getElementById("bio"),
    currentPw: document.getElementById("current-pw"),
    newPw: document.getElementById("new-pw"),
    confirmPw: document.getElementById("confirm-pw")
  };

  /* ---------- Section Navigation ---------- */
  function showSection(sectionId) {
    sections.forEach(s => s.classList.remove("active"));
    navItems.forEach(n => n.classList.remove("active"));

    const section = document.getElementById(`section-${sectionId}`);
    const navItem = document.querySelector(`[data-section="${sectionId}"]`);

    if (section) section.classList.add("active");
    if (navItem) navItem.classList.add("active");
  }

  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const sectionId = item.dataset.section;
      showSection(sectionId);
      window.location.hash = sectionId;
    });
  });

  // Load section from hash on page load
  function loadSectionFromHash() {
    const hash = window.location.hash.slice(1);
    if (hash && document.getElementById(`section-${hash}`)) {
      showSection(hash);
    } else {
      showSection("profile");
    }
  }

  window.addEventListener("hashchange", loadSectionFromHash);
  loadSectionFromHash();

  /* ---------- Auto-save Indicator ---------- */
  let indicatorTimeout;

  function showAutoSave(status, message) {
    clearTimeout(indicatorTimeout);
    autoSaveIndicator.hidden = false;
    autoSaveIndicator.className = "auto-save-indicator";
    autoSaveText.textContent = message;

    if (status === "success") {
      autoSaveIndicator.classList.add("success");
    } else if (status === "error") {
      autoSaveIndicator.classList.add("error");
    }

    indicatorTimeout = setTimeout(() => {
      autoSaveIndicator.hidden = true;
    }, 3000);
  }

  /* ---------- Debounce Utility ---------- */
  function debounce(fn, delay) {
    let timeout;
    return function (...args) {
      clearTimeout(timeout);
      timeout = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  /* ---------- Auto-save Profile Fields ---------- */
  function autoSaveField(fieldName, value) {
    showAutoSave("saving", "Saving...");

    const formData = new FormData();
    formData.append("field", fieldName);
    formData.append("value", value);

    const csrfToken = profileForm.querySelector('[name="csrfmiddlewaretoken"]').value;

    fetch("/accounts/settings/autosave/", {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken
      },
      body: formData
    })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          showAutoSave("success", "Saved");
        } else {
          showAutoSave("error", data.error || "Error saving");
        }
      })
      .catch(() => {
        showAutoSave("error", "Network error");
      });
  }

  const debouncedAutoSave = debounce((fieldName, value) => {
    autoSaveField(fieldName, value);
  }, 500);

  // Wire up auto-save listeners
  if (fields.displayName) {
    fields.displayName.addEventListener("input", (e) => {
      debouncedAutoSave("display_name", e.target.value);
      avatarInitials.textContent = SyncChatCommon.initials(e.target.value.trim());
    });
  }

  if (fields.username) {
    fields.username.addEventListener("input", (e) => {
      debouncedAutoSave("username", e.target.value);
    });
  }

  if (fields.email) {
    fields.email.addEventListener("input", (e) => {
      debouncedAutoSave("email", e.target.value);
    });
  }

  if (fields.bio) {
    fields.bio.addEventListener("input", (e) => {
      debouncedAutoSave("bio", e.target.value);
    });
  }

  /* ---------- Avatar Upload ---------- */
  function applyPhoto(src) {
    if (src) {
      avatarImg.src = src;
      avatarBtn.classList.add("has-photo");
    } else {
      avatarImg.removeAttribute("src");
      avatarBtn.classList.remove("has-photo");
    }
    avatarInitials.textContent = SyncChatCommon.initials(fields.displayName.value.trim());
  }

  applyPhoto(avatarImg.getAttribute("src"));

  avatarBtn.addEventListener("click", () => photoInput.click());

  photoInput.addEventListener("change", () => {
    const file = photoInput.files && photoInput.files[0];
    if (!file || !file.type.startsWith("image/")) return;

    const reader = new FileReader();
    reader.onload = () => applyPhoto(reader.result);
    reader.readAsDataURL(file);

    // Submit form to save avatar
    profileForm.submit();
  });

  /* ---------- Username Sanitization ---------- */
  if (fields.username) {
    SyncChatCommon.sanitizeUsernameInput(fields.username);
  }

  /* ---------- Password Toggles ---------- */
  SyncChatCommon.initPasswordToggles();

  /* ---------- Password Form Validation ---------- */
  function clearFieldError(field) {
    field.classList.remove("error");
    const errorDiv = field.closest(".form-group").querySelector(".field-error");
    if (errorDiv && !errorDiv.hasAttribute("data-server-error")) {
      errorDiv.remove();
    }
  }

  function showFieldError(field, message) {
    clearFieldError(field);
    field.classList.add("error");

    const formGroup = field.closest(".form-group");
    let errorDiv = formGroup.querySelector(".field-error");
    if (!errorDiv) {
      errorDiv = document.createElement("div");
      errorDiv.className = "field-error";
      formGroup.appendChild(errorDiv);
    }
    errorDiv.textContent = message;
  }

  Object.values(fields).forEach(field => {
    if (field) {
      field.addEventListener("input", () => clearFieldError(field));
    }
  });

  if (passwordForm) {
    passwordForm.addEventListener("submit", (e) => {
      let hasError = false;

      const current = fields.currentPw.value;
      const newPw = fields.newPw.value;
      const confirm = fields.confirmPw.value;

      if (!current) {
        showFieldError(fields.currentPw, "Current password is required");
        hasError = true;
      }

      if (!newPw) {
        showFieldError(fields.newPw, "New password is required");
        hasError = true;
      } else if (newPw.length < 8) {
        showFieldError(fields.newPw, "Password must be at least 8 characters");
        hasError = true;
      }

      if (!confirm) {
        showFieldError(fields.confirmPw, "Please confirm your password");
        hasError = true;
      } else if (newPw !== confirm) {
        showFieldError(fields.confirmPw, "Passwords do not match");
        hasError = true;
      }

      if (hasError) {
        e.preventDefault();
        SyncChatCommon.shakeForm(passwordForm);
      }
    });
  }

  /* ---------- Theme Switching ---------- */
  // Delegate to the shared theme module (theme.js): it resolves light/dark,
  // applies it, persists to localStorage, and POSTs the preference to
  // /accounts/theme/ so User.theme stays in sync for logged-in users.
  function markActiveTheme(pref) {
    themeOptions.forEach(opt => {
      opt.classList.toggle("active", opt.dataset.theme === pref);
    });
  }

  // Reflect the current preference on open. getPreference() reads the
  // server-rendered DB value (data-theme-pref) before any localStorage.
  markActiveTheme(window.SyncChatTheme ? window.SyncChatTheme.getPreference() : "system");

  themeOptions.forEach(option => {
    option.addEventListener("click", () => {
      const pref = option.dataset.theme; // "light" | "dark" | "system"
      if (window.SyncChatTheme) {
        window.SyncChatTheme.setPreference(pref);
      }
      markActiveTheme(pref);
    });
  });

  /* ---------- Privacy Settings ---------- */
  const privacyControls = document.querySelectorAll("[data-privacy-field]");

  function savePrivacySetting(field, value) {
    showAutoSave("saving", "Saving...");

    const formData = new FormData();
    formData.append("field", field);
    formData.append("value", value);

    const csrfToken = profileForm.querySelector('[name="csrfmiddlewaretoken"]').value;

    fetch("/accounts/settings/privacy/", {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken
      },
      credentials: "same-origin",
      body: formData
    })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          showAutoSave("success", "Saved");
        } else {
          showAutoSave("error", data.error || "Error saving");
        }
      })
      .catch(() => {
        showAutoSave("error", "Network error");
      });
  }

  privacyControls.forEach(control => {
    control.addEventListener("change", () => {
      const field = control.dataset.privacyField;
      const value = control.type === "checkbox" ? String(control.checked) : control.value;
      savePrivacySetting(field, value);
    });
  });

  /* ---------- Notification Settings ---------- */
  // Notification preferences live in localStorage only (no server state);
  // dashboard.js reads the same keys to gate its alerts. Absent key => on.
  const notifToggles = {
    desktop: document.getElementById("desktop-notif"),
    message: document.getElementById("message-notif"),
    sound: document.getElementById("sound-notif")
  };

  Object.keys(notifToggles).forEach(kind => {
    const toggle = notifToggles[kind];
    if (!toggle) return;
    const key = `syncchat:notify:${kind}`;
    let stored = null;
    try { stored = localStorage.getItem(key); } catch (e) {}
    toggle.checked = stored !== "off";
    toggle.addEventListener("change", () => {
      try { localStorage.setItem(key, toggle.checked ? "on" : "off"); } catch (e) {}
    });
  });

  /* ---------- Blocked Users Management ---------- */
  const blockedUsersContainer = document.getElementById("blocked-users-container");
  const blockedLoading = document.getElementById("blocked-loading");
  const blockedEmpty = document.getElementById("blocked-empty");

  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function getInitials(name) {
    return name
      .split(" ")
      .map(n => n[0])
      .join("")
      .toUpperCase()
      .slice(0, 2);
  }

  function loadBlockedUsers() {
    if (!blockedUsersContainer) return;

    blockedLoading.hidden = false;
    blockedEmpty.hidden = true;
    blockedUsersContainer.innerHTML = "";

    fetch("/chat/blocked-users/", {
      method: "GET",
      headers: {
        "X-CSRFToken": getCookie("csrftoken")
      },
      credentials: "same-origin"
    })
      .then(res => {
        if (res.ok) return res.json();
        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
          return res.json().then(d => Promise.reject(new Error(d.error || "Failed to load blocked users.")));
        }
        return Promise.reject(new Error(`Failed to load blocked users (${res.status})`));
      })
      .then(data => {
        blockedLoading.hidden = true;
        const users = data.users || [];

        if (users.length === 0) {
          blockedEmpty.hidden = false;
          return;
        }

        blockedUsersContainer.innerHTML = users.map(user => {
          const initials = getInitials(user.name || user.username);
          const avatarHtml = user.avatar
            ? `<img src="${escapeHtml(user.avatar)}" alt="${escapeHtml(user.name)}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 50%;" />`
            : `<span>${escapeHtml(initials)}</span>`;

          return `
            <div class="blocked-user-item" data-user-id="${user.id}">
              <div class="blocked-user-info">
                <div class="blocked-user-avatar">${avatarHtml}</div>
                <div class="blocked-user-details">
                  <div class="blocked-user-name">${escapeHtml(user.name)}</div>
                  <div class="blocked-user-handle">${escapeHtml(user.handle)}</div>
                </div>
              </div>
              <div class="blocked-user-actions">
                <button class="btn-unblock" data-user-id="${user.id}" data-user-name="${escapeHtml(user.name)}">Unblock</button>
              </div>
            </div>`;
        }).join("");

        // Attach unblock handlers
        blockedUsersContainer.querySelectorAll(".btn-unblock").forEach(btn => {
          btn.addEventListener("click", () => {
            const userId = btn.dataset.userId;
            const userName = btn.dataset.userName;
            unblockUser(userId, userName, btn);
          });
        });
      })
      .catch(err => {
        blockedLoading.hidden = true;
        blockedUsersContainer.innerHTML = `
          <div style="padding: 40px; text-align: center; color: var(--error);">
            ${escapeHtml(err.message)}
          </div>`;
      });
  }

  function unblockUser(userId, userName, btn) {
    if (!userId) return;

    btn.disabled = true;
    btn.textContent = "Unblocking...";

    fetch(`/chat/users/${userId}/unblock/`, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken")
      },
      credentials: "same-origin"
    })
      .then(res => {
        if (res.ok) return res.json();
        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
          return res.json().then(d => Promise.reject(new Error(d.error || "Failed to unblock user.")));
        }
        return Promise.reject(new Error(`Failed to unblock user (${res.status})`));
      })
      .then(() => {
        // Remove the user item from the list
        const userItem = btn.closest(".blocked-user-item");
        if (userItem) {
          userItem.style.opacity = "0";
          userItem.style.transform = "translateX(-20px)";
          userItem.style.transition = "all 0.3s ease";
          setTimeout(() => {
            userItem.remove();
            // Check if list is empty
            if (blockedUsersContainer.children.length === 0) {
              blockedEmpty.hidden = false;
            }
          }, 300);
        }
      })
      .catch(err => {
        alert(err.message);
        btn.disabled = false;
        btn.textContent = "Unblock";
      });
  }

  // Load blocked users when the blocked section is shown
  navItems.forEach(item => {
    item.addEventListener("click", () => {
      if (item.dataset.section === "blocked") {
        loadBlockedUsers();
      }
    });
  });

  // Load on initial page load if blocked section is active
  if (window.location.hash === "#blocked") {
    loadBlockedUsers();
  }

  /* ---------- Delete Account ---------- */
  const deleteAccountBtn = document.getElementById("delete-account-btn");
  const deleteModal = document.getElementById("delete-account-modal");
  const deleteForm = document.getElementById("delete-account-form");
  const deletePassword = document.getElementById("delete-password");
  const deleteConfirmCheck = document.getElementById("delete-confirm-check");
  const deleteCancelBtn = document.getElementById("delete-cancel-btn");
  const deleteConfirmBtn = document.getElementById("delete-confirm-btn");
  const deleteError = document.getElementById("delete-account-error");

  if (deleteAccountBtn && deleteModal) {
    function closeDeleteModal() {
      deleteModal.hidden = true;
      deleteError.hidden = true;
      deleteError.textContent = "";
      deleteForm.reset();
      deleteConfirmBtn.disabled = true;
    }

    function refreshDeleteBtnState() {
      // Both an explicit confirmation and a password are required before the
      // destructive action can be triggered.
      deleteConfirmBtn.disabled = !(deleteConfirmCheck.checked && deletePassword.value);
    }

    function showDeleteError(message) {
      deleteError.textContent = message;
      deleteError.hidden = false;
    }

    deleteAccountBtn.addEventListener("click", () => {
      deleteError.hidden = true;
      deleteError.textContent = "";
      deleteForm.reset();
      deleteConfirmBtn.disabled = true;
      deleteModal.hidden = false;
      deletePassword.focus();
    });

    deleteCancelBtn.addEventListener("click", closeDeleteModal);

    deleteModal.addEventListener("click", (e) => {
      if (e.target === deleteModal) closeDeleteModal();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !deleteModal.hidden) closeDeleteModal();
    });

    deletePassword.addEventListener("input", () => {
      deleteError.hidden = true;
      refreshDeleteBtnState();
    });
    deleteConfirmCheck.addEventListener("change", refreshDeleteBtnState);

    deleteConfirmBtn.addEventListener("click", () => {
      if (!deleteConfirmCheck.checked || !deletePassword.value) return;

      deleteConfirmBtn.disabled = true;
      deleteConfirmBtn.textContent = "Deleting...";

      const formData = new FormData();
      formData.append("password", deletePassword.value);
      formData.append("confirm", "true");

      const csrfToken = deleteForm.querySelector('[name="csrfmiddlewaretoken"]').value;

      fetch("/accounts/delete-account/", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        body: formData,
        credentials: "same-origin"
      })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
          if (ok && data.success) {
            // Close any live sockets before leaving so no stale presence/chat
            // connection lingers for the deleted account.
            if (window.SyncChatSocket && typeof window.SyncChatSocket.disconnect === "function") {
              window.SyncChatSocket.disconnect();
            }
            if (window.SyncChatPresence && typeof window.SyncChatPresence.disconnect === "function") {
              window.SyncChatPresence.disconnect();
            }
            window.location.href = data.redirect || "/accounts/login/";
            return;
          }
          showDeleteError((data && data.error) || "Could not delete your account. Please try again.");
          deleteConfirmBtn.textContent = "Delete Account";
          refreshDeleteBtnState();
        })
        .catch(() => {
          showDeleteError("Network error. Your account was not deleted.");
          deleteConfirmBtn.textContent = "Delete Account";
          refreshDeleteBtnState();
        });
    });
  }
})();
