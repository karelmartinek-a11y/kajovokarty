# Third-party licenses

Tento repozitář používá následující knihovny. Při produkčním buildu je nutné zachovat jejich licenční texty a splnit podmínky příslušné licence.

| Balík | Verze | Licence |
|---|---:|---|
| PySide6 / Qt for Python | 6.10.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only / komerční Qt licence |
| shiboken6 | 6.10.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| httpx | 0.28.1 | BSD-3-Clause |
| openpyxl | 3.1.5 | MIT |
| xlrd | 2.0.1 | BSD |
| python-dateutil | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause |
| platformdirs | 4.3.8 | MIT |
| cryptography | 45.0.5 | Apache-2.0 OR BSD-3-Clause |
| pywin32 | 310 | PSF |
| reportlab | 4.4.2 | BSD-3-Clause |
| pytest | 8.4.1 | MIT |
| pytest-cov | 6.2.1 | MIT |
| pytest-qt | 4.5.0 | MIT |
| mypy | 1.17.0 | MIT |
| ruff | 0.12.3 | MIT |
| PyInstaller | 6.14.2 | GPL-2.0-or-later with bootloader exception |
| setuptools | 75.8.2 | MIT |
| wheel | 0.45.1 | MIT |

Úplná znění licencí jsou distribuována v nainstalovaných balících. Produkční release gate musí před vydáním provést automatickou kontrolu licencí a zahrnout příslušné texty do instalace.
