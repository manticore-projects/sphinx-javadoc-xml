"""
sphinx-javadoc-xml
==================

A Sphinx extension that renders Java API documentation from an XML doclet
output in a JavaDoc-inspired style, with cross-links to OpenJDK Javadoc
and internal type references.

Directives
----------

``.. javadoc-api:: path/to/api.xml``
    Renders the full API (all packages, types, members).
    Options: ``:package:``, ``:public-only:``, ``:jdk-url:``

``.. javadoc-class:: path/to/api.xml``
    Renders a single type.
    Options: ``:class:``, ``:public-only:``, ``:jdk-url:``

``.. javadoc-package:: path/to/api.xml``
    Renders a package summary table only.
    Options: ``:package:``, ``:public-only:``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from sphinx.application import Sphinx

from .directives import JavadocApiDirective, JavadocClassDirective, JavadocPackageDirective

__version__ = "0.3.0"

logger = logging.getLogger(__name__)

# Google Fonts for Roboto family (Manticore branding)
_GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Roboto:wght@400;500;700"
    "&family=Roboto+Slab:wght@400;500"
    "&family=Roboto+Mono:wght@400;600"
    "&display=swap"
)

_BULMA_CDN_URL = (
    "https://cdn.jsdelivr.net/npm/[email protected]/css/bulma.min.css"
)


def _on_builder_inited(app: Sphinx) -> None:
    """Register static files and optional CDN resources."""
    logger.info("sphinx-javadoc-xml v%s loaded", __version__)

    # Static dir for javadoc.css
    static_dir = str(Path(__file__).parent / "static")
    app.config.html_static_path.append(static_dir)

    # Detect if running under manticore-sphinx-theme (which provides
    # Roboto fonts and Bulma already)
    theme = getattr(app.config, "html_theme", "")
    is_manticore = theme in ("manticore_sphinx_theme", "manticore-sphinx-theme")

    # Load Google Fonts unless the theme already provides them
    if not is_manticore and app.config.javadoc_load_fonts:
        app.add_css_file(_GOOGLE_FONTS_URL)

    # Load Bulma CSS if requested and not already provided by theme
    if not is_manticore and app.config.javadoc_load_bulma:
        app.add_css_file(_BULMA_CDN_URL)


def setup(app: Sphinx) -> Dict[str, Any]:
    app.add_directive("javadoc-api", JavadocApiDirective)
    app.add_directive("javadoc-class", JavadocClassDirective)
    app.add_directive("javadoc-package", JavadocPackageDirective)

    # Configuration values
    app.add_config_value("javadoc_jdk_url",
                         "https://docs.oracle.com/en/java/javase/21/docs/api",
                         "html")
    app.add_config_value("javadoc_load_fonts", True, "html")
    app.add_config_value("javadoc_load_bulma", False, "html")

    app.connect("builder-inited", _on_builder_inited)
    app.add_css_file("javadoc.css")

    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
