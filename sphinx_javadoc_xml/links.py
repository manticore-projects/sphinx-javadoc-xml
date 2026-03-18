"""
Cross-reference resolver for Java types.

Provides:
- Links to OpenJDK Javadoc for standard library types
- Internal cross-reference anchors for types defined in the XML
"""

from __future__ import annotations

from typing import Dict, Optional, Set, Tuple


# JDK 21 module mapping: package prefix → module name
# Used to build correct javadoc.io / docs.oracle.com URLs
_JDK_MODULES: Dict[str, str] = {
    "java.lang": "java.base",
    "java.lang.annotation": "java.base",
    "java.lang.invoke": "java.base",
    "java.lang.reflect": "java.base",
    "java.lang.ref": "java.base",
    "java.io": "java.base",
    "java.math": "java.base",
    "java.net": "java.base",
    "java.nio": "java.base",
    "java.nio.channels": "java.base",
    "java.nio.charset": "java.base",
    "java.nio.file": "java.base",
    "java.security": "java.base",
    "java.text": "java.base",
    "java.time": "java.base",
    "java.util": "java.base",
    "java.util.concurrent": "java.base",
    "java.util.concurrent.atomic": "java.base",
    "java.util.concurrent.locks": "java.base",
    "java.util.function": "java.base",
    "java.util.logging": "java.logging",
    "java.util.regex": "java.base",
    "java.util.stream": "java.base",
    "java.sql": "java.sql",
    "javax.sql": "java.sql",
}

# Default base URL — Oracle's JDK 21 docs
DEFAULT_JDK_URL = "https://docs.oracle.com/en/java/javase/21/docs/api"


def _find_jdk_module(qualified: str) -> Optional[str]:
    """Find the JDK module for a qualified class name."""
    # Try longest matching prefix
    parts = qualified.rsplit(".", 1)
    if len(parts) < 2:
        return None
    pkg = parts[0]
    # Walk up the package hierarchy
    while pkg:
        if pkg in _JDK_MODULES:
            return _JDK_MODULES[pkg]
        if "." not in pkg:
            break
        pkg = pkg.rsplit(".", 1)[0]
    return None


def jdk_javadoc_url(qualified: str, base_url: str = DEFAULT_JDK_URL) -> Optional[str]:
    """
    Return the full OpenJDK Javadoc URL for a standard library type.

    Parameters
    ----------
    qualified : str
        Fully qualified class name, e.g. ``java.util.List``
    base_url : str
        Base URL for the JDK Javadoc site.

    Returns
    -------
    str or None
        URL if the type is a known JDK type, else None.
    """
    module = _find_jdk_module(qualified)
    if module is None:
        return None
    # Convert dots to slashes, handle nested classes (Foo.Bar → Foo.Bar.html)
    path = qualified.replace(".", "/")
    return f"{base_url}/{module}/{path}.html"


class LinkResolver:
    """
    Resolves type references to either internal anchors or external URLs.

    Parameters
    ----------
    internal_types : set of str
        Qualified names of all types defined in the API model.
    jdk_base_url : str
        Base URL for JDK Javadoc.
    """

    def __init__(
        self,
        internal_types: Set[str],
        jdk_base_url: str = DEFAULT_JDK_URL,
    ):
        self.internal_types = internal_types
        self.jdk_base_url = jdk_base_url

    def resolve(self, qualified: str) -> Optional[Tuple[str, str]]:
        """
        Resolve a qualified type name to a (url_or_refid, kind) tuple.

        Returns
        -------
        (target, kind) or None
            - kind='internal': target is a docutils refid (anchor)
            - kind='external': target is a full URL
        """
        base = qualified.split("<")[0]

        # Check internal first
        if base in self.internal_types:
            anchor = base.replace("<", "").replace(">", "").replace(",", "").replace(" ", "")
            return (anchor, "internal")

        # Check JDK
        url = jdk_javadoc_url(base, self.jdk_base_url)
        if url:
            return (url, "external")

        return None
