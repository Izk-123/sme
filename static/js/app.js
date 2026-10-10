/**
 * Template Name: NiceAdmin - v2.2.2
 * Template URL: https://bootstrapmade.com/nice-admin-bootstrap-admin-html-template/
 * Author: BootstrapMade.com
 * License: https://bootstrapmade.com/license/
 *
 * ChumaFlow additions:
 *   - IntersectionObserver reveal system
 *   - Staggered cascade for rows/grids/sidebar
 *   - KPI count-up animation
 *   - Button ripple
 *   - Bootstrap alert/toast exit choreography
 *   - HTMX swap integration
 *   - Scroll progress bar
 *   - Notification badge pulse + bell shake
 *   - Form submit feedback
 *   - Responsive table → card stack (data-label auto-fill)
 */
(function() {
  "use strict";

  /**
   * Easy selector helper function
   */
  const select = (el, all = false) => {
    el = el.trim()
    if (all) {
      return [...document.querySelectorAll(el)]
    } else {
      return document.querySelector(el)
    }
  }

  /**
   * Easy event listener function
   */
  const on = (type, el, listener, all = false) => {
    if (all) {
      select(el, all).forEach(e => e.addEventListener(type, listener))
    } else {
      select(el, all).addEventListener(type, listener)
    }
  }

  /**
   * Easy on scroll event listener
   */
  const onscroll = (el, listener) => {
    el.addEventListener('scroll', listener)
  }

  /**
   * Sidebar toggle
   */
  if (select('.toggle-sidebar-btn')) {
    on('click', '.toggle-sidebar-btn', function(e) {
      select('body').classList.toggle('toggle-sidebar')
    })
  }

  /**
   * Dark / light mode toggle
   */
  ;(function initThemeToggle() {
    const root = document.documentElement

    const applyTheme = (theme, btn, animate) => {
      if (animate) {
        root.classList.add('theme-transition')
        window.setTimeout(() => root.classList.remove('theme-transition'), 400)
      }
      root.setAttribute('data-theme', theme)
      try {
        localStorage.setItem('sme-theme', theme)
      } catch (err) { /* localStorage unavailable */ }
      if (btn) {
        btn.classList.add('theme-toggle-spin')
        window.setTimeout(() => btn.classList.remove('theme-toggle-spin'), 400)
      }
    }

    document.addEventListener('click', function(e) {
      const btn = e.target.closest('#themeToggle')
      if (!btn) return
      e.preventDefault()
      const current = root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
      applyTheme(current === 'dark' ? 'light' : 'dark', btn, true)
    })
  })()

  /**
   * Search bar toggle
   */
  if (select('.search-bar-toggle')) {
    on('click', '.search-bar-toggle', function(e) {
      select('.search-bar').classList.toggle('search-bar-show')
    })
  }

  /**
   * Navbar links active state on scroll
   */
  let navbarlinks = select('#navbar .scrollto', true)
  const navbarlinksActive = () => {
    let position = window.scrollY + 200
    navbarlinks.forEach(navbarlink => {
      if (!navbarlink.hash) return
      let section = select(navbarlink.hash)
      if (!section) return
      if (position >= section.offsetTop && position <= (section.offsetTop + section.offsetHeight)) {
        navbarlink.classList.add('active')
      } else {
        navbarlink.classList.remove('active')
      }
    })
  }
  window.addEventListener('load', navbarlinksActive)
  onscroll(document, navbarlinksActive)

  /**
   * Toggle .header-scrolled class to #header when page is scrolled
   */
  let selectHeader = select('#header')
  if (selectHeader) {
    const headerScrolled = () => {
      if (window.scrollY > 100) {
        selectHeader.classList.add('header-scrolled')
      } else {
        selectHeader.classList.remove('header-scrolled')
      }
    }
    window.addEventListener('load', headerScrolled)
    onscroll(document, headerScrolled)
  }

  /**
   * Back to top button
   */
  let backtotop = select('.back-to-top')
  if (backtotop) {
    const toggleBacktotop = () => {
      if (window.scrollY > 100) {
        backtotop.classList.add('active')
      } else {
        backtotop.classList.remove('active')
      }
    }
    window.addEventListener('load', toggleBacktotop)
    onscroll(document, toggleBacktotop)
  }

  /**
   * Initiate tooltips
   */
  var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
  var tooltipList = tooltipTriggerList.map(function(tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl)
  })

  /**
   * Initiate quill editors (if Quill is available)
   */
  if (select('.quill-editor-default') && window.Quill) {
    new Quill('.quill-editor-default', { theme: 'snow' });
  }

  if (select('.quill-editor-bubble') && window.Quill) {
    new Quill('.quill-editor-bubble', { theme: 'bubble' });
  }

  if (select('.quill-editor-full') && window.Quill) {
    new Quill(".quill-editor-full", {
      modules: {
        toolbar: [
          [{ font: [] }, { size: [] }],
          ["bold", "italic", "underline", "strike"],
          [{ color: [] }, { background: [] }],
          [{ script: "super" }, { script: "sub" }],
          [{ list: "ordered" }, { list: "bullet" }, { indent: "-1" }, { indent: "+1" }],
          ["direction", { align: [] }],
          ["link", "image", "video"],
          ["clean"]
        ]
      },
      theme: "snow"
    });
  }

  /**
   * Initiate TinyMCE Editor (if available)
   */
  var useDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;

  if (window.tinymce && select('textarea.tinymce-editor')) {
    tinymce.init({
      selector: 'textarea.tinymce-editor',
      plugins: 'print preview paste importcss searchreplace autolink autosave save directionality code visualblocks visualchars fullscreen image link media template codesample table charmap hr pagebreak nonbreaking anchor toc insertdatetime advlist lists wordcount imagetools textpattern noneditable help charmap quickbars emoticons',
      imagetools_cors_hosts: ['picsum.photos'],
      menubar: 'file edit view insert format tools table help',
      toolbar: 'undo redo | bold italic underline strikethrough | fontselect fontsizeselect formatselect | alignleft aligncenter alignright alignjustify | outdent indent |  numlist bullist | forecolor backcolor removeformat | pagebreak | charmap emoticons | fullscreen  preview save print | insertfile image media template link anchor codesample | ltr rtl',
      toolbar_sticky: true,
      autosave_ask_before_unload: true,
      autosave_interval: '30s',
      autosave_prefix: '{path}{query}-{id}-',
      autosave_restore_when_empty: false,
      autosave_retention: '2m',
      image_advtab: true,
      link_list: [
        { title: 'My page 1', value: 'https://www.tiny.cloud' },
        { title: 'My page 2', value: 'http://www.moxiecode.com' }
      ],
      image_list: [
        { title: 'My page 1', value: 'https://www.tiny.cloud' },
        { title: 'My page 2', value: 'http://www.moxiecode.com' }
      ],
      image_class_list: [
        { title: 'None', value: '' },
        { title: 'Some class', value: 'class-name' }
      ],
      importcss_append: true,
      file_picker_callback: function(callback, value, meta) {
        if (meta.filetype === 'file') {
          callback('https://www.google.com/logos/google.jpg', { text: 'My text' });
        }
        if (meta.filetype === 'image') {
          callback('https://www.google.com/logos/google.jpg', { alt: 'My alt text' });
        }
        if (meta.filetype === 'media') {
          callback('movie.mp4', {
            source2: 'alt.ogg',
            poster: 'https://www.google.com/logos/google.jpg'
          });
        }
      },
      templates: [
        { title: 'New Table', description: 'creates a new table', content: '<div class="mceTmpl"><table width="98%%"  border="0" cellspacing="0" cellpadding="0"><tr><th scope="col"> </th><th scope="col"> </th></tr><tr><td> </td><td> </td></tr></table></div>' },
        { title: 'Starting my story', description: 'A cure for writers block', content: 'Once upon a time...' },
        { title: 'New list with dates', description: 'New List with dates', content: '<div class="mceTmpl"><span class="cdate">cdate</span><br /><span class="mdate">mdate</span><h2>My List</h2><ul><li></li><li></li></ul></div>' }
      ],
      template_cdate_format: '[Date Created (CDATE): %m/%d/%Y : %H:%M:%S]',
      template_mdate_format: '[Date Modified (MDATE): %m/%d/%Y : %H:%M:%S]',
      height: 600,
      image_caption: true,
      quickbars_selection_toolbar: 'bold italic | quicklink h2 h3 blockquote quickimage quicktable',
      noneditable_noneditable_class: 'mceNonEditable',
      toolbar_mode: 'sliding',
      contextmenu: 'link image imagetools table',
      skin: useDarkMode ? 'oxide-dark' : 'oxide',
      content_css: useDarkMode ? 'dark' : 'default',
      content_style: 'body { font-family:Helvetica,Arial,sans-serif; font-size:14px }'
    });
  }

  /**
   * Initiate Bootstrap validation check
   */
  var needsValidation = document.querySelectorAll('.needs-validation')

  Array.prototype.slice.call(needsValidation)
    .forEach(function(form) {
      form.addEventListener('submit', function(event) {
        if (!form.checkValidity()) {
          event.preventDefault()
          event.stopPropagation()
        }
        form.classList.add('was-validated')
      }, false)
    })

  /**
   * Initiate Datatables - safe version
   */
  const datatables = select('.datatable', true)
  datatables.forEach(datatable => {
    const headers = datatable.querySelectorAll('thead th');
    const firstRow = datatable.querySelector('tbody tr');
    const cells = firstRow ? firstRow.querySelectorAll('td') : [];

    if (headers.length === cells.length && headers.length > 0 && window.simpleDatatables) {
      try {
        new simpleDatatables.DataTable(datatable);
      } catch (e) {
        console.warn('DataTable initialization failed:', e.message);
      }
    }
  });

  /**
   * Autoresize echart charts (if echarts is available)
   */
  const mainContainer = select('#main');
  if (mainContainer && window.echarts) {
    setTimeout(() => {
      new ResizeObserver(function() {
        select('.echart', true).forEach(getEchart => {
          if (window.echarts.getInstanceByDom(getEchart)) {
            window.echarts.getInstanceByDom(getEchart).resize();
          }
        })
      }).observe(mainContainer);
    }, 200);
  }

})();

