/* Scroll motion: .reveal / .reveal-scale / .reveal-left fade in;
   [data-stagger] containers cascade their children. */
(function () {
  "use strict";
  var singles = document.querySelectorAll(".reveal, .reveal-scale, .reveal-left");
  var groups = document.querySelectorAll("[data-stagger]");

  if (!("IntersectionObserver" in window)) {
    singles.forEach(function (el) { el.classList.add("in"); });
    groups.forEach(function (el) { el.classList.add("in"); });
    return;
  }

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
})();
