(function () {
  "use strict";

  function updatePayFields(row) {
    const panel = row.querySelector(".pay-override-panel");
    const checkbox = row.querySelector(".labor-checkbox");
    const payType = row.querySelector(".pay-type-select");
    if (!panel || !checkbox || !payType) return;

    const checked = checkbox.checked;
    panel.hidden = !checked;

    const hourlyField = row.querySelector(".pay-field-hourly");
    const pctField = row.querySelector(".pay-field-percentage");
    const isHourly = payType.value === "hourly";

    if (hourlyField) hourlyField.hidden = !isHourly;
    if (pctField) pctField.hidden = isHourly;

    const rateInput = row.querySelector(".hourly-rate-input");
    const tierSelect = row.querySelector(".tier-select");
    if (rateInput) rateInput.disabled = !checked || !isHourly;
    if (tierSelect) tierSelect.disabled = !checked || isHourly;
    payType.disabled = !checked || checkbox.disabled;
  }

  function applyDefaults(row) {
    const payType = row.querySelector(".pay-type-select");
    const rateInput = row.querySelector(".hourly-rate-input");
    const tierSelect = row.querySelector(".tier-select");
    if (!payType) return;

    const defaultPayType = row.dataset.defaultPayType || "hourly";
    const defaultTier = row.dataset.defaultTier || "";
    const defaultRate = row.dataset.defaultRate || "";

    if (!payType.dataset.userTouched) {
      payType.value = defaultPayType;
    }
    if (rateInput && !rateInput.dataset.userTouched && defaultRate) {
      rateInput.value = defaultRate;
    }
    if (tierSelect && !tierSelect.dataset.userTouched && defaultTier) {
      tierSelect.value = defaultTier;
    }
    updatePayFields(row);
  }

  function onCheckboxChange(row) {
    const checkbox = row.querySelector(".labor-checkbox");
    if (checkbox && checkbox.checked && !row.dataset.initialized) {
      applyDefaults(row);
      row.dataset.initialized = "1";
    }
    updatePayFields(row);
  }

  function onPayTypeChange(row) {
    const payType = row.querySelector(".pay-type-select");
    if (payType) payType.dataset.userTouched = "1";

    const rateInput = row.querySelector(".hourly-rate-input");
    const tierSelect = row.querySelector(".tier-select");
    const isHourly = payType && payType.value === "hourly";

    if (isHourly && rateInput && !rateInput.value && row.dataset.defaultRate) {
      rateInput.value = row.dataset.defaultRate;
    }
    if (!isHourly && tierSelect && !tierSelect.value && row.dataset.defaultTier) {
      tierSelect.value = row.dataset.defaultTier;
    }
    updatePayFields(row);
  }

  function initRow(row) {
    const checkbox = row.querySelector(".labor-checkbox");
    const payType = row.querySelector(".pay-type-select");
    const rateInput = row.querySelector(".hourly-rate-input");
    const tierSelect = row.querySelector(".tier-select");

    if (checkbox && checkbox.checked) {
      row.dataset.initialized = "1";
    }

    if (checkbox) {
      checkbox.addEventListener("change", function () {
        onCheckboxChange(row);
      });
    }
    if (payType) {
      payType.addEventListener("change", function () {
        onPayTypeChange(row);
      });
    }
    if (rateInput) {
      rateInput.addEventListener("input", function () {
        rateInput.dataset.userTouched = "1";
      });
    }
    if (tierSelect) {
      tierSelect.addEventListener("change", function () {
        tierSelect.dataset.userTouched = "1";
      });
    }

    updatePayFields(row);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".labor-assignment").forEach(initRow);
  });
})();
