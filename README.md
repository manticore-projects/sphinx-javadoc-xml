# sphinx-javadoc-xml

[![PyPI](https://img.shields.io/pypi/v/sphinx-javadoc-xml)](https://pypi.org/project/sphinx-javadoc-xml/)
[![Python](https://img.shields.io/pypi/pyversions/sphinx-javadoc-xml)](https://pypi.org/project/sphinx-javadoc-xml/)
[![License](https://img.shields.io/pypi/l/sphinx-javadoc-xml)](LICENSE)

<img width="33%" alt="JSQLParser API" align="right" src="https://github.com/user-attachments/assets/e8e0f520-978b-4538-963e-74306363f976" /> A Sphinx extension that renders Java API documentation from an XML doclet output
in a **JavaDoc-inspired style** — fully integrated with your Sphinx theme, with
cross-links to [OpenJDK Javadoc](https://docs.oracle.com/en/java/javase/21/docs/api/)
and between all defined types. 

Live sample: https://manticore-projects.com/JSQLParser/javadoc_snapshot.html# 


## Features

- **Full XML doclet support**: classes, interfaces, enums, methods, fields,
  constructors, annotations, type parameters, bounded wildcards, exceptions
- **OpenJDK cross-links**: `java.util.List` becomes a clickable link to the
  Oracle JDK 21 docs (configurable URL)
- **Internal cross-references**: all types defined in your API link to each other
- **Package name stripping**: types within the same package show short names
- **Three directives**: full API, single class, or package summary
- **Theme-compatible CSS**: works with Furo, Read the Docs, Alabaster, and others

## Installation

```bash
pip install sphinx-javadoc-xml
```

## Quick Start

### 1. Enable in `conf.py`

```python
extensions = [
    "sphinx_javadoc_xml",
]

# Optional configuration
javadoc_jdk_url = "https://docs.oracle.com/en/java/javase/21/docs/api"
javadoc_load_fonts = True    # Load Roboto fonts from Google Fonts CDN
javadoc_load_bulma = False   # Load Bulma CSS from CDN (for non-Bulma themes)
```

### With manticore-sphinx-theme

When using `manticore-sphinx-theme`, the extension automatically inherits the
Manticore color scheme (`--bst-*` CSS variables), Roboto fonts, and Bulma CSS
from the theme — no extra configuration needed:

```python
html_theme = "manticore_sphinx_theme"
extensions = ["sphinx_javadoc_xml"]
# Fonts and Bulma are auto-detected and skipped (already provided by theme)
```

### With other themes

The extension ships with the Manticore color scheme as defaults and loads
Google Fonts (Roboto family) automatically. Optionally enable Bulma for
enhanced table rendering:

```python
html_theme = "furo"  # or alabaster, sphinx_rtd_theme, etc.
extensions = ["sphinx_javadoc_xml"]
javadoc_load_bulma = True  # Optional: pull Bulma from CDN
```

### 2. Place your XML file

```
docs/
├── _static/
│   └── api.xml
├── conf.py
└── api.rst
```

### 3. Use the directives

**Full package API:**

```rst
.. javadoc-api:: _static/api.xml
   :package: net.sf.jsqlparser.expression
   :public-only:
```

**Single class:**

```rst
.. javadoc-class:: _static/api.xml
   :class: net.sf.jsqlparser.expression.Function
   :public-only:
```

**Package summary only (no type details):**

```rst
.. javadoc-package:: _static/api.xml
   :package: net.sf.jsqlparser.statement.select
   :public-only:
```

## Directives Reference

### `.. javadoc-api:: <path>`

| Option         | Description                                      |
|----------------|--------------------------------------------------|
| `:package:`    | Filter to a specific package name                |
| `:public-only:`| Hide private and package-private members          |
| `:jdk-url:`   | Override JDK Javadoc base URL for this directive  |

### `.. javadoc-class:: <path>`

| Option         | Description                                      |
|----------------|--------------------------------------------------|
| `:class:`      | **Required.** Qualified or simple class name     |
| `:public-only:`| Hide private and package-private members          |
| `:jdk-url:`   | Override JDK Javadoc base URL for this directive  |

### `.. javadoc-package:: <path>`

| Option         | Description                                      |
|----------------|--------------------------------------------------|
| `:package:`    | **Required.** Package name to render             |
| `:public-only:`| Hide private and package-private members          |

## Configuration (`conf.py`)

| Option               | Default                                              | Description                                                                 |
|----------------------|------------------------------------------------------|-----------------------------------------------------------------------------|
| `javadoc_jdk_url`    | `https://docs.oracle.com/en/java/javase/21/docs/api` | Base URL for JDK Javadoc cross-links                                       |
| `javadoc_load_fonts` | `True`                                               | Load Google Fonts (Roboto family); auto-disabled under manticore-sphinx-theme |
| `javadoc_load_bulma` | `False`                                              | Load Bulma CSS from CDN; auto-disabled under manticore-sphinx-theme         |

## Cross-Linking

The extension automatically creates hyperlinks:

- **JDK types** → Oracle Javadoc (e.g., `java.util.List` → [docs.oracle.com/...](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/List.html))
- **Internal types** → anchor links within the same page or document
- External links open in a new tab and show a small ↗ indicator

## Theme Compatibility

The CSS uses CSS custom properties (`--jdx-*`) that automatically inherit
from manticore-sphinx-theme's `--bst-*` variables when available:

| Theme                    | Integration                                             |
|--------------------------|---------------------------------------------------------|
| **manticore-sphinx-theme** | Native — inherits colors, fonts, Bulma; zero config    |
| **Furo**                   | Full — uses Manticore defaults, optional Bulma          |
| **sphinx_rtd_theme**       | Full — Manticore colors with RTD layout                 |
| **Alabaster**              | Full — clean integration                                |
| **sphinx_book_theme**      | Full — Jupyter Book style with Manticore colors         |

All CSS selectors are prefixed with `javadoc-` so they never conflict with
theme styles.

The extension expects the XML structure produced by the
[xml-doclet](https://github.com/MarkusBernwordt/xml-doclet) or a compatible
custom doclet. See the [CHANGELOG](CHANGELOG.md) for supported elements.

## XML Format

The extension expects the XML structure produced by the
[xml-doclet](https://github.com/MarkusBernwordt/xml-doclet) or a compatible
custom doclet. See the [CHANGELOG](CHANGELOG.md) for supported elements.

## Publishing to PyPI

```bash
# Build
python -m build

# Upload to TestPyPI first
twine upload --repository testpypi dist/*

# Upload to PyPI
twine upload dist/*
```

Or use GitHub Actions with [OIDC trusted publishing](https://docs.pypi.org/trusted-publishers/).

## License

[MIT](LICENSE)
