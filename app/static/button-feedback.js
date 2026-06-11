(function () {
  "use strict";

  function enhanceButton(btn) {
    if (btn.dataset.feedbackEnhanced) return;
    btn.dataset.feedbackEnhanced = "1";
    const icon = document.createElement("span");
    icon.className = "btn-icon";
    icon.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.className = "btn-label";
    label.textContent = btn.textContent.trim();
    btn.textContent = "";
    btn.appendChild(icon);
    btn.appendChild(label);
  }

  function setButtonLoading(btn) {
    btn.classList.remove("is-saved");
    btn.classList.add("is-loading");
    btn.disabled = true;
  }

  function setButtonSaved(btn) {
    btn.classList.remove("is-loading");
    btn.classList.add("is-saved");
    btn.disabled = false;
  }

  function clearButtonSaved(btn) {
    btn.classList.remove("is-saved");
    btn.disabled = false;
  }

  function enhanceAllButtons() {
    document.querySelectorAll("button.btn[type='submit']").forEach(enhanceButton);
  }

  function parseSavedJobs(raw) {
    if (!raw) return [];
    return raw.split(",").map(function (part) {
      return part.trim();
    }).filter(Boolean);
  }

  function getSavedJobsFromPage() {
    const field = document.querySelector("input.saved-jobs-field");
    return field ? parseSavedJobs(field.value) : [];
  }

  function setSavedJobsOnPage(ids) {
    const value = ids.join(",");
    document.querySelectorAll("input.saved-jobs-field").forEach(function (field) {
      field.value = value;
    });
  }

  function jobIdFromEditForm(form) {
    const match = form.getAttribute("action")?.match(/\/jobs\/(\d+)\/edit/);
    return match ? match[1] : null;
  }

  function getJobEditButton(jobId) {
    const form = document.querySelector(
      'form[action*="/jobs/' + jobId + '/edit"]'
    );
    return form && form.querySelector("button.btn[type='submit']");
  }

  function applySavedJobButtons(jobIds) {
    const onPage = new Set();
    document
      .querySelectorAll('form[action*="/jobs/"][action*="/edit"]')
      .forEach(function (form) {
        const jobId = jobIdFromEditForm(form);
        if (jobId) onPage.add(jobId);
      });

    const savedIds = jobIds.filter(function (id) {
      return onPage.has(id);
    });
    if (savedIds.length) {
      setSavedJobsOnPage(savedIds);
    }

    savedIds.forEach(function (jobId) {
      const btn = getJobEditButton(jobId);
      if (btn) {
        enhanceButton(btn);
        setButtonSaved(btn);
      }
    });
  }

  function bindFormResetOnChange(form) {
    const btn = form.querySelector("button.btn[type='submit']");
    if (!btn) return;
    const jobId = jobIdFromEditForm(form);
    function onDirty() {
      clearButtonSaved(btn);
      if (!jobId) return;
      const nextIds = getSavedJobsFromPage().filter(function (id) {
        return id !== jobId;
      });
      setSavedJobsOnPage(nextIds);
    }
    form.addEventListener("input", onDirty, true);
    form.addEventListener("change", onDirty, true);
  }

  function applySavedFromUrl() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("saved") !== "1") return;

    const savedJobs = params.get("saved_jobs");
    const savedJob = params.get("saved_job");
    const savedForm = params.get("saved_form");
    let targetBtn = null;

    if (savedJobs) {
      applySavedJobButtons(parseSavedJobs(savedJobs));
    } else if (savedJob) {
      applySavedJobButtons([savedJob]);
      const form = document.querySelector(
        'form[action*="/jobs/' + savedJob + '/edit"]'
      );
      targetBtn = form && form.querySelector("button.btn[type='submit']");
    } else if (savedForm === "manual") {
      const form = document.querySelector('form[action*="/jobs/manual"]');
      targetBtn = form && form.querySelector("button.btn[type='submit']");
    } else if (savedForm === "disconnect") {
      const form = document.querySelector('form[action*="/calendar/disconnect"]');
      targetBtn = form && form.querySelector("button.btn[type='submit']");
    } else if (savedForm === "connect") {
      const form = document.querySelector('form[action*="/calendar/connect"]');
      targetBtn = form && form.querySelector("button.btn[type='submit']");
    } else {
      const forms = document.querySelectorAll("main form");
      if (forms.length === 1) {
        targetBtn = forms[0].querySelector("button.btn[type='submit']");
      } else {
        targetBtn = document.querySelector(
          "main form button.btn[type='submit']"
        );
      }
    }

    if (targetBtn) {
      enhanceButton(targetBtn);
      setButtonSaved(targetBtn);
    }

    params.delete("saved");
    params.delete("saved_job");
    params.delete("saved_form");
    const query = params.toString();
    const nextUrl =
      window.location.pathname + (query ? "?" + query : "") + window.location.hash;
    history.replaceState({}, "", nextUrl);
  }

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const btn = event.submitter;
    if (!btn || !btn.classList.contains("btn")) return;
    enhanceButton(btn);
    setButtonLoading(btn);
  });

  document.addEventListener("DOMContentLoaded", function () {
    enhanceAllButtons();
    document.querySelectorAll("main form").forEach(bindFormResetOnChange);
    applySavedFromUrl();
    applySavedJobButtons(getSavedJobsFromPage());
  });
})();
