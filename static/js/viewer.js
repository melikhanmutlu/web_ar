/* Viewer page: QR modal, copy link, model-viewer load progress. */
(function () {
  "use strict";

  const qrModal = document.getElementById("qr-modal");
  const showQr = document.getElementById("show-qr");
  if (showQr && qrModal) {
    showQr.addEventListener("click", () => { qrModal.hidden = false; });
    qrModal.querySelectorAll("[data-close]").forEach((el) =>
      el.addEventListener("click", () => { qrModal.hidden = true; })
    );
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") qrModal.hidden = true;
    });
  }

  const copyBtn = document.getElementById("copy-link");
  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(copyBtn.dataset.url).then(() => {
        const original = copyBtn.textContent;
        copyBtn.textContent = "Kopyalandı ✓";
        setTimeout(() => { copyBtn.textContent = original; }, 1800);
      });
    });
  }

  const mv = document.getElementById("mv");
  if (mv) {
    const bar = mv.querySelector(".mv-progress-bar");
    mv.addEventListener("progress", (e) => {
      if (!bar) return;
      const p = e.detail.totalProgress;
      bar.style.width = p * 100 + "%";
      if (p >= 1) setTimeout(() => { bar.style.opacity = "0"; }, 400);
    });
  }
})();
