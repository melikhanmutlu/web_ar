"""Production/development entrypoint.

Railway (nixpacks.toml) runs:
    flask db upgrade        with FLASK_APP=app.py
    python worker.py        background converter (imports from this module)
    gunicorn app:app        web server
"""

import os

from webar import create_app
from webar.extensions import db  # re-exported for worker.py / shells
from webar.jobs import run_conversion_job  # re-exported for worker.py

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG"])
