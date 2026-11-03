"""Bootstrap command-line interface."""

import argparse


def main(argv: list[str] | None = None) -> int:
    """Parse command-line arguments and return an exit status."""
    parser = argparse.ArgumentParser(
        prog="daemon-reborn",
        description="Daemon Reborn desktop companion bootstrap.",
    )
    parser.parse_args(argv)
    return 0
