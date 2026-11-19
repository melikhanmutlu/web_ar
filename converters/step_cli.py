"""Run cascadio (OpenCASCADE) STEP -> GLB in its own process.

OpenCASCADE can segfault or exhaust memory on hostile or huge STEP files, so
STEPConverter shells out to this module instead of importing cascadio in the
web/worker process. Exit code: 0 ok, 2 conversion failed.
"""

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--tol-linear", type=float, default=0.01)
    parser.add_argument("--tol-angular", type=float, default=0.5)
    args = parser.parse_args(argv)

    import cascadio

    try:
        result = cascadio.step_to_glb(
            args.input,
            args.output,
            tol_linear=args.tol_linear,
            tol_angular=args.tol_angular,
            merge_primitives=True,
            # Serial meshing: ~3.2 GB peak instead of ~4.8 GB on a 72 MB
            # assembly, for ~10% more time.
            use_parallel=False,
        )
    except Exception as exc:  # cascadio raises a plain RuntimeError on bad input
        print(f"cascadio failed: {exc}", file=sys.stderr)
        return 2
    if result != 0:
        print(f"cascadio returned {result}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
