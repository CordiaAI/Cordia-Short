(function () {
  function createController({ landing, auth, onMode, initialMode }) {
    let signedOut = false;
    let pendingMode = ["signin", "register"].includes(initialMode) ? initialMode : null;

    function showLanding() {
      landing.hidden = !signedOut;
      auth.hidden = true;
    }

    function open(mode) {
      if (!signedOut) return;
      onMode(mode);
      landing.hidden = true;
      auth.hidden = false;
      auth.querySelector("input")?.focus();
    }

    auth.querySelector("[data-auth-close]")?.addEventListener("click", showLanding);

    return {
      setSignedOut(value) {
        signedOut = value === true;
        if (signedOut && pendingMode) {
          const mode = pendingMode;
          pendingMode = null;
          open(mode);
          return;
        }
        if (!signedOut) pendingMode = null;
        showLanding();
      },
      showLanding,
    };
  }

  window.CordiaLanding = { createController };
})();
