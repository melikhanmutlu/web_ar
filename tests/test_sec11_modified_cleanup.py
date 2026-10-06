"""SEC-11: /apply_modifications must not accumulate unlimited modified_*.glb files."""

import glob
import os

from app import app
from blueprints.model_editing import MAX_MODIFIED_DOWNLOADS
from tests.test_viewer_page import make_two_material_model


def test_apply_modifications_keeps_only_latest_downloads(client):
    model_id, _ = make_two_material_model(user_id=None)
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)

    names = []
    for _ in range(MAX_MODIFIED_DOWNLOADS + 4):
        resp = client.post("/apply_modifications", json={
            "model_id": model_id,
            "modifications": {"transform": {"scale": 1.1}},
        })
        assert resp.status_code == 200, resp.get_json()
        names.append(resp.get_json()["filename"])

    remaining = {os.path.basename(p) for p in glob.glob(os.path.join(model_dir, "modified_*.glb"))}
    assert len(remaining) == MAX_MODIFIED_DOWNLOADS
    # the most recent download is always still available
    assert names[-1] in remaining
    assert client.get(f"/download_modified/{model_id}/{names[-1]}").status_code == 200
