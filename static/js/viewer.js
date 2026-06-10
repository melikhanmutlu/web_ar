/* Viewer: stage controls (rotate, dimensions overlay, environment, exposure,
   background, screenshot, fullscreen), QR/copy share, owner edit panel. */
(function () {
  "use strict";

  var csrf = document.querySelector('meta[name="csrf-token"]').content;
  var mv = document.getElementById("mv");
  var stage = document.getElementById("stage");

  function $(id) { return document.getElementById(id); }

  /* ---------- load progress ---------- */
  if (mv) {
    var bar = mv.querySelector(".mv-progress-bar");
    mv.addEventListener("progress", function (e) {
      if (!bar) return;
      var p = e.detail.totalProgress;
      bar.style.width = p * 100 + "%";
      if (p >= 1) setTimeout(function () { bar.style.opacity = "0"; }, 400);
    });
  }

  /* ---------- stage controls ---------- */
  var rotateBtn = $("ctl-rotate");
  if (rotateBtn) {
    rotateBtn.addEventListener("click", function () {
      if (mv.hasAttribute("auto-rotate")) mv.removeAttribute("auto-rotate");
      else mv.setAttribute("auto-rotate", "");
      rotateBtn.classList.toggle("active");
    });
  }

  var envs = [
    { key: "neutral", label: "☼ STÜDYO", exposure: 1 },
    { key: "legacy", label: "☼ KLASİK", exposure: 1 },
    { key: null, label: "☼ SAHNE", exposure: 1.15 }
  ];
  var envIdx = 0;
  var envBtn = $("ctl-env");
  if (envBtn) {
    envBtn.addEventListener("click", function () {
      envIdx = (envIdx + 1) % envs.length;
      var env = envs[envIdx];
      if (env.key) mv.setAttribute("environment-image", env.key);
      else mv.removeAttribute("environment-image");
      $("ctl-exposure").value = env.exposure;
      mv.exposure = env.exposure;
      envBtn.textContent = env.label;
    });
  }

  var bgBtn = $("ctl-bg");
  if (bgBtn) {
    bgBtn.addEventListener("click", function () {
      stage.classList.toggle("light-bg");
      bgBtn.classList.toggle("active");
    });
  }

  var exposure = $("ctl-exposure");
  if (exposure) {
    exposure.addEventListener("input", function () { mv.exposure = parseFloat(exposure.value); });
  }

  var fsBtn = $("ctl-fs");
  if (fsBtn) {
    fsBtn.addEventListener("click", function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else stage.requestFullscreen && stage.requestFullscreen();
    });
  }

  var shotBtn = $("ctl-shot");
  if (shotBtn) {
    shotBtn.addEventListener("click", function () {
      try {
        var url = mv.toDataURL("image/png");
        var a = document.createElement("a");
        a.href = url;
        a.download = (window.__MODEL__ ? window.__MODEL__.name : "model") + ".png";
        a.click();
      } catch (_) { alert("Ekran görüntüsü alınamadı."); }
    });
  }

  /* ---------- real-world dimension labels ---------- */
  var dimsBtn = $("ctl-dims");
  var dimsOn = false;
  function fmt(value) {
    return value >= 1 ? value.toFixed(2) + " m" : (value * 100).toFixed(1) + " cm";
  }
  function addDimHotspot(name, position, text) {
    var ok = mv.updateHotspot ? true : false;
    var el = document.createElement("div");
    el.className = "dim-hotspot";
    el.slot = "hotspot-" + name;
    el.dataset.position = position.join(" ");
    el.textContent = text;
    mv.appendChild(el);
    if (ok) mv.updateHotspot({ name: "hotspot-" + name, position: position.join(" ") });
  }
  function showDims() {
    var size = mv.getDimensions && mv.getDimensions();
    var center = mv.getBoundingBoxCenter && mv.getBoundingBoxCenter();
    if (!size || !center) return;
    var x2 = size.x / 2, y2 = size.y / 2, z2 = size.z / 2;
    addDimHotspot("dim-x", [center.x, center.y - y2, center.z + z2], "X — " + fmt(size.x));
    addDimHotspot("dim-y", [center.x + x2, center.y, center.z + z2], "Y — " + fmt(size.y));
    addDimHotspot("dim-z", [center.x + x2, center.y - y2, center.z], "Z — " + fmt(size.z));
  }
  function hideDims() {
    mv.querySelectorAll(".dim-hotspot").forEach(function (el) { el.remove(); });
  }
  if (dimsBtn) {
    dimsBtn.addEventListener("click", function () {
      dimsOn = !dimsOn;
      dimsBtn.classList.toggle("active", dimsOn);
      if (dimsOn) {
        if (mv.loaded) showDims();
        else mv.addEventListener("load", showDims, { once: true });
      } else hideDims();
    });
  }

  /* ---------- share ---------- */
  var qrModal = $("qr-modal");
  var showQr = $("show-qr");
  if (showQr && qrModal) {
    showQr.addEventListener("click", function () { qrModal.hidden = false; });
    qrModal.querySelectorAll("[data-close]").forEach(function (el) {
      el.addEventListener("click", function () { qrModal.hidden = true; });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") qrModal.hidden = true;
    });
  }

  var copyBtn = $("copy-link");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      navigator.clipboard.writeText(copyBtn.dataset.url).then(function () {
        var original = copyBtn.textContent;
        copyBtn.textContent = "Kopyalandı ✓";
        setTimeout(function () { copyBtn.textContent = original; }, 1800);
      });
    });
  }

  /* ---------- owner edit panel ---------- */
  var saveBtn = $("ed-save");
  if (saveBtn) {
    var colorOn = $("ed-color-on");
    var colorInput = $("ed-color");
    colorOn.addEventListener("change", function () { colorInput.hidden = !colorOn.checked; });

    var initialSize = $("ed-size").value;
    saveBtn.addEventListener("click", function () {
      var statusEl = $("ed-status");
      var payload = {
        name: $("ed-name").value.trim(),
        folder_id: $("ed-folder").value ? parseInt($("ed-folder").value, 10) : null
      };
      if ($("ed-size").value && $("ed-size").value !== initialSize) {
        payload.target_size = parseFloat($("ed-size").value);
      }
      if (colorOn.checked) payload.color = colorInput.value;

      saveBtn.disabled = true;
      statusEl.textContent = "Kaydediliyor…";
      fetch("/api/models/" + window.__MODEL__.id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(payload)
      })
        .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
        .then(function (res) {
          saveBtn.disabled = false;
          if (!res.ok) { statusEl.textContent = res.body.error || "Kaydedilemedi."; return; }
          statusEl.textContent = "Kaydedildi ✓";
          if (payload.target_size || payload.color) {
            statusEl.textContent = "Kaydedildi ✓ — sayfa yenileniyor…";
            setTimeout(function () { window.location.reload(); }, 900);
          }
        })
        .catch(function () { saveBtn.disabled = false; statusEl.textContent = "Bağlantı hatası."; });
    });
  }
})();
