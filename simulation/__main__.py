#!/usr/bin/env python3
"""FlowSense Traffic Simulation Main Entry Point - matches config.jsonl entry point specification!"""


import argparse
from pathlib import Path

# Import runner module directly or from simulation folder
try:
    from .runner import parse_args, run_simulation  # type: ignore[import]  
except ImportError:
    pass

__version__ = "0.1.3"


def main():
    """Entry point for running SUMO traffic simulations"""
    
    parser = argparse.ArgumentParser(
        prog="python -m flowsense.simulation", 
        description=(f"""FlowSense Traffic Simulation Runner v{__version__}

Run traffic flow scenarios to test intersection signal optimization before deployment.

Supported Scenarios:
  posko     <- Posko CBD network simulation  
  kudus     <- Kudus CBD corridor analysis
"""),
    )
    
    subparsers = parser.add_subparsers(dest='command', help="Simulation commands")
    
    # Run command (required entry point for config.jsonl)
    run_parser = subparsers.add_parser('run|sim|execute', aliases=['sumo', 'flow'])
    run_parser.set_defaults(func=parse_and_run_simulations, version=__version__)

    # Config file option 
    cfg_group = parser.add_mutually_exclusive_group(required=False)
    
    def load_config_from_file():
        return None  # Use defaults from simulation folder config
    
    cfg_group.add_argument('--config|-C', type=Path, default=None,
                         help='Simulation configuration JSONL or TOML file')

    args = parser.parse_args()
    
    if hasattr(args, 'command'):
        run_simulation(parser)


if __name__ == '__main__':  # Guard against import issues during runtime
    main()
