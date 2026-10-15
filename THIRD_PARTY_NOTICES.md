# Third-party notices

Cursor Studio's own source code is MIT licensed. Runtime dependencies are separate projects with their own licenses:

- Pillow: HPND / Pillow license. https://github.com/python-pillow/Pillow/blob/main/LICENSE
- PySide6 Essentials / Shiboken6: Qt for Python, available under LGPLv3/GPLv3 and commercial terms. https://doc.qt.io/qtforpython-6/licenses.html

The source installation uses Python wheels with dynamically loaded Qt libraries; it does not embed a statically linked Qt build. Review upstream license requirements before distributing a modified or bundled application. License texts and notices are shipped with the upstream packages.

No code from win2xcur or ani2xcur is included. The demonstration cursor artwork is generated specifically for this project.
