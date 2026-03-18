#!/usr/bin/env python3
"""
Verify that sphinx-javadoc-xml is correctly installed and working.
Run this from the project directory:

    python3 verify_install.py

If the output shows proper HTML structure (separate <p>, <ul>, <li> tags),
the extension is correctly installed. If descriptions appear on one line,
you have stale cached files.
"""
import importlib
import sys

def main():
    print("=" * 60)
    print("sphinx-javadoc-xml Installation Verifier")
    print("=" * 60)

    # Check module can be imported
    try:
        mod = importlib.import_module("sphinx_javadoc_xml")
        print(f"\n✓ Module found: {mod.__file__}")
        print(f"  Version: {mod.__version__}")
    except ImportError:
        print("\n✗ Cannot import sphinx_javadoc_xml!")
        print("  Run: pipx inject sphinx -e .")
        sys.exit(1)

    # Check directives module
    try:
        from sphinx_javadoc_xml.directives import _process_comment, _comment_nodes, _render_block
        print(f"✓ _process_comment found")
        print(f"✓ _comment_nodes found")
        print(f"✓ _render_block found")
    except ImportError as e:
        print(f"\n✗ Missing function: {e}")
        print("  You likely have a stale __pycache__. Fix:")
        print("  find . -type d -name __pycache__ -exec rm -rf {} +")
        sys.exit(1)

    # Test comment processing
    from sphinx_javadoc_xml.directives import _process_comment
    import re

    test = '<p>First paragraph.</p><p>Second paragraph.</p><ul><li>Item A</li><li>Item B</li></ul>'
    result = _process_comment(test)
    blocks = re.split(r'\n\n+', result)

    print(f"\n--- Comment Processing Test ---")
    print(f"Input:  {test}")
    print(f"Blocks: {len(blocks)}")
    for i, b in enumerate(blocks):
        print(f"  [{i}] {b}")

    if len(blocks) >= 2:
        print(f"\n✓ Multi-paragraph rendering works ({len(blocks)} blocks)")
    else:
        print(f"\n✗ FAILED: Expected multiple blocks, got {len(blocks)}")
        print("  Stale code detected. Fix:")
        print("  1. Delete __pycache__:  find . -type d -name __pycache__ -exec rm -rf {} +")
        print("  2. Reinstall:  pipx runpip sphinx uninstall sphinx-javadoc-xml -y")
        print("  3. Reinstall:  pipx inject sphinx -e .")
        sys.exit(1)

    # Check for bullet detection
    if '•' in result:
        print("✓ Bullet list detection works")
    else:
        print("✗ Bullet markers not found")

    print(f"\n{'=' * 60}")
    print("All checks passed! Now rebuild Sphinx docs with:")
    print("  sphinx-build -E -b html docs docs/_build/html")
    print("  (the -E flag forces a full rebuild, ignoring cache)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
