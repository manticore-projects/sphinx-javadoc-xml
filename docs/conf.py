import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "XML Doclet API"
author = "Andreas Reichel"
release = "2.3"

extensions = [
    "sphinx_javadoc_xml",
]

html_theme = "manticore_sphinx_theme"
html_static_path = ["_static"]
html_title = "XML Doclet API Reference"
html_show_sourcelink = False

# -- sphinx-javadoc-xml options ---------------------------------------------

# JDK Javadoc base URL (default: JDK 21)
javadoc_jdk_url = "https://docs.oracle.com/en/java/javase/21/docs/api"

# Load Google Fonts (Roboto family) — disable if your theme already provides them
# Automatically disabled when using manticore-sphinx-theme
javadoc_load_fonts = True

# Load Bulma CSS from CDN — enable for Bulma-compatible table styling
# Automatically disabled when using manticore-sphinx-theme (which bundles Bulma)
javadoc_load_bulma = True
