"""Installed-package convenience entrypoint; no model calls."""
from vulnloc.cli import main

if __name__ == "__main__":
    import sys
    sys.argv.insert(1, "reproduce")
    main()
