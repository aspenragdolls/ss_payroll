/**
 * Soft navigation for ss_payroll: HTMX boost helpers, progress bar,
 * hover prefetch, title sync, and chrome re-init after shell swaps.
 */
(function () {
  "use strict";

  var PREFETCH_LIMIT = 24;
  var PREFETCH_TTL_MS = 45000;
  var prefetchCache = new Map();
  var progressTimer = null;
  var progressEl = null;
  var navigating = false;

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function ensureProgress() {
    if (progressEl) return progressEl;
    progressEl = document.createElement("div");
    progressEl.id = "nav-progress";
    progressEl.setAttribute("role", "progressbar");
    progressEl.setAttribute("aria-hidden", "true");
    progressEl.setAttribute("aria-valuemin", "0");
    progressEl.setAttribute("aria-valuemax", "100");
    document.body.appendChild(progressEl);
    return progressEl;
  }

  function setNavigating(on) {
    navigating = on;
    document.documentElement.classList.toggle("is-navigating", on);
    var shell = qs("#app-shell");
    if (shell) shell.setAttribute("aria-busy", on ? "true" : "false");
  }

  function startProgress() {
    var el = ensureProgress();
    el.classList.remove("is-done", "is-hidden");
    el.classList.add("is-active");
    el.style.width = "12%";
    el.setAttribute("aria-hidden", "false");
    el.setAttribute("aria-valuenow", "12");
    setNavigating(true);
    clearInterval(progressTimer);
    var width = 12;
    progressTimer = setInterval(function () {
      if (width >= 86) return;
      width += Math.max(0.6, (90 - width) * 0.045);
      el.style.width = width + "%";
      el.setAttribute("aria-valuenow", String(Math.round(width)));
    }, 120);
  }

  function endProgress() {
    clearInterval(progressTimer);
    progressTimer = null;
    var el = ensureProgress();
    el.style.width = "100%";
    el.setAttribute("aria-valuenow", "100");
    el.classList.add("is-done");
    setNavigating(false);
    window.setTimeout(function () {
      el.classList.remove("is-active", "is-done");
      el.classList.add("is-hidden");
      el.style.width = "0%";
      el.setAttribute("aria-hidden", "true");
    }, 220);
  }

  function normalizeUrl(href) {
    try {
      var url = new URL(href, window.location.origin);
      if (url.origin !== window.location.origin) return null;
      return url.pathname + url.search + url.hash;
    } catch (e) {
      return null;
    }
  }

  function shouldSkipSoftNav(url) {
    if (!url) return true;
    var path = url.split("?")[0].split("#")[0];
    if (path.indexOf("/events") === 0) return true;
    if (path.indexOf("/customers/export") === 0) return true;
    if (/\.(csv|pdf|xlsx|zip|ics)$/i.test(path)) return true;
    return false;
  }

  function prunePrefetch() {
    if (prefetchCache.size <= PREFETCH_LIMIT) return;
    var oldest = prefetchCache.keys().next().value;
    prefetchCache.delete(oldest);
  }

  function storePrefetch(url, html) {
    prefetchCache.set(url, { html: html, at: Date.now() });
    prunePrefetch();
  }

  function getPrefetch(url) {
    var entry = prefetchCache.get(url);
    if (!entry) return null;
    if (Date.now() - entry.at > PREFETCH_TTL_MS) {
      prefetchCache.delete(url);
      return null;
    }
    return entry.html;
  }

  function prefetchUrl(href) {
    var url = normalizeUrl(href);
    if (!url || shouldSkipSoftNav(url)) return;
    if (url === normalizeUrl(window.location.href)) return;
    if (prefetchCache.has(url)) return;

    // Reserve slot so parallel hovers don't stampede.
    prefetchCache.set(url, { html: null, at: Date.now() });
    fetch(url, {
      credentials: "same-origin",
      headers: {
        Accept: "text/html",
        "X-Requested-With": "XMLHttpRequest",
      },
    })
      .then(function (res) {
        if (!res.ok) {
          prefetchCache.delete(url);
          return null;
        }
        var type = (res.headers.get("content-type") || "").toLowerCase();
        if (type.indexOf("text/html") === -1) {
          prefetchCache.delete(url);
          return null;
        }
        return res.text();
      })
      .then(function (html) {
        if (!html || html.indexOf('id="app-shell"') === -1) {
          prefetchCache.delete(url);
          return;
        }
        storePrefetch(url, html);
      })
      .catch(function () {
        prefetchCache.delete(url);
      });
  }

  function extractTitle(html) {
    var match = html.match(/<title[^>]*>([^<]*)<\/title>/i);
    return match ? match[1].trim() : null;
  }

  function syncTitleFromHtml(html) {
    var title = extractTitle(html);
    if (title) document.title = title;
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.body.setAttribute("data-theme", theme);
    var meta = document.getElementById("meta-theme-color");
    if (meta) {
      var onCal = document.body.classList.contains("ios-cal-page");
      if (onCal) {
        meta.setAttribute("content", theme === "dark" ? "#000000" : "#f2f2f7");
      } else {
        meta.setAttribute("content", theme === "dark" ? "#0f1419" : "#f4f6f8");
      }
    }
    var toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.setAttribute(
        "aria-label",
        theme === "light" ? "Switch to dark mode" : "Switch to light mode"
      );
    }
    try {
      localStorage.setItem("ss-payroll-theme", theme);
    } catch (e) {}
  }

  function initThemeToggle() {
    var toggle = document.getElementById("theme-toggle");
    if (!toggle || toggle.dataset.themeBound === "1") return;
    toggle.dataset.themeBound = "1";
    toggle.addEventListener("click", function () {
      var next =
        document.body.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
    });
  }

  function initNavMenus() {
    var nav = qs(".site-nav");
    if (!nav) return;

    var items = qsa(".nav-item", nav);
    var hoverCapable = window.matchMedia("(hover: hover) and (pointer: fine)");

    function setOpen(item, open) {
      item.classList.toggle("is-open", open);
      var trigger = item.querySelector(".nav-trigger");
      if (trigger) trigger.setAttribute("aria-expanded", open ? "true" : "false");
    }

    function closeAll(except) {
      qsa(".site-nav .nav-item").forEach(function (item) {
        if (item !== except) setOpen(item, false);
      });
    }

    items.forEach(function (item) {
      if (item.dataset.navItemBound === "1") return;
      item.dataset.navItemBound = "1";
      var trigger = item.querySelector(".nav-trigger");
      if (!trigger) return;
      trigger.addEventListener("click", function (e) {
        if (hoverCapable.matches) return;
        e.preventDefault();
        e.stopPropagation();
        var willOpen = !item.classList.contains("is-open");
        closeAll(item);
        setOpen(item, willOpen);
      });
    });

    if (!document.body.dataset.navDocBound) {
      document.body.dataset.navDocBound = "1";
      document.addEventListener("click", function (e) {
        var currentNav = qs(".site-nav");
        if (!currentNav || !currentNav.contains(e.target)) closeNavMenus();
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") closeNavMenus();
      });
    }
  }

  function closeNavMenus() {
    qsa(".nav-item.is-open").forEach(function (item) {
      item.classList.remove("is-open");
      var trigger = item.querySelector(".nav-trigger");
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
  }

  function markActiveNav() {
    var path = window.location.pathname;
    qsa(".site-nav a[href]").forEach(function (link) {
      var href = link.getAttribute("href");
      if (!href || href.charAt(0) !== "/") return;
      var linkPath = href.split("?")[0];
      var active =
        linkPath === path ||
        (linkPath !== "/" && path.indexOf(linkPath) === 0);
      link.classList.toggle("is-current", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function bindPrefetch() {
    document.body.addEventListener(
      "pointerenter",
      function (e) {
        var link = e.target.closest && e.target.closest("a[href]");
        if (!link || link.getAttribute("hx-boost") === "false") return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download")) return;
        prefetchUrl(link.getAttribute("href"));
      },
      true
    );

    document.body.addEventListener(
      "focusin",
      function (e) {
        var link = e.target.closest && e.target.closest("a[href]");
        if (!link) return;
        prefetchUrl(link.getAttribute("href"));
      },
      true
    );
  }

  function warmPrimaryRoutes() {
    var routes = ["/", "/workers", "/customers", "/bookings", "/payroll/begin", "/payroll/history"];
    // Idle warm — keep first paint free.
    var run = function () {
      routes.forEach(function (route) {
        if (normalizeUrl(window.location.href) === route) return;
        prefetchUrl(route);
      });
    };
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(run, { timeout: 2500 });
    } else {
      window.setTimeout(run, 1200);
    }
  }

  function hardNavigate(url) {
    endProgress();
    window.location.href = url;
  }

  function swapFromPrefetch(url, html) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var next = doc.querySelector("#app-shell");
    var target = document.querySelector("#app-shell");
    if (!next || !target) return false;

    syncTitleFromHtml(html);
    startProgress();
    closeNavMenus();

    function finish() {
      target.replaceWith(next);
      var shell = qs("#app-shell");
      if (shell && window.htmx) htmx.process(shell);
      try {
        history.pushState({ htmx: true }, "", url);
      } catch (e) {}
      endProgress();
      initChrome();
      markActiveNav();
      document.body.dispatchEvent(
        new CustomEvent("htmx:afterSettle", { bubbles: true })
      );
    }

    if (document.startViewTransition) {
      document.startViewTransition(finish);
    } else {
      finish();
    }
    return true;
  }

  function onBeforeRequest(evt) {
    var path =
      (evt.detail.pathInfo && evt.detail.pathInfo.requestPath) ||
      (evt.detail.requestConfig && evt.detail.requestConfig.path) ||
      "";
    var url = normalizeUrl(path) || path;
    if (shouldSkipSoftNav(url)) {
      evt.preventDefault();
      hardNavigate(url);
      return;
    }

    var verb = (
      (evt.detail.requestConfig && evt.detail.requestConfig.verb) ||
      "get"
    ).toLowerCase();
    var cached = verb === "get" ? getPrefetch(url) : null;
    if (cached) {
      evt.preventDefault();
      // Consume cache so a quick toggle re-fetches fresh HTML next time.
      prefetchCache.delete(url);
      if (!swapFromPrefetch(url, cached)) {
        hardNavigate(url);
      }
      // Refresh in background for next visit.
      window.setTimeout(function () {
        prefetchUrl(url);
      }, 400);
      return;
    }

    startProgress();
    closeNavMenus();
  }

  function onBeforeSwap(evt) {
    var xhr = evt.detail.xhr;
    if (!xhr) return;
    var html = xhr.responseText || "";
    var type = (xhr.getResponseHeader("Content-Type") || "").toLowerCase();
    if (type && type.indexOf("text/html") === -1) {
      evt.detail.shouldSwap = false;
      hardNavigate(
        (evt.detail.pathInfo && evt.detail.pathInfo.requestPath) ||
          window.location.href
      );
      return;
    }
    if (html.indexOf('id="app-shell"') === -1) {
      evt.detail.shouldSwap = false;
      hardNavigate(
        (evt.detail.pathInfo &&
          (evt.detail.pathInfo.finalRequestPath ||
            evt.detail.pathInfo.requestPath)) ||
          window.location.href
      );
      return;
    }
    syncTitleFromHtml(html);
  }

  function onAfterSettle() {
    endProgress();
    initChrome();
    markActiveNav();
    // Keep prefetch cache warm for the page we just left / arrived at.
    prefetchCache.delete(normalizeUrl(window.location.href));
  }

  function onHistoryRestore() {
    endProgress();
    initChrome();
    markActiveNav();
  }

  function onSendError() {
    endProgress();
  }

  /**
   * Serve hover-prefetched HTML when HTMX is about to fetch the same URL.
   * Uses htmx:beforeRequest + xhr override via detail.serverResponse path
   * by short-circuiting with a synthetic successful response when possible.
   */
  function onConfigRequest(evt) {
    var path =
      (evt.detail.pathInfo && evt.detail.pathInfo.requestPath) ||
      evt.detail.path ||
      "";
    var url = normalizeUrl(path);
    if (!url) return;
    var cached = getPrefetch(url);
    if (!cached) return;

    // Hint: still issue the request but prefer freshness; cache is a warm start
    // for back-to-back nav. Real win is already having TCP/TLS + HTML ready
    // from prefetch; leave request alone if headers differ.
    evt.detail.headers["X-Nav-Prefetch"] = "1";
  }

  function initChrome() {
    var theme =
      document.documentElement.getAttribute("data-theme") ||
      document.body.getAttribute("data-theme") ||
      "light";
    applyTheme(theme);
    initThemeToggle();
    initNavMenus();
  }

  function boot() {
    if (window.htmx) {
      // Keep history usable without huge memory cost.
      htmx.config.historyCacheSize = 20;
      htmx.config.scrollBehavior = "smooth";
      // Allow page-level scripts (charts, payroll helpers) after soft nav.
      htmx.config.allowScriptTags = true;
    }

    ensureProgress();
    initChrome();
    markActiveNav();
    bindPrefetch();
    warmPrimaryRoutes();

    document.body.addEventListener("htmx:beforeRequest", onBeforeRequest);
    document.body.addEventListener("htmx:configRequest", onConfigRequest);
    document.body.addEventListener("htmx:beforeSwap", onBeforeSwap);
    document.body.addEventListener("htmx:afterSettle", onAfterSettle);
    document.body.addEventListener("htmx:historyRestore", onHistoryRestore);
    document.body.addEventListener("htmx:responseError", onSendError);
    document.body.addEventListener("htmx:sendError", onSendError);
    document.body.addEventListener("htmx:timeout", onSendError);

    // Instant click feedback even before HTMX queues the request.
    document.body.addEventListener(
      "click",
      function (e) {
        var link = e.target.closest && e.target.closest("a[href]");
        if (!link || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
          return;
        }
        if (link.getAttribute("hx-boost") === "false") return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download")) return;
        var url = normalizeUrl(link.getAttribute("href"));
        if (!url || shouldSkipSoftNav(url)) return;
        if (url.split("#")[0] === normalizeUrl(window.location.href).split("#")[0]) {
          return;
        }
        startProgress();
      },
      true
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
