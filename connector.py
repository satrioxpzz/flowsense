"""FlowSense edge connector entry point.

Thin wrapper around the flowsense.runner package. Run:
    python connector.py --camera "Simpang DPRD Arah Kota"
"""
import sys

from flowsense.runner import main

if __name__ == "__main__":
    sys.exit(main())
