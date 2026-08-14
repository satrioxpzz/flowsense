"""FlowSense Traffic Simulation Module - entry point for SUMO-based traffic analysis.

The simulation package exposes an optional ``runner`` sub-module (added for
P0-3). Importing it here is best-effort: if the runner has not been ported into
this environment yet, the package still imports cleanly and callers can detect
the missing entry point explicitly.
"""

__version__ = "0.1.3"

try:
    from flowsense.simulation.runner import parse_args, run_simulation  # type: ignore[import]

    HAS_RUNNER = True
except ImportError:
    # Runner not present in this environment; simulation is optional at runtime.
    HAS_RUNNER = False
    parse_args = None
    run_simulation = None


__all__ = ["__version__", "HAS_RUNNER", "parse_args", "run_simulation"]
