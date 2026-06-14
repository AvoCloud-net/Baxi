#!/usr/bin/env python3
"""Baxi admin CLI — standalone front-end for the console commands.

Use this when the bot is NOT running. While the bot IS running, type the same
commands straight into its terminal (the in-process console is started from
main.py via assets.console.run_console).

    python3 baxi_cli.py                  # interactive REPL
    python3 baxi_cli.py <command> ...    # one-shot, then exit
    python3 baxi_cli.py help             # list commands

Run from the bot's working directory (needs config/ + baxi_data.db).
"""
from assets.console import main_standalone

if __name__ == "__main__":
    main_standalone()
