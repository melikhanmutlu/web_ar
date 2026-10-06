"""User-facing conversion error messages.

Converter/library exceptions can carry module names ("No module named
'chardet'") or absolute server paths ("/storage/temp/<id>/x.bin"). Neither
should reach the upload UI, the job status API, webhooks or e-mails, so known
error classes are mapped to plain-language messages and anything else is
scrubbed of paths.
"""
import os
import re


class UserFacingConversionError(RuntimeError):
    """A conversion failure whose message is already safe to show users."""


# Absolute POSIX paths with >= 2 segments, and Windows drive paths.
_POSIX_PATH = re.compile(r"(?<![\w.:/])/(?:[\w.\-~@+]+/)+[\w.\-~@+]*")
_WINDOWS_PATH = re.compile(r"(?<![\w])[A-Za-z]:[\\/](?:[^\\/\s'\":,;]+[\\/])*[^\\/\s'\":,;]*")


def _strip_paths(message: str) -> str:
    def _leaf(match):
        leaf = os.path.basename(match.group(0).replace("\\", "/").rstrip("/"))
        return leaf or "file"

    return _WINDOWS_PATH.sub(_leaf, _POSIX_PATH.sub(_leaf, message))


def friendly_conversion_error(error, extension=None) -> str:
    """Return a safe, readable message for a conversion failure."""
    if isinstance(error, UserFacingConversionError):
        return str(error)
    raw = str(error) or error.__class__.__name__
    lowered = raw.lower()
    fmt = (extension or "").lstrip(".").upper() or "3D"

    if "no module named" in lowered or isinstance(error, ImportError):
        return (
            f"The file could not be read as a valid {fmt} model. "
            f"It may be corrupt or not really a {fmt} file."
        )
    if "unsafe file reference" in lowered or "unsafe mtllib" in lowered:
        return (
            "The OBJ/MTL file points to a file path that is not allowed "
            "(absolute or '..' paths). Re-export it with relative texture paths."
        )
    if isinstance(error, FileNotFoundError) or "no such file or directory" in lowered:
        return (
            "A file this model refers to (texture, buffer or material library) "
            "is missing. Upload a ZIP that contains all referenced files."
        )
    if "timed out" in lowered:
        return "Conversion timed out. Try a simpler or smaller model."
    return _strip_paths(raw)


def sanitize_error_message(message) -> str:
    """Scrub paths/module names from an already-formatted error string."""
    if message is None:
        return message
    text = str(message)
    if "no module named" in text.lower():
        return friendly_conversion_error(text)
    return _strip_paths(text)
