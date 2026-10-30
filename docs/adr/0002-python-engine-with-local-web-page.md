# Python engine with a local web page, not a browser-only or desktop app

The engine is a Python package (numpy + pillow) with a command line, and the interactive UI is a small web page that the same package serves on localhost. The earlier prototype tools were Python, it runs the same on Windows and Linux, and the page needs no build step. We gave up the zero-install of a browser-only app (like Kromacut) and the polish of a desktop app; either could be added later on top of the same engine.

Decided 2026-10-27, with: up to 4 filaments per Stack in v1 with automatic Swap plans, command line first then the live-preview page, a short editable filament list instead of a community TD import, and 3MF export from a template (ADR 0001).
