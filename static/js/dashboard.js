/* Dashboard: upload modal with drag & drop, XHR progress, job polling. */
(function () {
  "use strict";

  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const modal = document.getElementById("upload-modal");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const formArea = document.getElementById("upload-form-area");
  const progressArea = document.getElementById("upload-progress-area");
  const progressBar = document.getElementById("progress-bar");
  const statusEl = document.getElementById("upload-status");
  const detailEl = document.getElementById("upload-detail");

  let busy = false;

  function openModal() { modal.hidden = false; }
  function closeModal() {
    if (busy) return;
    modal.hidden = true;
    resetModal();
  }
  function resetModal() {
    formArea.hidden = false;
    progressArea.hidden = true;
    progressBar.style.width = "0";
    progressBar.classList.remove("indeterminate");
    fileInput.value = "";
  }

  document.getElementById("open-upload").addEventListener("click", openModal);
  modal.querySelectorAll("[data-close]").forEach((el) =>
    el.addEventListener("click", closeModal)
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) startUpload(fileInput.files[0]);
  });
  ["dragover", "dragenter"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) startUpload(e.dataTransfer.files[0]);
  });

  function fail(message) {
    busy = false;
    statusEl.textContent = "Hata";
    progressBar.classList.remove("indeterminate");
    progressBar.style.width = "0";
    detailEl.textContent = message;
    setTimeout(() => {
      resetModal();
    }, 4000);
  }

  function startUpload(file) {
    busy = true;
    formArea.hidden = true;
    progressArea.hidden = false;
    statusEl.textContent = "Yükleniyor… " + file.name;
    detailEl.textContent = "";

    const data = new FormData();
    data.append("file", file);
    const folderId = document.getElementById("upload-folder").value;
    if (folderId) data.append("folder_id", folderId);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.setRequestHeader("X-CSRFToken", csrfToken);
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        progressBar.style.width = Math.round((e.loaded / e.total) * 100) + "%";
      }
    });
    xhr.addEventListener("load", () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 202 && body.job_id) {
        pollJob(body.job_id);
      } else {
        fail(body.error || "Yükleme başarısız oldu (" + xhr.status + ").");
      }
    });
    xhr.addEventListener("error", () => fail("Bağlantı hatası — tekrar deneyin."));
    xhr.send(data);
  }

  function pollJob(jobId) {
    statusEl.textContent = "Dönüştürülüyor…";
    detailEl.textContent = "Model GLB formatına çevriliyor, bu birkaç saniye sürebilir.";
    progressBar.style.width = "100%";
    progressBar.classList.add("indeterminate");

    const tick = () => {
      fetch("/api/jobs/" + jobId, { headers: { Accept: "application/json" } })
        .then((r) => r.json())
        .then((job) => {
          if (job.status === "completed" && job.model_id) {
            statusEl.textContent = "Hazır! Yönlendiriliyorsunuz…";
            window.location.href = "/m/" + job.model_id;
          } else if (job.status === "failed") {
            fail(job.error || "Dönüşüm başarısız oldu.");
          } else {
            setTimeout(tick, 1500);
          }
        })
        .catch(() => setTimeout(tick, 3000));
    };
    tick();
  }
})();
