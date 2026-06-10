/* Live slicing preview: renders the GLB in three.js with a clipping plane
   so the cut is visible in real time, then applies the real cut server-side
   (trimesh) via POST /api/models/<id>/slice. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const modal = document.getElementById("slicer-modal");
const openBtn = document.getElementById("open-slicer");
if (!modal || !openBtn) {
  // viewer rendered without owner panel
} else {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const wrap = document.getElementById("slicer-canvas");
  const posInput = document.getElementById("slice-pos");
  const flipInput = document.getElementById("slice-flip");
  const statsEl = document.getElementById("slice-stats");
  const statusEl = document.getElementById("slice-status");
  const applyBtn = document.getElementById("slice-apply");

  let initialized = false;
  let running = false;
  let renderer, scene, camera, controls, plane, planeMesh, bbox, modelRoot;
  let axis = "x";
  const AXIS_VEC = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };

  function init() {
    if (initialized) return;
    initialized = true;

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.localClippingEnabled = true;
    wrap.appendChild(renderer.domElement);

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(40, 1, 0.01, 200);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    scene.add(new THREE.AmbientLight(0xffffff, 1.4));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(3, 5, 4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xc9b9f6, 0.8);
    fill.position.set(-4, 2, -3);
    scene.add(fill);

    plane = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);

    new GLTFLoader().load(window.__GLB_URL__, (gltf) => {
      modelRoot = gltf.scene;
      modelRoot.traverse((node) => {
        if (node.isMesh) {
          const mats = Array.isArray(node.material) ? node.material : [node.material];
          mats.forEach((m) => {
            m.clippingPlanes = [plane];
            m.clipShadows = true;
            m.side = THREE.DoubleSide; // show interior at the cut
          });
        }
      });
      scene.add(modelRoot);

      bbox = new THREE.Box3().setFromObject(modelRoot);
      const size = bbox.getSize(new THREE.Vector3());
      const center = bbox.getCenter(new THREE.Vector3());
      const radius = Math.max(size.x, size.y, size.z);

      controls.target.copy(center);
      camera.position.set(center.x + radius * 1.5, center.y + radius * 0.9, center.z + radius * 1.5);
      camera.near = radius / 100;
      camera.far = radius * 20;
      camera.updateProjectionMatrix();

      // translucent lilac cut-plane indicator
      const geo = new THREE.PlaneGeometry(radius * 1.6, radius * 1.6);
      const mat = new THREE.MeshBasicMaterial({
        color: 0xa78ef0, transparent: true, opacity: 0.16,
        side: THREE.DoubleSide, depthWrite: false
      });
      planeMesh = new THREE.Mesh(geo, mat);
      const edge = new THREE.LineSegments(
        new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: 0xc9b9f6, transparent: true, opacity: 0.7 })
      );
      planeMesh.add(edge);
      scene.add(planeMesh);

      updatePlane();
      startLoop();
    }, undefined, () => {
      statusEl.textContent = "Model yüklenemedi.";
      applyBtn.disabled = true;
    });

    window.addEventListener("resize", resize);
    if ("ResizeObserver" in window) new ResizeObserver(resize).observe(wrap);
  }

  function resize() {
    if (!renderer || modal.hidden) return;
    const w = wrap.clientWidth, h = Math.max(wrap.clientHeight, 420);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function startLoop() {
    if (running) return; // never stack RAF loops
    running = true;
    requestAnimationFrame(animate);
  }

  function animate() {
    if (modal.hidden) { running = false; return; } // pause while closed
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }

  function updatePlane() {
    if (!bbox) return;
    const t = parseFloat(posInput.value);
    const idx = "xyz".indexOf(axis);
    const lo = bbox.min.getComponent(idx), hi = bbox.max.getComponent(idx);
    const coord = lo + (hi - lo) * t;
    const flip = flipInput.checked;

    // three.js keeps the half-space where normal·p + constant > 0
    const n = new THREE.Vector3(...AXIS_VEC[axis]).multiplyScalar(flip ? -1 : 1);
    plane.normal.copy(n);
    plane.constant = -coord * (flip ? -1 : 1);

    if (planeMesh) {
      const center = bbox.getCenter(new THREE.Vector3());
      planeMesh.position.copy(center);
      planeMesh.position.setComponent(idx, coord);
      planeMesh.rotation.set(0, 0, 0);
      if (axis === "x") planeMesh.rotation.y = Math.PI / 2;
      else if (axis === "y") planeMesh.rotation.x = Math.PI / 2;
    }

    const size = bbox.getSize(new THREE.Vector3());
    const kept = flip ? coord - bbox.min.getComponent(idx) : bbox.max.getComponent(idx) - coord;
    statsEl.textContent = axis.toUpperCase() + " ekseni · düzlem %" + Math.round(t * 100) +
      " · tutulan kalınlık ≈ " + (kept >= 1 ? kept.toFixed(2) + " m" : (kept * 100).toFixed(1) + " cm") +
      " / " + (size.getComponent(idx) >= 1 ? size.getComponent(idx).toFixed(2) + " m"
                                           : (size.getComponent(idx) * 100).toFixed(1) + " cm");
  }

  /* controls */
  modal.querySelectorAll("[data-axis]").forEach((btn) => {
    btn.addEventListener("click", () => {
      axis = btn.dataset.axis;
      modal.querySelectorAll("[data-axis]").forEach((b) => b.classList.toggle("active", b === btn));
      updatePlane();
    });
  });
  posInput.addEventListener("input", updatePlane);
  flipInput.addEventListener("change", updatePlane);

  openBtn.addEventListener("click", () => {
    modal.hidden = false;
    init();
    // layout settles a frame after the modal becomes visible
    requestAnimationFrame(() => { resize(); startLoop(); });
  });
  modal.querySelectorAll("[data-close]").forEach((el) => {
    el.addEventListener("click", () => { modal.hidden = true; });
  });

  applyBtn.addEventListener("click", () => {
    if (!confirm("Kesim kalıcıdır ve geri alınamaz. Uygulansın mı?")) return;
    applyBtn.disabled = true;
    statusEl.textContent = "Kesiliyor…";
    fetch("/api/models/" + window.__MODEL__.id + "/slice", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({
        axis: axis,
        position: parseFloat(posInput.value),
        keep: flipInput.checked ? "below" : "above",
        cap: document.getElementById("slice-cap").checked
      })
    })
      .then((r) => r.json().then((b) => ({ ok: r.ok, body: b })))
      .then((res) => {
        if (!res.ok) {
          applyBtn.disabled = false;
          statusEl.textContent = res.body.error || "Kesim başarısız.";
          return;
        }
        statusEl.textContent = "Kesildi ✓ — sayfa yenileniyor…";
        setTimeout(() => window.location.reload(), 800);
      })
      .catch(() => {
        applyBtn.disabled = false;
        statusEl.textContent = "Bağlantı hatası.";
      });
  });
}
