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


function initialiseSidebarTreeNavigation() {
  const trees = document.querySelectorAll(
    "[data-sidebar-tree]"
  );

  if (!trees.length) {
    return;
  }

  trees.forEach((tree) => {
    const items = Array.from(
      tree.querySelectorAll("[data-sidebar-tree-item]")
    );

    if (!items.length) {
      return;
    }

    const activeItem = items.find(
      (item) => item.getAttribute("aria-current") === "page"
    );
    let hoveredItem = null;

    function setTarget(item) {
      if (!item) {
        tree.classList.remove("sidebar-tree-visible");
        return;
      }

      const center = item.offsetTop + item.offsetHeight / 2;
      const firstItem = items[0];
      const firstCenter = (
        firstItem.offsetTop + firstItem.offsetHeight / 2
      );

      tree.style.setProperty(
        "--tree-highlight-y",
        `${item.offsetTop}px`
      );
      tree.style.setProperty(
        "--tree-marker-y",
        `${center}px`
      );
      tree.style.setProperty(
        "--tree-accent-height",
        `${Math.max(0, center - firstCenter)}px`
      );
      tree.classList.add("sidebar-tree-visible");
    }

    function measure() {
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      const firstCenter = (
        firstItem.offsetTop + firstItem.offsetHeight / 2
      );
      const lastCenter = (
        lastItem.offsetTop + lastItem.offsetHeight / 2
      );

      tree.style.setProperty(
        "--tree-track-start",
        `${firstCenter}px`
      );
      tree.style.setProperty(
        "--tree-track-height",
        `${Math.max(0, lastCenter - firstCenter)}px`
      );
      setTarget(hoveredItem || activeItem);
      tree.classList.add("sidebar-tree-ready");
    }

    items.forEach((item) => {
      item.addEventListener("pointerenter", () => {
        hoveredItem = item;
        setTarget(item);
      });

      item.addEventListener("focus", () => {
        hoveredItem = item;
        setTarget(item);
      });
    });

    tree.addEventListener("pointerleave", () => {
      hoveredItem = null;
      setTarget(activeItem);
    });

    tree.addEventListener("focusout", () => {
      window.requestAnimationFrame(() => {
        if (!tree.contains(document.activeElement)) {
          hoveredItem = null;
          setTarget(activeItem);
        }
      });
    });

    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(measure);
      observer.observe(tree);
    }

    window.requestAnimationFrame(measure);
  });
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

  const centreValue = donut.querySelector(
    ".county-confidence-centre strong"
  );
  const centreLabel = donut.querySelector(
    ".county-confidence-centre span"
  );
  const legendItems = Array.from(
    chart.querySelectorAll(
      ".county-confidence-legend [data-risk]"
    )
  );

  if (!centreValue || !centreLabel) {
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

  const values = [
    {
      risk: "Low",
      value: toPercentage(chart.dataset.low),
      colour: "var(--low)",
    },
    {
      risk: "Medium",
      value: toPercentage(chart.dataset.medium),
      colour: "var(--medium)",
    },
    {
      risk: "High",
      value: toPercentage(chart.dataset.high),
      colour: "var(--high)",
    },
  ];

  let cumulative = 0;

  const gradientStops = values.map((entry) => {
    const start = cumulative;
    cumulative = Math.min(
      100,
      cumulative + entry.value
    );

    return (
      `${entry.colour} ${start}% ${cumulative}%`
    );
  });

  if (cumulative < 100) {
    gradientStops.push(
      `#dce5e8 ${cumulative}% 100%`
    );
  }

  donut.style.setProperty(
    "background",
    `conic-gradient(${gradientStops.join(", ")})`,
    "important"
  );

  const currentRisk = centreValue.textContent.trim();
  const currentLabel = centreLabel.textContent.trim();

  function clearActiveState() {
    legendItems.forEach((item) => {
      item.classList.remove("is-active");
      item.removeAttribute("aria-current");
    });
  }

  function showEntry(entry) {
    if (!entry) {
      return;
    }

    centreValue.textContent =
      `${Math.round(entry.value)}%`;
    centreLabel.textContent =
      `${entry.risk} risk`;

    clearActiveState();

    const matchingLegend = legendItems.find(
      (item) => item.dataset.risk === entry.risk
    );

    if (matchingLegend) {
      matchingLegend.classList.add("is-active");
      matchingLegend.setAttribute(
        "aria-current",
        "true"
      );
    }
  }

  function restoreCurrentPrediction() {
    centreValue.textContent = currentRisk;
    centreLabel.textContent = currentLabel;
    clearActiveState();
  }

  function entryForRisk(risk) {
    return values.find(
      (entry) => entry.risk === risk
    );
  }

  function entryForPointer(event) {
    const bounds = donut.getBoundingClientRect();
    const centreX = bounds.left + bounds.width / 2;
    const centreY = bounds.top + bounds.height / 2;

    const deltaX = event.clientX - centreX;
    const deltaY = event.clientY - centreY;

    const distance = Math.sqrt(
      deltaX * deltaX + deltaY * deltaY
    );

    const outerRadius = bounds.width / 2;
    const innerRadius = outerRadius * 0.62;

    if (
      distance < innerRadius ||
      distance > outerRadius
    ) {
      return null;
    }

    const degrees = (
      Math.atan2(deltaY, deltaX) *
      180 /
      Math.PI +
      450
    ) % 360;

    const position = degrees / 360 * 100;
    let boundary = 0;

    return values.find((entry) => {
      boundary += entry.value;
      return position <= boundary;
    }) || null;
  }

  donut.addEventListener(
    "pointermove",
    (event) => {
      const entry = entryForPointer(event);

      if (entry) {
        showEntry(entry);
      } else {
        restoreCurrentPrediction();
      }
    }
  );

  donut.addEventListener(
    "pointerleave",
    restoreCurrentPrediction
  );

  legendItems.forEach((item) => {
    const entry = entryForRisk(
      item.dataset.risk
    );

    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute(
      "aria-label",
      `${item.dataset.risk} risk: ` +
      `${Math.round(entry.value)}%`
    );

    item.addEventListener(
      "mouseenter",
      () => showEntry(entry)
    );

    item.addEventListener(
      "mouseleave",
      restoreCurrentPrediction
    );

    item.addEventListener(
      "focus",
      () => showEntry(entry)
    );

    item.addEventListener(
      "blur",
      restoreCurrentPrediction
    );

    item.addEventListener(
      "keydown",
      (event) => {
        if (
          event.key === "Enter" ||
          event.key === " "
        ) {
          event.preventDefault();
          showEntry(entry);
        }

        if (event.key === "Escape") {
          restoreCurrentPrediction();
          item.blur();
        }
      }
    );
  });

  donut.setAttribute(
    "aria-label",
    values.map(
      (entry) =>
        `${entry.risk}-risk probability ` +
        `${Math.round(entry.value)}%.`
    ).join(" ")
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
  initialiseSidebarTreeNavigation();

  initialiseLogout();
});
