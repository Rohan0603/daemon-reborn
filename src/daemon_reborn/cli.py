"""Bootstrap command-line interface."""

import argparse
import sys

from PySide6.QtWidgets import QApplication


def main(argv: list[str] | None = None) -> int:
    """Parse command-line arguments and return an exit status."""
    parser = argparse.ArgumentParser(
        prog="daemon-reborn",
        description="Daemon Reborn Windows desktop companion.",
    )
    parser.parse_args(argv)

    from daemon_reborn.app.application import DesktopApplication

    qt_args = [parser.prog, *(argv if argv is not None else sys.argv[1:])]
    return DesktopApplication(QApplication(qt_args)).run()
