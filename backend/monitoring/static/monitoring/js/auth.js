"use strict";

function collectErrorMessages(value) {
  if (typeof value === "string") {
    return [value];
  }

  if (Array.isArray(value)) {
    return value.flatMap(collectErrorMessages);
  }

  if (value && typeof value === "object") {
    return Object.values(value).flatMap(
      collectErrorMessages
    );
  }

  return [];
}


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
      "Unable to initialise the secure form."
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


async function submitAuthenticationForm(form) {
  const message = form.querySelector(
    "[data-form-message]"
  );
  const submitButton = form.querySelector(
    'button[type="submit"]'
  );

  message.textContent = "";
  message.classList.remove("is-success");

  if (!form.reportValidity()) {
    return;
  }

  submitButton.disabled = true;
  submitButton.setAttribute("aria-busy", "true");

  try {
    const csrfToken = await getCSRFToken(
      form.dataset.csrfUrl
    );

    const payload = Object.fromEntries(
      new FormData(form).entries()
    );

    const response = await fetch(
      form.dataset.endpoint,
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(payload),
      }
    );

    let data = {};

    try {
      data = await response.json();
    } catch (error) {
      data = {};
    }

    if (!response.ok) {
      const errors = collectErrorMessages(data);

      throw new Error(
        errors.length
          ? errors.join(" ")
          : "The request could not be completed."
      );
    }

    message.textContent =
      "Authentication successful. Redirecting…";
    message.classList.add("is-success");

    window.location.assign(
      form.dataset.successUrl
    );
  } catch (error) {
    message.textContent =
      error.message ||
      "An unexpected error occurred. Please try again.";
  } finally {
    submitButton.disabled = false;
    submitButton.removeAttribute("aria-busy");
  }
}


document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector(
    "[data-auth-form]"
  );

  if (!form) {
    return;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitAuthenticationForm(form);
  });
});