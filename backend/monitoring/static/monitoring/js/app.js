"use strict";

const desktopBreakpoint = window.matchMedia(
  "(min-width: 901px)"
);


async function getCSRFToken(url) {
  const response = await fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(
      "Unable to initialise the secure request."
    );
  }

  const data = await response.json();

  if (!data.csrf_token) {
    throw new Error(
      "The server did not provide a CSRF token."
    );
  }

  return data.csrf_token;
}


function initialiseSidebar() {
  const sidebar = document.querySelector(
    "[data-sidebar]"
  );
  const toggle = document.querySelector(
    "[data-sidebar-toggle]"
  );
  const overlay = document.querySelector(
    "[data-sidebar-overlay]"
  );

  if (!sidebar || !toggle || !overlay) {
    return;
  }

  function isDesktop() {
    return desktopBreakpoint.matches;
  }

  function setMobileSidebar(open) {
    document.body.classList.toggle(
      "sidebar-open",
      open
    );

    overlay.hidden = !open;
    toggle.setAttribute(
      "aria-expanded",
      String(open)
    );
  }

  function applyDesktopPreference() {
    const collapsed =
      localStorage.getItem("sidebar-collapsed") ===
      "true";

    document.body.classList.toggle(
      "sidebar-collapsed",
      collapsed
    );

    document.body.classList.remove("sidebar-open");
    overlay.hidden = true;

    toggle.setAttribute(
      "aria-expanded",
      String(!collapsed)
    );
  }

  function applyResponsiveState() {
    if (isDesktop()) {
      applyDesktopPreference();
      return;
    }

    document.body.classList.remove(
      "sidebar-collapsed"
    );
    setMobileSidebar(false);
  }

  toggle.addEventListener("click", () => {
    if (isDesktop()) {
      const collapsed = document.body.classList.toggle(
        "sidebar-collapsed"
      );

      localStorage.setItem(
        "sidebar-collapsed",
        String(collapsed)
      );

      toggle.setAttribute(
        "aria-expanded",
        String(!collapsed)
      );

      return;
    }

    setMobileSidebar(
      !document.body.classList.contains(
        "sidebar-open"
      )
    );
  });

  overlay.addEventListener("click", () => {
    setMobileSidebar(false);
  });

  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      document.body.classList.contains(
        "sidebar-open"
      )
    ) {
      setMobileSidebar(false);
      toggle.focus();
    }
  });

  desktopBreakpoint.addEventListener(
    "change",
    applyResponsiveState
  );

  applyResponsiveState();
}


function initialiseLogout() {
  const logoutButton = document.querySelector(
    "[data-logout]"
  );

  if (!logoutButton) {
    return;
  }

  logoutButton.addEventListener("click", async () => {
    logoutButton.disabled = true;
    logoutButton.setAttribute("aria-busy", "true");

    try {
      const csrfToken = await getCSRFToken(
        document.body.dataset.csrfUrl
      );

      const response = await fetch(
        document.body.dataset.logoutUrl,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
            "X-CSRFToken": csrfToken,
          },
        }
      );

      if (!response.ok) {
        throw new Error("Logout failed.");
      }

      window.location.assign(
        document.body.dataset.loginUrl
      );
    } catch (error) {
      window.alert(
        "Unable to sign out. Please try again."
      );

      logoutButton.disabled = false;
      logoutButton.removeAttribute("aria-busy");
    }
  });
}


document.addEventListener("DOMContentLoaded", () => {
  initialiseSidebar();
  initialiseLogout();
});