/* ==========================================================================
   CHUMAFLOW — animation orchestrator
   ========================================================================== */
(function () {
  "use strict";

  const reduceMotion  = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const animDisabled  = () => document.documentElement.getAttribute("data-animations") === "off";
  const hasIO         = "IntersectionObserver" in window;

  if (reduceMotion || animDisabled()) {
    document.querySelectorAll(".cf-reveal").forEach(el => el.classList.add("is-visible"));
    return;
  }

  /* ------------------------------------------------------------------
     A. Reveal on scroll
     ------------------------------------------------------------------ */

  const REVEAL_SELECTORS = [
    ".section.dashboard .card",
    ".section .row > [class*='col-']",
    ".list-group",
    ".alert",
    ".pagetitle"
  ].join(",");

  const seen = new WeakSet();

  function tagRevealable(root = document) {
    root.querySelectorAll(REVEAL_SELECTORS).forEach(el => {
      if (seen.has(el)) return;
      seen.add(el);
      el.classList.add("cf-reveal");
    });
  }

  let observer = null;
  function ensureObserver() {
    if (observer || !hasIO) return;
    observer = new IntersectionObserver(
      entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.08, rootMargin: "0px 0px -40px 0px" }
    );
  }

  function observeAll() {
    ensureObserver();
    if (!observer) {
      document.querySelectorAll(".cf-reveal").forEach(el => el.classList.add("is-visible"));
      return;
    }
    document.querySelectorAll(".cf-reveal:not(.is-visible)").forEach(el => observer.observe(el));
  }

  /* ------------------------------------------------------------------
     B. Stagger
     ------------------------------------------------------------------ */

  const STAGGER_PARENTS = ".section .row, .row.g-4, .row.g-3, [data-stagger]";
  const STAGGER_STEP_MS = 70;
  const STAGGER_MAX_MS  = 420;

  function applyStagger(root = document) {
    root.querySelectorAll(STAGGER_PARENTS).forEach(parent => {
      if (parent.dataset.cfStaggered === "1") return;
      parent.dataset.cfStaggered = "1";

      const kids = Array.from(parent.children).filter(
        el => el.classList.contains("cf-reveal") || el.querySelector?.(".cf-reveal")
      );
      if (kids.length < 2) return;

      kids.forEach((kid, i) => {
        const delay = Math.min(i * STAGGER_STEP_MS, STAGGER_MAX_MS);
        const target = kid.classList.contains("cf-reveal")
          ? kid
          : kid.querySelector(".cf-reveal");
        if (target) target.style.setProperty("--cf-delay", delay + "ms");
      });
    });
  }

  /* ------------------------------------------------------------------
     C. Number count-up
     ------------------------------------------------------------------ */

  const COUNT_TARGETS = ".dashboard .info-card h6, [data-count-up]";
  const counted = new WeakSet();

  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

  function formatNumber(value, { decimals, hasComma }) {
    let out = decimals > 0 ? value.toFixed(decimals) : Math.round(value).toString();
    if (hasComma) out = out.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return out;
  }

  function animateCount(el) {
    if (counted.has(el)) return;
    const text = (el.textContent || "").trim();
    const match = text.match(/(-?\d[\d,]*(?:\.\d+)?)/);
    if (!match) return;

    const raw = match[0];
    const target = parseFloat(raw.replace(/,/g, ""));
    if (!isFinite(target) || target === 0) { counted.add(el); return; }

    counted.add(el);

    const prefix = text.slice(0, match.index);
    const suffix = text.slice(match.index + raw.length);
    const hasComma = raw.includes(",");
    const decimals = raw.includes(".") ? raw.split(".")[1].length : 0;
    const duration = 850;
    const start = performance.now();

    const original = el.textContent;
    const originalMinWidth = el.style.minWidth;
    el.style.minWidth = el.offsetWidth + "px";

    function tick(now) {
      const t = Math.min((now - start) / duration, 1);
      const eased = easeOutCubic(t);
      const value = target * eased;
      el.textContent = prefix + formatNumber(value, { decimals, hasComma }) + suffix;
      if (t < 1) {
        requestAnimationFrame(tick);
      } else {
        el.textContent = original;
        el.style.minWidth = originalMinWidth;
        el.classList.add("cf-count-flash");
        setTimeout(() => el.classList.remove("cf-count-flash"), 800);
      }
    }
    requestAnimationFrame(tick);
  }

  function initCountUp(root = document) {
    root.querySelectorAll(COUNT_TARGETS).forEach(animateCount);
  }

  /* ------------------------------------------------------------------
     D. Button ripple
     ------------------------------------------------------------------ */

  const RIPPLE_SELECTORS = ".btn, .pill, .sidebar-nav .nav-link, .header-nav .nav-icon";

  function attachRipple(el) {
    if (el.dataset.cfRipple === "1") return;
    el.dataset.cfRipple = "1";

    const pos = getComputedStyle(el).position;
    if (pos === "static") el.style.position = "relative";
    if (getComputedStyle(el).overflow !== "hidden") el.style.overflow = "hidden";

    el.addEventListener("pointerdown", e => {
      if (e.button !== undefined && e.button !== 0) return;
      const rect = el.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      const x = e.clientX - rect.left - size / 2;
      const y = e.clientY - rect.top  - size / 2;

      const ink = document.createElement("span");
      ink.className = "cf-ripple-ink";
      ink.style.width  = size + "px";
      ink.style.height = size + "px";
      ink.style.left   = x + "px";
      ink.style.top    = y + "px";
      el.appendChild(ink);

      setTimeout(() => ink.remove(), 700);
    });
  }

  function initRipple(root = document) {
    root.querySelectorAll(RIPPLE_SELECTORS).forEach(attachRipple);
  }

  /* ------------------------------------------------------------------
     E. Exit animations
     ------------------------------------------------------------------ */

  function initExits() {
    document.addEventListener("click", e => {
      const btn = e.target.closest('[data-bs-dismiss="alert"]');
      if (!btn) return;
      const alert = btn.closest(".alert");
      if (!alert || alert.dataset.cfExiting === "1") return;
      alert.dataset.cfExiting = "1";
      alert.classList.add("is-exiting");
    }, true);

    if (window.bootstrap && window.bootstrap.Alert) {
      const originalClose = window.bootstrap.Alert.prototype.close;
      window.bootstrap.Alert.prototype.close = function () {
        const el = this._element;
        if (el && !el.classList.contains("is-exiting")) {
          el.classList.add("is-exiting");
          setTimeout(() => {
            try { originalClose.call(this); }
            catch (_) { el.remove(); }
          }, 240);
          return;
        }
        return originalClose.call(this);
      };
    }

    if (window.bootstrap && window.bootstrap.Toast) {
      const originalHide = window.bootstrap.Toast.prototype.hide;
      window.bootstrap.Toast.prototype.hide = function () {
        const el = this._element;
        if (el && !el.classList.contains("is-exiting")) {
          el.classList.add("is-exiting");
          setTimeout(() => {
            try { originalHide.call(this); }
            catch (_) { el.remove(); }
          }, 220);
          return;
        }
        return originalHide.call(this);
      };
    }
  }

  /* ------------------------------------------------------------------
     F. HTMX integration
     ------------------------------------------------------------------ */

  function initHtmx() {
    if (!window.htmx) return;

    document.body.addEventListener("htmx:beforeSwap", e => {
      const t = e.detail?.target;
      if (t && t.classList) {
        t.style.transition = "opacity 140ms ease-out, transform 140ms ease-out";
        t.style.opacity = "0.4";
        t.style.transform = "translateY(4px)";
      }
    });

    const refresh = (root = document) => {
      tagRevealable(root);
      applyStagger(root);
      initRipple(root);
      initCountUp(root);
      observeAll();
    };

    document.body.addEventListener("htmx:afterSwap", e => {
      const t = e.detail?.target;
      if (t) {
        t.style.opacity = "";
        t.style.transform = "";
        t.style.transition = "";
      }
      refresh(document);
    });

    document.body.addEventListener("htmx:afterSettle", () => refresh(document));
    document.body.addEventListener("htmx:load", e => refresh(e.target?.closest?.(".section") || document));
  }

  /* ------------------------------------------------------------------
     G. Scroll progress bar
     ------------------------------------------------------------------ */

  function initScrollProgress() {
    const bar = document.createElement("div");
    bar.className = "cf-scroll-progress is-idle";
    document.body.appendChild(bar);

    let idleTimer = null;
    function update() {
      const doc = document.documentElement;
      const scrollable = doc.scrollHeight - doc.clientHeight;
      const pct = scrollable > 0 ? (doc.scrollTop / scrollable) * 100 : 0;
      bar.style.width = pct + "%";
      bar.classList.remove("is-idle");
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        bar.classList.add("is-idle");
      }, 900);
    }
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  /* ------------------------------------------------------------------
     H. Badge pulse + bell shake
     ------------------------------------------------------------------ */

  function initBadgeWatcher() {
    const badge = document.querySelector(".header-nav .badge-number");
    if (!badge || !("MutationObserver" in window)) return;

    let lastValue = badge.textContent;
    const bell = badge.closest(".nav-item")?.querySelector(".bi-bell")
              || badge.closest("li")?.querySelector(".bi-bell");

    const mo = new MutationObserver(() => {
      const current = badge.textContent;
      if (current === lastValue) return;
      lastValue = current;

      badge.classList.remove("cf-badge-pulse");
      void badge.offsetWidth;
      badge.classList.add("cf-badge-pulse");

      if (bell) {
        const parent = bell.closest(".nav-icon") || bell;
        parent.classList.remove("cf-bell-shake");
        void parent.offsetWidth;
        parent.classList.add("cf-bell-shake");
        setTimeout(() => parent.classList.remove("cf-bell-shake"), 800);
      }
    });

    mo.observe(badge, { childList: true, characterData: true, subtree: true });
  }

  /* ------------------------------------------------------------------
     I. Form feedback
     ------------------------------------------------------------------ */

  function initFormFeedback() {
    document.addEventListener("submit", e => {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (form.dataset.cfSubmitting === "1") return;
      form.dataset.cfSubmitting = "1";

      const btn = form.querySelector('button[type="submit"], input[type="submit"]');
      if (!btn) return;

      if (btn.dataset.cfOriginalHtml === undefined) {
        btn.dataset.cfOriginalHtml = btn.innerHTML;
      }
      btn.disabled = true;
      btn.style.opacity = "0.75";
      btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${btn.dataset.cfOriginalHtml}`;

      setTimeout(() => {
        form.dataset.cfSubmitting = "";
        btn.disabled = false;
        btn.style.opacity = "";
        btn.innerHTML = btn.dataset.cfOriginalHtml;
      }, 12000);
    });
  }

  /* ------------------------------------------------------------------
     J. Boot
     ------------------------------------------------------------------ */

  function boot() {
    tagRevealable();
    applyStagger();
    initRipple();
    initCountUp();
    observeAll();
    initExits();
    initHtmx();
    initScrollProgress();
    initBadgeWatcher();
    initFormFeedback();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.ChumaFlow = {
    reveal:  () => observeAll(),
    refresh: (root = document) => {
      tagRevealable(root);
      applyStagger(root);
      initRipple(root);
      initCountUp(root);
      observeAll();
    },
    animateCount,
  };
})();

/* ==========================================================================
   CHUMAFLOW — responsive table → card stack
   --------------------------------------------------------------------------
   Reads each <table class="table-stack">'s <thead> labels and writes them
   onto every corresponding <td>/<th> as `data-label`, which the CSS uses
   to render the label on mobile card view.

   Survives DataTables re-renders (simple-datatables rebuilds <tbody> on
   pagination/search, which would otherwise drop the labels).
   ========================================================================== */
(function () {
  "use strict";

  function populateLabels(table) {
    const headers = Array.from(table.querySelectorAll("thead th"))
      .map(th => th.textContent.trim());
    if (!headers.length) return;

    table.querySelectorAll("tbody tr").forEach(row => {
      const cells = row.querySelectorAll(":scope > th, :scope > td");
      // Skip empty-state rows like <td colspan="5">Nothing here</td>
      if (cells.length === 1 && cells[0].hasAttribute("colspan")) return;

      cells.forEach((cell, i) => {
        if (headers[i] && !cell.hasAttribute("data-label")) {
          cell.setAttribute("data-label", headers[i]);
        }
      });
    });
  }

  function initStackTables(root = document) {
    root.querySelectorAll(".table-stack").forEach(table => {
      populateLabels(table);
      observeDataTableReRenders(table);
    });
  }

  function observeDataTableReRenders(table) {
    if (table.dataset.cfStackObserved === "1") return;
    table.dataset.cfStackObserved = "1";

    const tbody = table.querySelector("tbody");
    if (!tbody || !("MutationObserver" in window)) return;

    const mo = new MutationObserver(() => {
      populateLabels(table);
    });
    mo.observe(tbody, { childList: true, subtree: false });

    const thead = table.querySelector("thead");
    if (thead) {
      new MutationObserver(() => populateLabels(table))
        .observe(thead, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initStackTables();
      setTimeout(initStackTables, 0);
    });
  } else {
    initStackTables();
    setTimeout(initStackTables, 0);
  }

  document.body.addEventListener("htmx:afterSwap", () => initStackTables(document));
  document.body.addEventListener("htmx:load",     () => initStackTables(document));

  window.ChumaFlow = window.ChumaFlow || {};
  window.ChumaFlow.stackTables = initStackTables;
})();