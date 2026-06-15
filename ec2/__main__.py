"""Entry point for ``python -m ec2``."""

from __future__ import annotations

import sys

from ec2.cli import main

if __name__ == "__main__":
    sys.exit(main())
