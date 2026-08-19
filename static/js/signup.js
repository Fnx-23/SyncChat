(function () {
  const form = document.getElementById("signup-form");
  const fields = {
    fullname: document.getElementById("fullname"),
    username: document.getElementById("username"),
    password: document.getElementById("password"),
    confirm: document.getElementById("confirm")
  };
  const error = document.getElementById("form-error");
  const btn = document.getElementById("submit-btn");
  const btnLabel = btn.querySelector(".btn-label");

  SyncChatCommon.initPasswordToggles();
  SyncChatCommon.sanitizeUsernameInput(fields.username);

  const clearError = () => {
    error.classList.remove("show");
    Object.values(fields).forEach((i) => i.classList.remove("error"));
  };
  Object.values(fields).forEach((i) => i.addEventListener("input", clearError));

  function fail(message) {
    error.textContent = message;
    error.classList.add("show");
    SyncChatCommon.shakeForm(form);
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    clearError();

    const name = fields.fullname.value.trim();
    const user = fields.username.value.trim();
    const pass = fields.password.value;
    const confirm = fields.confirm.value;

    let valid = true;

    if (!name) {
      fields.fullname.classList.add("error");
      valid = false;
    }
    if (!user) {
      fields.username.classList.add("error");
      valid = false;
    } else if (!/^[a-z0-9._-]+$/.test(user)) {
      fields.username.classList.add("error");
      fail("Username can only contain lowercase letters, numbers, dots, hyphens, and underscores.");
      fields.username.focus();
      return;
    }
    if (!pass) {
      fields.password.classList.add("error");
      valid = false;
    }
    if (pass && pass.length < 8) {
      fields.password.classList.add("error");
      valid = false;
      fail("Password must be at least 8 characters.");
      fields.password.focus();
      return;
    }
    if (!confirm || confirm !== pass) {
      fields.confirm.classList.add("error");
      valid = false;
      fail("Passwords do not match.");
      fields.confirm.focus();
      return;
    }

    if (!valid) {
      fail("Please fill in all fields.");
      ([fields.fullname, fields.username, fields.password, fields.confirm].find((i) => i.classList.contains("error")) || fields.fullname).focus();
      return;
    }

    // Real signup: brief loading state, then submit to the server.
    // form.submit() bypasses this submit handler, so no loop.
    btn.disabled = true;
    btnLabel.innerHTML = '<span class="spinner" aria-hidden="true"></span> Creating account\u2026';
    setTimeout(() => {
      form.submit();
    }, 400);
  });
})();
