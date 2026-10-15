# Contributing

Bug reports and pull requests are welcome. For a decoding issue, include your Linux distribution, Python version, application version, steps to reproduce and the error text. Attach a minimal cursor sample only if you have permission to share it.

Use Python 3.11-compatible code. Install `.[dev]` in a virtual environment and run Ruff, pytest with `QT_QPA_PLATFORM=offscreen`, and `python -m build` before submitting a pull request. Add regression tests for decoder and exporter changes. Keep the core independent of Qt, preserve overwrite protection and avoid executing commands derived from filenames.

For larger features, open an issue first to discuss scope. Never include credentials, user-specific paths or third-party cursor packs without a redistribution license.
