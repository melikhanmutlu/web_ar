"""Run one ConversionService.convert() in its own process.

A conversion can lift a process by hundreds of MB to several GB (trimesh
scenes, FBX/OBJ meshes, STEP tessellation). glibc rarely hands that memory
back, so in the long-lived worker it stayed resident — and billed — until the
next deploy. Converting in a short-lived child returns all of it to the OS
the moment the job ends.

Protocol: the parent writes one JSON request to stdin; the child answers on
stdout with JSON lines: {"progress": [...], "extra": {...}} while it runs and
a final {"result": {...}} or {"error": "...", "user_facing": bool}. Anything
else the converters print goes to stderr (the service log).
"""

import json
import logging
import os
import sys


def _jsonable(value):
    """numpy scalars/arrays in converter attributes -> plain JSON values."""
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def main() -> int:
    # Keep the real stdout for the protocol; send every other write
    # (including C-level prints from converters) to stderr.
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")

    def send(message):
        proto.write(json.dumps(message, default=_jsonable) + "\n")

    request = json.loads(sys.stdin.read())

    from services.asset_quality import AssetQualityService
    from services.conversion import ConversionService
    from services.conversion_errors import UserFacingConversionError

    service = ConversionService(AssetQualityService(**request["asset_quality"]))

    def progress(value, stage, detail, **extra):
        send({"progress": [value, stage, detail], "extra": extra})

    try:
        result = service.convert(request["payload"], request["output_path"], progress=progress)
    except UserFacingConversionError as exc:
        send({"error": str(exc), "user_facing": True})
        return 0
    except Exception as exc:  # convert() already made the message user-safe
        send({"error": str(exc), "user_facing": False})
        return 0
    converter = result.pop("converter", None)
    result["converter"] = {
        "original_dimensions": getattr(converter, "original_dimensions", None),
        "max_dimension": getattr(converter, "max_dimension", 0),
    }
    send({"result": result})
    return 0


if __name__ == "__main__":
    sys.exit(main())
