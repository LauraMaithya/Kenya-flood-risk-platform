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

  const isDashboard = document.body.classList.contains(
      "dashboard-map-page"
    );

    if (isDashboard) {
      document.body.classList.remove(
        "sidebar-collapsed",
        "sidebar-open"
      );

      toggle.hidden = true;
      overlay.hidden = true;
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

function initialiseConfidenceChart() {
  const chart = document.querySelector(
    "[data-confidence-chart]"
  );
  const donut = document.querySelector(
    "[data-confidence-donut]"
  );

  if (!chart || !donut) {
    return;
  }

  function toPercentage(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
      return 0;
    }

    return Math.min(
      100,
      Math.max(0, number * 100)
    );
  }

  const low = toPercentage(chart.dataset.low);
  const medium = toPercentage(chart.dataset.medium);
  const high = toPercentage(chart.dataset.high);

  const lowEnd = low;
  const mediumEnd = Math.min(100, low + medium);
  const highEnd = Math.min(
    100,
    low + medium + high
  );

  donut.style.background = [
    "conic-gradient(",
    `var(--low) 0% ${lowEnd}%,`,
    `var(--medium) ${lowEnd}% ${mediumEnd}%,`,
    `var(--high) ${mediumEnd}% ${highEnd}%,`,
    `#dce5e8 ${highEnd}% 100%`,
    ")",
  ].join(" ");

  donut.setAttribute(
    "aria-label",
    [
      `Low-risk probability ${Math.round(low)}%.`,
      `Medium-risk probability ${Math.round(medium)}%.`,
      `High-risk probability ${Math.round(high)}%.`,
    ].join(" ")
  );
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
  initialiseConfidenceChart();
  initialiseLogout();
});