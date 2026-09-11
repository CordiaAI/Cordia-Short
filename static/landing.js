(function () {
  function createController({ landing, auth, onMode }) {
    let signedOut = false;

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

    landing.querySelectorAll("[data-auth-open]").forEach((button) => {
      button.addEventListener("click", () => open(button.getAttribute("data-auth-open")));
    });
    auth.querySelector("[data-auth-close]")?.addEventListener("click", showLanding);

    return {
      setSignedOut(value) {
        signedOut = value === true;
        showLanding();
      },
      open,
      showLanding,
    };
  }

  window.CordiaLanding = { createController };
})();
