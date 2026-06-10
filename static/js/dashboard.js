/* Studio: search, upload modal (drag&drop + options + job polling),
   AI generation modal (text / image tabs + Meshy job polling). */
(function () {
  "use strict";

  var csrf = document.querySelector('meta[name="csrf-token"]').content;

  function $(id) { return document.getElementById(id); }
  function wireModal(modal, onClose) {
    modal.querySelectorAll("[data-close]").forEach(function (el) {
      el.addEventListener("click", function () { if (onClose()) modal.hidden = true; });
    });
  }

  /* ---------- search filter ---------- */
  var search = $("model-search");
  if (search) {
    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase();
      document.querySelectorAll("#model-grid .model-card").forEach(function (card) {
        card.style.display = !q || card.dataset.name.indexOf(q) !== -1 ? "" : "none";
      });
    });
  }

  /* =====================================================
     UPLOAD
     ===================================================== */
  var upModal = $("upload-modal");
  if (upModal) {
    var dropzone = $("dropzone");
    var fileInput = $("file-input");
    var dzFile = $("dz-file");
    var startBtn = $("upload-start");
    var formArea = $("upload-form-area");
    var progArea = $("upload-progress-area");
    var bar = $("progress-bar");
    var statusEl = $("upload-status");
    var detailEl = $("upload-detail");
    var colorOn = $("up-color-on");
    var colorInput = $("up-color");
    var selectedFile = null;
    var busy = false;

    $("open-upload").addEventListener("click", function () { upModal.hidden = false; });
    wireModal(upModal, function () { return !busy; });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !busy) upModal.hidden = true;
    });

    colorOn.addEventListener("change", function () { colorInput.hidden = !colorOn.checked; });

    function setFile(file) {
      selectedFile = file;
      dzFile.hidden = false;
      dzFile.textContent = "→ " + file.name + " (" + (file.size / 1048576).toFixed(1) + " MB)";
      startBtn.disabled = false;
    }
    dropzone.addEventListener("click", function () { fileInput.click(); });
    fileInput.addEventListener("change", function () {
      if (fileInput.files.length) setFile(fileInput.files[0]);
    });
    ["dragover", "dragenter"].forEach(function (ev) {
      dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.add("dragover"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.remove("dragover"); });
    });
    dropzone.addEventListener("drop", function (e) {
      if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
    });

    function upFail(message) {
      busy = false;
      statusEl.textContent = "Hata";
      bar.classList.remove("indeterminate");
      bar.style.width = "0";
      detailEl.textContent = message;
      setTimeout(function () {
        formArea.hidden = false;
        progArea.hidden = true;
      }, 4200);
    }

    startBtn.addEventListener("click", function () {
      if (!selectedFile) return;
      busy = true;
      formArea.hidden = true;
      progArea.hidden = false;
      statusEl.textContent = "Yükleniyor… " + selectedFile.name;
      detailEl.textContent = "";

      var data = new FormData();
      data.append("file", selectedFile);
      if ($("up-folder").value) data.append("folder_id", $("up-folder").value);
      if ($("up-name").value.trim()) data.append("name", $("up-name").value.trim());
      if ($("up-size").value) data.append("target_size", $("up-size").value);
      if (colorOn.checked) data.append("color", colorInput.value);

      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      xhr.setRequestHeader("X-CSRFToken", csrf);
      xhr.upload.addEventListener("progress", function (e) {
        if (e.lengthComputable) bar.style.width = Math.round((e.loaded / e.total) * 100) + "%";
      });
      xhr.addEventListener("load", function () {
        var body = {};
        try { body = JSON.parse(xhr.responseText); } catch (_) {}
        if (xhr.status === 202 && body.job_id) pollConvert(body.job_id);
        else upFail(body.error || "Yükleme başarısız oldu (" + xhr.status + ").");
      });
      xhr.addEventListener("error", function () { upFail("Bağlantı hatası — tekrar deneyin."); });
      xhr.send(data);
    });

    function pollConvert(jobId) {
      statusEl.textContent = "Dönüştürülüyor…";
      detailEl.textContent = "GLB üretiliyor, boyutlar analiz ediliyor, USDZ ve QR hazırlanıyor.";
      bar.style.width = "100%";
      bar.classList.add("indeterminate");
      (function tick() {
        fetch("/api/jobs/" + jobId, { headers: { Accept: "application/json" } })
          .then(function (r) { return r.json(); })
          .then(function (job) {
            if (job.status === "completed" && job.model_id) {
              statusEl.textContent = "Hazır! Yönlendiriliyorsunuz…";
              window.location.href = "/m/" + job.model_id;
            } else if (job.status === "failed") {
              upFail(job.error || "Dönüşüm başarısız oldu.");
            } else setTimeout(tick, 1500);
          })
          .catch(function () { setTimeout(tick, 3000); });
      })();
    }
  }

  /* =====================================================
     AI GENERATION
     ===================================================== */
  var aiModal = $("ai-modal");
  if (aiModal) {
    var aiBusy = false;
    var aiTab = "text";
    var aiImage = null;
    var aiForm = $("ai-form-area");
    var aiProg = $("ai-progress-area");
    var aiBar = $("ai-progress-bar");
    var aiStatus = $("ai-status");
    var aiDetail = $("ai-detail");

    $("open-ai").addEventListener("click", function () { aiModal.hidden = false; });
    wireModal(aiModal, function () {
      if (aiBusy) return confirm("Üretim devam ediyor. Kapatırsanız ilerlemeyi izleyemezsiniz (üretim sürmeye devam eder). Kapatılsın mı?");
      return true;
    });

    aiModal.querySelectorAll(".tabbar button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        aiTab = btn.dataset.tab;
        aiModal.querySelectorAll(".tabbar button").forEach(function (b) { b.classList.toggle("active", b === btn); });
        $("ai-tab-text").hidden = aiTab !== "text";
        $("ai-tab-image").hidden = aiTab !== "image";
      });
    });

    var aiDz = $("ai-dropzone");
    var aiInput = $("ai-image-input");
    aiDz.addEventListener("click", function () { aiInput.click(); });
    aiInput.addEventListener("change", function () {
      if (aiInput.files.length) setAiImage(aiInput.files[0]);
    });
    ["dragover", "dragenter"].forEach(function (ev) {
      aiDz.addEventListener(ev, function (e) { e.preventDefault(); aiDz.classList.add("dragover"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      aiDz.addEventListener(ev, function (e) { e.preventDefault(); aiDz.classList.remove("dragover"); });
    });
    aiDz.addEventListener("drop", function (e) {
      if (e.dataTransfer.files.length) setAiImage(e.dataTransfer.files[0]);
    });
    function setAiImage(file) {
      aiImage = file;
      var label = $("ai-dz-file");
      label.hidden = false;
      label.textContent = "→ " + file.name;
    }

    function aiFail(message) {
      aiBusy = false;
      aiStatus.textContent = "Hata";
      aiBar.style.width = "0";
      aiDetail.textContent = message;
      setTimeout(function () { aiForm.hidden = false; aiProg.hidden = true; }, 5000);
    }

    function aiShowProgress() {
      aiBusy = true;
      aiForm.hidden = true;
      aiProg.hidden = false;
      aiBar.style.width = "2%";
      aiStatus.textContent = "Üretim başlatılıyor…";
      aiDetail.textContent = "";
    }

    var stageNames = {
      preview: "Önizleme geometrisi üretiliyor…",
      refine: "Model rafine ediliyor, PBR dokular işleniyor…",
      image: "Görselden 3D model üretiliyor…"
    };

    $("ai-start").addEventListener("click", function () {
      if (aiTab === "text") {
        var prompt = $("ai-prompt").value.trim();
        if (prompt.length < 3) { alert("Lütfen ne üretmek istediğinizi yazın."); return; }
        aiShowProgress();
        fetch("/api/ai/text", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({ prompt: prompt, art_style: $("ai-style").value })
        }).then(handleStart).catch(function () { aiFail("Bağlantı hatası."); });
      } else {
        if (!aiImage) { alert("Lütfen bir görsel seçin."); return; }
        aiShowProgress();
        var data = new FormData();
        data.append("image", aiImage);
        if ($("ai-img-name").value.trim()) data.append("name", $("ai-img-name").value.trim());
        fetch("/api/ai/image", {
          method: "POST",
          headers: { "X-CSRFToken": csrf },
          body: data
        }).then(handleStart).catch(function () { aiFail("Bağlantı hatası."); });
      }
    });

    function handleStart(resp) {
      resp.json().then(function (body) {
        if (resp.status === 202 && body.job_id) pollAi(body.job_id);
        else aiFail(body.error || "Üretim başlatılamadı.");
      });
    }

    function pollAi(jobId) {
      (function tick() {
        fetch("/api/ai/jobs/" + jobId, { headers: { Accept: "application/json" } })
          .then(function (r) { return r.json(); })
          .then(function (job) {
            if (job.status === "ready" && job.model_id) {
              aiBar.style.width = "100%";
              aiStatus.textContent = "Hazır! Yönlendiriliyorsunuz…";
              window.location.href = "/m/" + job.model_id;
              return;
            }
            if (job.status === "failed") { aiFail(job.error || "Üretim başarısız oldu."); return; }
            aiBar.style.width = Math.max(2, job.progress || 0) + "%";
            aiStatus.textContent = stageNames[job.stage] || "Üretiliyor…";
            aiDetail.textContent = "%" + (job.progress || 0) + " — ortalama süre 2–5 dk";
            setTimeout(tick, 4000);
          })
          .catch(function () { setTimeout(tick, 6000); });
      })();
    }
  }
})();
