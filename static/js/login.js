(function () {
  const form = document.getElementById("login-form");
  const username = document.getElementById("username");
  const password = document.getElementById("password");
  const error = document.getElementById("form-error");
  const btn = document.getElementById("submit-btn");
  const btnLabel = btn.querySelector(".btn-label");
  const remember = document.getElementById("remember");

  SyncChatCommon.initPasswordToggles();

  // Restore remembered username
  try {
    const saved = localStorage.getItem("syncchat_username");
    if (saved) {
      username.value = saved;
      remember.checked = true;
    }
  } catch (e) {}

  const clearError = () => {
    error.classList.remove("show");
    form.querySelectorAll("input").forEach((i) => i.classList.remove("error"));
  };
  username.addEventListener("input", clearError);
  password.addEventListener("input", clearError);

  function markInvalid() {
    [username, password].forEach((i) => {
      i.classList.remove("error");
      void i.offsetWidth; // restart shake
      i.classList.add("error");
    });
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    clearError();

    const valid = username.value.trim() && password.value;

    if (!valid) {
      markInvalid();
      error.classList.add("show");
      SyncChatCommon.shakeForm(form);
      (username.value.trim() ? password : username).focus();
      return;
    }

    // Persist remember-me
    try {
      if (remember.checked) {
        localStorage.setItem("syncchat_username", username.value.trim());
      } else {
        localStorage.removeItem("syncchat_username");
      }
    } catch (e) {}

    // Real login: brief loading state, then submit to the server.
    // form.submit() bypasses this submit handler, so no loop.
    btn.disabled = true;
    btnLabel.innerHTML = '<span class="spinner" aria-hidden="true"></span> Logging in\u2026';
    setTimeout(() => {
      form.submit();
    }, 400);
  });
})();
