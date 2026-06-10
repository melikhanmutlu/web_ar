/* Motion helpers (all gated on prefers-reduced-motion):
   - .reveal / .reveal-scale / .reveal-left + [data-stagger] scroll reveals
   - .word-in headings split into cascading words
   - [data-parallax] scroll parallax (hero stage)
   - [data-magnetic] cursor-magnetic buttons
   - .step-card cursor spotlight (--mx/--my custom props)
   - [data-countup] number count-up on first view */
(function () {
  "use strict";

  var motionOK = !window.matchMedia ||
    window.matchMedia("(prefers-reduced-motion: no-preference)").matches;

  /* ---------- scroll reveals ---------- */
  var singles = document.querySelectorAll(".reveal, .reveal-scale, .reveal-left");
  var groups = document.querySelectorAll("[data-stagger]");
  if (!motionOK || !("IntersectionObserver" in window)) {
    singles.forEach(function (el) { el.classList.add("in"); });
    groups.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add("in");
        io.unobserve(e.target);
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -4% 0px" });
    singles.forEach(function (el) { io.observe(el); });
    groups.forEach(function (group) {
      var step = parseFloat(group.dataset.stagger) || 0.09;
      Array.prototype.forEach.call(group.children, function (child, i) {
        child.style.transitionDelay = (i * step).toFixed(2) + "s";
      });
      io.observe(group);
    });
  }

  if (!motionOK) return; // everything below is decorative motion

  /* ---------- word cascade on .word-in headings ---------- */
  document.querySelectorAll(".word-in").forEach(function (el) {
    var wi = 0;
    Array.prototype.slice.call(el.childNodes).forEach(function (node) {
      if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) return;
      var frag = document.createDocumentFragment();
      node.textContent.split(/(\s+)/).forEach(function (part) {
        if (!part.trim()) { frag.appendChild(document.createTextNode(part)); return; }
        var span = document.createElement("span");
        span.className = "w";
        span.style.setProperty("--wi", wi++);
        span.textContent = part;
        frag.appendChild(span);
      });
      el.replaceChild(frag, node);
    });
    // elements like <span class="hl"> keep their own cascade index
    el.querySelectorAll(":scope > *:not(br)").forEach(function (child) {
      if (child.classList.contains("w")) return;
      child.classList.add("w");
      child.style.setProperty("--wi", wi++);
    });
  });

  /* ---------- scroll parallax ---------- */
  var parallaxEls = document.querySelectorAll("[data-parallax]");
  if (parallaxEls.length) {
    var ticking = false;
    var onScroll = function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        parallaxEls.forEach(function (el) {
          var speed = parseFloat(el.dataset.parallax) || 0.08;
          var rect = el.getBoundingClientRect();
          var offset = (rect.top + rect.height / 2 - window.innerHeight / 2) * -speed;
          el.style.transform = "translateY(" + offset.toFixed(1) + "px)";
        });
        ticking = false;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ---------- magnetic buttons ---------- */
  document.querySelectorAll("[data-magnetic]").forEach(function (el) {
    var strength = 0.22;
    el.addEventListener("mousemove", function (e) {
      var r = el.getBoundingClientRect();
      var x = (e.clientX - r.left - r.width / 2) * strength;
      var y = (e.clientY - r.top - r.height / 2) * strength;
      el.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px)";
    });
    el.addEventListener("mouseleave", function () {
      el.style.transform = "";
    });
  });

  /* ---------- cursor spotlight on dark cards ---------- */
  document.querySelectorAll(".step-card").forEach(function (card) {
    card.addEventListener("mousemove", function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty("--mx", ((e.clientX - r.left) / r.width * 100).toFixed(1) + "%");
      card.style.setProperty("--my", ((e.clientY - r.top) / r.height * 100).toFixed(1) + "%");
    });
  });

  /* ---------- count-up numbers ---------- */
  var counters = document.querySelectorAll("[data-countup]");
  if (counters.length && "IntersectionObserver" in window) {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        cio.unobserve(entry.target);
        var el = entry.target;
        var target = parseFloat(el.dataset.countup);
        var decimals = (el.dataset.countup.split(".")[1] || "").length;
        var t0 = performance.now(), dur = 900;
        (function tick(now) {
          var p = Math.min(1, (now - t0) / dur);
          var eased = 1 - Math.pow(1 - p, 3);
          el.textContent = (target * eased).toFixed(decimals);
          if (p < 1) requestAnimationFrame(tick);
        })(t0);
      });
    }, { threshold: 0.4 });
    counters.forEach(function (el) { cio.observe(el); });
  }
})();
