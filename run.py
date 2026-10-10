#!/usr/bin/env python3
"""Root task runner and developer CLI for SurveySuite."""

import argparse
import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
TESTS_DIR = os.path.join(ROOT_DIR, "tests")


def get_env():
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{existing}" if existing else SRC_DIR
    return env


def test_suite(verbose=False):
    """Run full 1030+ test suite across all 15 survey engines."""
    print("Running consolidated SurveySuite test suite...")
    cmd = [sys.executable, "-m", "pytest", TESTS_DIR]
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")
    res = subprocess.run(cmd, cwd=ROOT_DIR, env=get_env())
    if res.returncode != 0:
        sys.exit(res.returncode)


def launch_app():
    """Launch the SurveySuite desktop Tkinter application."""
    print("Launching SurveySuite Desktop GUI...")
    cmd = [sys.executable, "-m", "suite.app"]
    subprocess.run(cmd, cwd=ROOT_DIR, env=get_env())


def main():
    parser = argparse.ArgumentParser(description="SurveySuite Monorepo Runner")
    subparsers = parser.add_subparsers(dest="command")

    test_parser = subparsers.add_parser("test", help="Run full test suite")
    test_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose pytest output")

    subparsers.add_parser("app", help="Launch the Desktop GUI application")

    args = parser.parse_args()

    if args.command == "test" or args.command is None:
        test_suite(getattr(args, "verbose", False))
    elif args.command == "app":
        launch_app()


if __name__ == "__main__":
    main()
