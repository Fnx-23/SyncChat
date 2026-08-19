// Shared theme system — loaded on every page from base.html.
//
// Preference model: the user picks one of 'light' | 'dark' | 'system'.
// 'system' resolves to light/dark from the OS and reacts live to OS changes.
// The preference is persisted two ways:
//   - localStorage ('syncchat:theme')   — anonymous users / before login / instant
//   - database (User.theme, via the API) — logged-in users, survives devices
// The inline no-flash script in base.html already applied the initial value
// before this file runs; here we just keep it in sync and expose the API.
(function () {
  const LS_KEY = "syncchat:theme";
  const VALID = ["light", "dark", "system"];
  const root = document.documentElement;

  /* ---------- Resolution helpers ---------- */
  function osPrefersDark() {
    return (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  function resolve(pref) {
    if (pref === "system") return osPrefersDark() ? "dark" : "light";
    return pref === "dark" ? "dark" : "light";
  }

  // The inline script stashed the chosen preference here; fall back to
  // localStorage, then to 'system'.
  function getPreference() {
    let pref = root.getAttribute("data-theme-pref");
    if (VALID.indexOf(pref) === -1) {
      try { pref = localStorage.getItem(LS_KEY); } catch (e) { pref = null; }
    }
    if (VALID.indexOf(pref) === -1) pref = "system";
    return pref;
  }

  function getResolved() {
    return root.dataset.theme || resolve(getPreference());
  }

  /* ---------- Smooth transitions ----------
     Bare CSS-variable swaps don't animate because variable changes aren't
     transitionable. So we briefly enable transitions on the common colour
     properties only during an explicit switch, then turn them off again so
     the initial paint and unrelated DOM mutations stay cheap. */
  let transitionTimer;

  function withTransitions(fn) {
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      fn();
      return;
    }
    root.classList.add("theme-transition");
    fn();
    clearTimeout(transitionTimer);
    transitionTimer = setTimeout(() => root.classList.remove("theme-transition"), 300);
  }

  /* ---------- Apply / persist ---------- */
  function applyResolved(resolved) {
    root.dataset.theme = resolved;
    // Let the page react (e.g. toggle button icons / aria labels).
    document.dispatchEvent(
      new CustomEvent("syncchat:themechange", {
        detail: {
          preference: getPreference(),
          resolved: resolved,
        },
      })
    );
  }

  function persist(pref) {
    try { localStorage.setItem(LS_KEY, pref); } catch (e) {}
    // Fire-and-forget DB save for logged-in users; anonymous users still
    // have localStorage so the next page load is correct.
    try {
      const token = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      if (token) {
        const body = new URLSearchParams({ theme: pref });
        fetch("/accounts/theme/", {
          method: "POST",
          headers: {
            "X-CSRFToken": token,
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: body.toString(),
        }).catch(() => {});
      }
    } catch (e) {}
  }

  // Set a preference (light|dark|system), resolve, apply, and persist.
  function setPreference(pref) {
    if (VALID.indexOf(pref) === -1) return;
    root.dataset.themePref = pref;
    persist(pref);
    const resolved = resolve(pref);
    withTransitions(() => applyResolved(resolved));
    return resolved;
  }

  // Simpler toggle used by the dashboard sun/moon button: flip light <-> dark.
  function toggle() {
    const next = getResolved() === "dark" ? "light" : "dark";
    return setPreference(next);
  }

  /* ---------- Live OS tracking for 'system' ---------- */
  function refreshIfSystem() {
    if (getPreference() !== "system") return;
    withTransitions(() => applyResolved(resolve("system")));
  }

  if (window.matchMedia) {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = mql.addEventListener
      ? (e) => e.addEventListener("change", refreshIfSystem)
      : null;
    // addEventListener is the modern API; fall back silently otherwise.
    if (mql.addEventListener) {
      mql.addEventListener("change", refreshIfSystem);
    } else if (mql.addListener) {
      mql.addListener(refreshIfSystem);
    }
  }

  // Re-resolve on first load in case the inline script's server hint was stale
  // (e.g. OS preference changed since the page was rendered). Cheap and safe.
  if (getPreference() === "system") {
    applyResolved(resolve("system"));
  }

  window.SyncChatTheme = {
    getPreference,
    getResolved,
    resolve,
    setPreference,
    toggle,
    applyResolved,
  };
})();
