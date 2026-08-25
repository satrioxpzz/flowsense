#!/usr/bin/env python3
"""FlowSense SUMO Simulation Entry Point (P0-3 fix).

Runs the adaptive / fixed-time traffic-light simulation end-to-end:

  1. Build SUMO infrastructure XML (net, routes, sensors, config) via generator.
  2. Launch sumo-gui + TraCI.
  3. Step an adaptive (TimeExtensionController) or fixed-time (FixedTimeController)
     controller each tick until the simulation ends.
  4. Write Markdown + JSON performance reports via analyzer.

Usage:
    python -m flowsense.simulation --adaptive [--congested north south ...]
    python -m flowsense.simulation --fixed
    python -m flowsense.simulation --compare        # adaptive + fixed then delta

Cross-platform: resolves SUMO_HOME from the eclipse-sumo wheel when present,
otherwise from the SUMO_HOME env var or the default Windows install location.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ----------------------------------------------------------------------------
# SUMO / TraCI environment bootstrap
# ----------------------------------------------------------------------------
def _bootstrap_sumo():
    """Make the SUMO 'tools' dir importable for traci/sumolib.

    Resolves SUMO_HOME from (in priority order):
      1. an existing SUMO_HOME env var (assumed absolute / correct),
      2. the eclipse-sumo wheel installed in this environment's site-packages,
      3. the common Windows install location.
    Returns the chosen SUMO_HOME string, or None if nothing was found.
    """
    candidates = []

    env = os.environ.get("SUMO_HOME")
    if env and os.path.isdir(os.path.join(env, "tools")):
        candidates.append(env)

    # eclipse-sumo wheel ships a 'sumo' package with a 'tools' subdir inside
    # site-packages. Resolve it robustly for both venv and system installs.
    try:
        import site
        for sp in site.getsitepackages():
            wheel = os.path.join(sp, "sumo", "tools")
            if os.path.isdir(wheel):
                # Record the parent ('.../sumo') as the SUMO_HOME root.
                candidates.append(os.path.join(sp, "sumo"))
                break
    except Exception:
        pass

    # Common Windows install location (Reference main.py default).
    candidates.append(r"C:\Program Files (x86)\Eclipse\Sumo")

    for cand in candidates:
        tools = os.path.join(cand, "tools")
        if os.path.isdir(tools):
            os.environ["SUMO_HOME"] = cand
            if tools not in sys.path:
                sys.path.insert(0, tools)
            return cand
    return None


_SUMO_HOME = _bootstrap_sumo()


def _require_traci():
    try:
        import traci  # noqa: F401
        return True
    except Exception as exc:  # pragma: no cover - environment guard
        print(
            "ERROR: traci/sumolib not importable. Is eclipse-sumo installed in this\n"
            "environment? Try:  python -m pip install eclipse-sumo\n"
            f"(SUMO_HOME candidates searched; last error: {exc})",
            file=sys.stderr,
        )
        sys.exit(2)


# ----------------------------------------------------------------------------
# Main flow
# ----------------------------------------------------------------------------
def run_once(use_adaptive: bool, congested: list[str], run_fast: bool = False,
             tls_layout: str = "opposites", orderliness: str = "orderly",
             use_gui: bool = False, real_flows: dict | None = None) -> dict | None:
    import traci
    from .generator import build_network, build_routes, build_sensors, build_config, find_exe
    from .sim_config import set_traffic_volumes, set_real_traffic_volumes
    from .controller import TimeExtensionController, FixedTimeController
    from .analyzer import print_simulation_report

    mode_label = "Adaptive-Control" if use_adaptive else "Fixed-Time-Program"
    print(f"\n=== FlowSense SUMO Simulation: {mode_label} ===")

    # 1. Build infrastructure
    if real_flows is not None:
        # P3-wiring: real YOLO counts from connector jsonl drive SUMO demand.
        set_real_traffic_volumes(real_flows)
        print("  Demand source: REAL FlowSense detections (--from-connector)")
    else:
        set_traffic_volumes(congested)
    build_network(tls_layout)
    build_routes(orderliness)
    build_sensors()
    build_config()

    # 2. Launch SUMO + TraCI (headless 'sumo' by default; 'sumo-gui' with --gui)
    sumo_bin = find_exe("sumo-gui" if use_gui else "sumo")
    cfg = os.path.join("simulation", "map", "build", "config.sumocfg")
    cmd = [sumo_bin, "-c", cfg, "--start", "--quit-on-end"]
    if run_fast:
        cmd += ["--step-length", "0.5"]
    print(f"  Launching: {' '.join(cmd)}")
    traci.start(cmd)

    # 3. Controller + step loop
    controller = (TimeExtensionController(tls_id="center")
                  if use_adaptive else FixedTimeController(tls_id="center"))
    step_length = 0.1
    try:
        t0 = time.time()
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            controller.step(step_length=step_length)
        elapsed = time.time() - t0
        print(f"  Simulation finished in {elapsed:.1f}s wall-clock.")
    except traci.exceptions.FatalTraCIError:
        print("  [INFO] TraCI session closed.")
    finally:
        try:
            traci.close()
        except Exception:
            pass
        try:
            controller.finalize()
        except Exception:
            pass

    # 4. Reports
    # When real FlowSense detections drive the demand, the report must not
    # mislabel the run with synthetic congestion directions (P2: analyzer
    # reporting synthetic congestion on real runs).
    report_congested = ["REAL:FlowSense-detections"] if real_flows is not None else congested
    return print_simulation_report(mode_label=mode_label, congested=report_congested)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m flowsense.simulation",
        description="Run the FlowSense SUMO traffic-light simulation.",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--adaptive", action="store_true",
                       help="Adaptive TimeExtension controller (default).")
    group.add_argument("--fixed", action="store_true",
                       help="Fixed-time program (read-only overlay).")
    group.add_argument("--compare", action="store_true",
                       help="Run adaptive then fixed, then print the delta.")
    parser.add_argument("--congested", nargs="*", default=[],
                        metavar="DIR",
                        help="Congested directions, e.g. north south west east.")
    parser.add_argument("--fast", action="store_true",
                        help="Speed up the run (larger step, scaled time).")
    parser.add_argument("--gui", action="store_true",
                        help="Use sumo-gui instead of headless sumo (requires a display).")
    parser.add_argument("--duration", type=int, default=None,
                        help="Override simulation duration in seconds (default from config).")
    parser.add_argument("--tls-layout", default="opposites",
                        choices=["opposites", "incoming"],
                        help="Traffic-light signal layout.")
    parser.add_argument("--orderliness", default="orderly",
                        choices=["orderly", "chaotic"],
                        help="Driver behavior profile.")
    parser.add_argument("--from-connector", metavar="JSONL", default=None,
                        help="Use real FlowSense detections from this connector .jsonl "
                             "as SUMO demand (overrides --congested synthetic volumes).")
    parser.add_argument("--bin-seconds", type=int, default=900,
                        help="Time-bin size (s) when aggregating --from-connector data "
                             "(default 900 = 15 min).")
    args = parser.parse_args(argv)

    if args.bin_seconds <= 0:
        parser.error(f"--bin-seconds must be a positive integer (got {args.bin_seconds})")

    _require_traci()

    # Default to adaptive when nothing specified.
    if not (args.adaptive or args.fixed or args.compare):
        args.adaptive = True

    # Load real detection demand if requested.
    real_flows = None
    if args.from_connector:
        from . import adapter
        recs = adapter.load_records(Path(args.from_connector))
        if not recs:
            print(f"  [WARN] No records loaded from {args.from_connector}; "
                  f"simulation will use 0 real demand for all directions.",
                  file=sys.stderr)
        real_flows = adapter.aggregate_flows(recs, bin_seconds=args.bin_seconds)
        print(f"  Loaded {len(recs)} real detection records from {args.from_connector}.")

    if args.duration is not None:
        from . import sim_config as _sc
        _sc.SIM_DURATION = args.duration

    if args.compare:
        print("\n########## ADAPTIVE PASS ##########")
        adv = run_once(True, args.congested, args.fast, args.tls_layout,
                       args.orderliness, args.gui, real_flows=real_flows)
        print("\n########## FIXED-TIME PASS ##########")
        fix = run_once(False, args.congested, args.fast, args.tls_layout,
                       args.orderliness, args.gui, real_flows=real_flows)
        try:
            from .comparator import compute_comparison_deltas, write_comparison_report
            if adv and fix:
                deltas = compute_comparison_deltas(adv, fix)
                write_comparison_report(adv, fix, deltas)
                print("\n  Comparison report written to output/summary/.")
            else:
                print("  [WARN] One or both passes produced no report data; skipping delta.")
        except Exception as exc:
            print(f"  [WARN] comparator skipped: {exc}")
        return

    use_adaptive = bool(args.fixed) is False  # --fixed -> False
    run_once(use_adaptive, args.congested, args.fast, args.tls_layout,
             args.orderliness, args.gui, real_flows=real_flows)


if __name__ == "__main__":
    # Ensure CWD is project root so relative BUILD_DIR/output paths resolve.
    root = Path(__file__).resolve().parent.parent.parent
    os.chdir(root)
    main()
