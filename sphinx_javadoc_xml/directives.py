"""
Sphinx directives for rendering Java API from XML doclet output.

Features:
- Smart type name shortening (internal types + java.lang.* → simple names)
- Cross-linking to OpenJDK Javadoc and internal type references
- Javadoc inline tag processing ({@code}, {@link})
- Known Subclasses / Known Implementing Classes sections
- Merged Returns section (type + @return tag)
"""

from __future__ import annotations

import html as html_mod
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.util.docutils import SphinxDirective

from .links import LinkResolver
from .parser import (
    ApiModel,
    ConstructorInfo,
    EnumConstant,
    FieldInfo,
    JavaType,
    MethodInfo,
    PackageInfo,
    TypeInfo,
    parse_xml,
)

# Well-known packages whose types should always show simple names
_SIMPLE_NAME_PACKAGES = frozenset([
    "java.lang", "java.lang.annotation", "java.lang.invoke",
    "java.lang.reflect", "java.lang.ref",
])


# ---------------------------------------------------------------------------
# Javadoc inline tag processing
# ---------------------------------------------------------------------------

_JAVADOC_CODE_RE = re.compile(r'\{@code\s+(.*?)\}', re.DOTALL)
_JAVADOC_LINK_RE = re.compile(r'\{@link(?:plain)?\s+([^}]+)\}')
_JAVADOC_VALUE_RE = re.compile(r'\{@value\s+([^}]*)\}')
_JAVADOC_INHERITDOC_RE = re.compile(r',?\s*\{@inheritDoc\}\s*,?\s*')

# HTML tag patterns
_HTML_CODE_RE = re.compile(r'<code>(.*?)</code>', re.DOTALL)
_HTML_PRE_RE = re.compile(r'<pre>(.*?)</pre>', re.DOTALL)
_HTML_BOLD_RE = re.compile(r'<b>(.*?)</b>', re.DOTALL)
_HTML_ITALIC_RE = re.compile(r'<i>(.*?)</i>', re.DOTALL)
_HTML_LINK_RE = re.compile(r'<a\s[^>]*?(?:href=["\']([^"\']*)["\'])?[^>]*>(.*?)</a>', re.DOTALL)
_HTML_BLOCK_OPEN_RE = re.compile(r'<(?:p|div|blockquote|dl)(?:\s[^>]*)?\s*>', re.IGNORECASE)
_HTML_BLOCK_CLOSE_RE = re.compile(r'</(?:p|div|blockquote|dl)>', re.IGNORECASE)
_HTML_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_HTML_REMAINING_RE = re.compile(r'<[^>]+>')


def _process_comment(text: str) -> str:
    """Process Javadoc inline tags and HTML into structured plain text.

    Preserves paragraph breaks (as \\n\\n) and line breaks (as \\n)
    so that _comment_nodes can render multi-paragraph descriptions.
    """
    if not text:
        return text

    # Accumulator for protected code spans
    _code_spans = []

    def _protect(content: str) -> str:
        """Replace a code span with a placeholder safe from HTML stripping."""
        idx = len(_code_spans)
        _code_spans.append(content)
        return f'\x00CODE{idx}\x00'

    def _restore(text: str) -> str:
        """Restore all protected code spans as ``...`` markers."""
        for i, content in enumerate(_code_spans):
            text = text.replace(f'\x00CODE{i}\x00', f'``{content}``')
        return text

    # 1. Remove {@inheritDoc} (with surrounding commas/spaces from doclet)
    text = _JAVADOC_INHERITDOC_RE.sub(' ', text)

    # 2. Protect code spans BEFORE any HTML processing
    # {@code X} → placeholder (handles multiline, skips empty)
    def _code_repl(m):
        content = m.group(1).strip()
        content = re.sub(r'\s+', ' ', content)
        if not content:
            return ''
        return _protect(content)
    text = _JAVADOC_CODE_RE.sub(_code_repl, text)

    # {@link Foo#bar} → placeholder
    def _link_repl(m):
        ref = m.group(1).strip()
        parts = ref.split(None, 1)
        target = parts[0].replace('#', '.')
        label = parts[1] if len(parts) > 1 else target
        display = label.rsplit('.', 1)[-1] if '.' in label else label
        return _protect(display)
    text = _JAVADOC_LINK_RE.sub(_link_repl, text)

    # {@value X} → placeholder
    text = _JAVADOC_VALUE_RE.sub(lambda m: _protect(m.group(1).strip()) if m.group(1).strip() else '', text)

    # 3. HTML inline conversions → placeholders for <code>
    def _html_code_repl(m):
        content = m.group(1).strip()
        content = re.sub(r'\s+', ' ', content)
        if not content:
            return ''
        return _protect(content)
    text = _HTML_CODE_RE.sub(_html_code_repl, text)

    text = _HTML_BOLD_RE.sub(r'\1', text)
    text = _HTML_ITALIC_RE.sub(r'\1', text)
    text = _HTML_LINK_RE.sub(r'\2', text)

    # 4. Structural HTML → text markers
    text = _HTML_PRE_RE.sub(lambda m: '\n\n' + m.group(1).strip() + '\n\n', text)
    text = re.sub(r'<li(?:\s[^>]*)?>', '\n• ', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '', text, flags=re.IGNORECASE)
    text = _HTML_BR_RE.sub('\n', text)
    text = re.sub(r'</?(?:ul|ol)(?:\s[^>]*)?\s*>', '\n', text, flags=re.IGNORECASE)
    text = _HTML_BLOCK_OPEN_RE.sub('\n\n', text)
    text = _HTML_BLOCK_CLOSE_RE.sub('\n\n', text)

    # 5. Strip remaining HTML tags (code spans are protected as placeholders)
    text = _HTML_REMAINING_RE.sub('', text)

    # 6. Decode HTML entities
    text = html_mod.unescape(text)

    # 7. Restore protected code spans as ``...`` markers
    text = _restore(text)

    # 8. Clean up Javadoc comma artifacts
    text = text.replace(',``', '``').replace('``,', '``')

    # 9. Normalize whitespace per line, preserve paragraph structure
    lines = text.split('\n')
    cleaned = [re.sub(r'[ \t]+', ' ', l).strip() for l in lines]
    # Remove lines that are just punctuation (artifacts from </p>. etc.)
    cleaned = [l for l in cleaned if not re.match(r'^[.,;:!?]+$', l)]
    text = '\n'.join(cleaned)

    # Collapse 3+ newlines → 2 (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Keep bullet items grouped
    text = re.sub(r'\n\n(• )', r'\n\1', text)

    text = text.strip()

    return text


def _make_inline_nodes(text: str) -> List[nodes.Node]:
    """Split text on `` markers to create inline + literal nodes."""
    result: List[nodes.Node] = []
    parts = text.split('``')
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part:
                result.append(nodes.inline(text=part))
        else:
            result.append(nodes.literal(text=part))
    return result


def _flat_comment(text: str) -> str:
    """Process comment to a single-line string for summary tables."""
    processed = _process_comment(text)
    # Collapse all whitespace to single spaces for table cells
    return re.sub(r'\s+', ' ', processed).strip()


def _comment_nodes(text: str) -> nodes.container:
    """Convert Javadoc comment text into a container with proper paragraphs,
    bullet lists, numbered lists, and preserved line breaks."""
    processed = _process_comment(text)

    # Split into paragraph blocks on double-newline
    blocks = re.split(r'\n\n+', processed)
    blocks = [b.strip() for b in blocks if b.strip()]

    if not blocks:
        return nodes.paragraph()

    # Single block, single line → simple paragraph
    if len(blocks) == 1 and '\n' not in blocks[0]:
        para = nodes.paragraph()
        for n in _make_inline_nodes(blocks[0]):
            para += n
        return para

    container = nodes.container()
    for block in blocks:
        lines = block.split('\n')
        _render_block(container, lines)
    return container


# Patterns for list detection
_BULLET_RE = re.compile(r'^[•\-\*]\s+')
_NUMBERED_RE = re.compile(r'^(\d+)[.)]\s+')


def _render_block(container: nodes.container, lines: List[str]) -> None:
    """Render a block of lines into the container, detecting lists."""
    # Classify each line
    leading_text = []
    list_items = []
    trailing_text = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        is_bullet = bool(_BULLET_RE.match(stripped))
        is_numbered = bool(_NUMBERED_RE.match(stripped))

        if is_bullet or is_numbered:
            in_list = True
            if is_bullet:
                item_text = _BULLET_RE.sub('', stripped)
            else:
                item_text = _NUMBERED_RE.sub('', stripped)
            list_items.append(item_text)
        elif in_list:
            trailing_text.append(stripped)
        else:
            leading_text.append(stripped)

    # No list items → join everything into a single paragraph
    if not list_items:
        all_text = ' '.join(l.strip() for l in lines if l.strip())
        para = nodes.paragraph()
        for n in _make_inline_nodes(all_text):
            para += n
        container += para
        return

    # Has list items → render leading text, then list, then trailing
    if leading_text:
        para = nodes.paragraph()
        for n in _make_inline_nodes(' '.join(leading_text)):
            para += n
        container += para

    bl = nodes.bullet_list()
    for item_text in list_items:
        li = nodes.list_item()
        p = nodes.paragraph()
        for n in _make_inline_nodes(item_text):
            p += n
        li += p
        bl += li
    container += bl

    if trailing_text:
        para = nodes.paragraph()
        for n in _make_inline_nodes(' '.join(trailing_text)):
            para += n
        container += para


# ---------------------------------------------------------------------------
# Anchor IDs
# ---------------------------------------------------------------------------

def _anchor_id(qualified: str, member: str = "") -> str:
    base = qualified.replace("<", "").replace(">", "").replace(",", "").replace(" ", "")
    if member:
        base += f".{member}"
    return base


def _singular(label: str) -> str:
    """Plurals → singular for table headers: Classes→Class, Interfaces→Interface, Enums→Enum."""
    if label.endswith("sses"):     # Classes → Class
        return label[:-2]
    if label.endswith("es"):       # Interfaces → Interface
        return label[:-1]
    if label.endswith("s"):        # Enums → Enum
        return label[:-1]
    return label


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

def _make_section(title_text: str, id_str: str) -> nodes.section:
    sec = nodes.section(ids=[id_str])
    sec += nodes.title(text=title_text)
    return sec


def _make_table(headers: List[str], rows: List[List[nodes.Node]]) -> nodes.table:
    table = nodes.table(classes=["javadoc-table"])
    tgroup = nodes.tgroup(cols=len(headers))
    table += tgroup
    for _ in headers:
        tgroup += nodes.colspec(colwidth=1)
    thead = nodes.thead()
    tgroup += thead
    header_row = nodes.row()
    for h in headers:
        entry = nodes.entry()
        entry += nodes.paragraph(text=h)
        header_row += entry
    thead += header_row
    tbody = nodes.tbody()
    tgroup += tbody
    for row_cells in rows:
        row = nodes.row()
        for cell_node in row_cells:
            entry = nodes.entry()
            if isinstance(cell_node, nodes.Node):
                entry += cell_node
            else:
                entry += nodes.paragraph(text=str(cell_node))
            row += entry
        tbody += row
    return table


# ---------------------------------------------------------------------------
# Type rendering with cross-links and smart name shortening
# ---------------------------------------------------------------------------

class _TypeRenderer:
    """Renders TypeInfo as docutils nodes with hyperlinks."""

    def __init__(
        self,
        resolver: LinkResolver,
        internal_types: Set[str],
        strip_pkg: str = "",
    ):
        self.resolver = resolver
        self.internal_types = internal_types
        self.strip_pkg = strip_pkg

    def _smart_name(self, qualified: str) -> str:
        """Compute the shortest unambiguous display name for a type.

        Rules:
        - java.lang.* → simple name (String, Object, Integer, ...)
        - Types defined in the API model → simple name
        - Same-package types → simple name
        - Other external types → fully qualified
        """
        base = qualified.split("<")[0]

        # Primitives and type variables
        if "." not in base:
            return base

        pkg = base.rsplit(".", 1)[0]

        # java.lang.* always simplified
        if pkg in _SIMPLE_NAME_PACKAGES:
            return base.rsplit(".", 1)[-1]

        # Internal API type → simple name
        if base in self.internal_types:
            return base.rsplit(".", 1)[-1]

        # Same package → strip pkg prefix
        if self.strip_pkg and base.startswith(self.strip_pkg + "."):
            return base[len(self.strip_pkg) + 1:]

        return base

    def simplify_name(self, qualified: str) -> str:
        """Public accessor for smart name (used for TypeParamInfo bounds)."""
        return self._smart_name(qualified)

    def type_str(self, t: TypeInfo) -> str:
        """Render a type as a plain string with smart names."""
        if t.wildcard:
            result = "?"
            if t.extends_bound:
                result += f" extends {self.type_str(t.extends_bound)}"
            elif t.super_bound:
                result += f" super {self.type_str(t.super_bound)}"
            return result

        base = self._smart_name(t.base_qualified)

        if t.generics:
            generic_str = ", ".join(self.type_str(g) for g in t.generics)
            base = f"{base}<{generic_str}>"
        if t.dimension:
            base += "[]" * t.dimension
        return base

    def param_list_str(self, params) -> str:
        return ", ".join(
            f"{self.type_str(p.type)} {p.name}" for p in params
        )

    def type_nodes(self, t: TypeInfo) -> List[nodes.Node]:
        """Build docutils nodes for a type with hyperlinks."""
        result: List[nodes.Node] = []

        if t.wildcard:
            result.append(nodes.inline(text="?", classes=["javadoc-type"]))
            if t.extends_bound:
                result.append(nodes.inline(text=" extends ", classes=["javadoc-keyword"]))
                result.extend(self.type_nodes(t.extends_bound))
            elif t.super_bound:
                result.append(nodes.inline(text=" super ", classes=["javadoc-keyword"]))
                result.extend(self.type_nodes(t.super_bound))
            return result

        base_qualified = t.base_qualified
        display_name = self._smart_name(base_qualified)

        link = self.resolver.resolve(base_qualified)
        if link:
            target, kind = link
            if kind == "internal":
                ref = nodes.reference(
                    text=display_name, refid=target,
                    classes=["javadoc-type", "javadoc-xref"],
                )
            else:
                ref = nodes.reference(
                    text=display_name, refuri=target,
                    classes=["javadoc-type", "javadoc-xref-external"],
                )
                ref["target"] = "_blank"
            result.append(ref)
        else:
            result.append(nodes.inline(text=display_name, classes=["javadoc-type"]))

        if t.generics:
            result.append(nodes.inline(text="<", classes=["javadoc-type"]))
            for i, g in enumerate(t.generics):
                if i > 0:
                    result.append(nodes.inline(text=", ", classes=["javadoc-type"]))
                result.extend(self.type_nodes(g))
            result.append(nodes.inline(text=">", classes=["javadoc-type"]))

        if t.dimension:
            result.append(nodes.inline(text="[]" * t.dimension, classes=["javadoc-type"]))

        return result

    def type_inline(self, t: TypeInfo) -> nodes.inline:
        container = nodes.inline(classes=["javadoc-type-container"])
        for n in self.type_nodes(t):
            container += n
        return container

    def exceptions_str(self, exceptions: List[str]) -> str:
        if not exceptions:
            return ""
        return " throws " + ", ".join(self._smart_name(e) for e in exceptions)

    def exceptions_nodes(self, exceptions: List[str]) -> List[nodes.Node]:
        if not exceptions:
            return []
        result: List[nodes.Node] = [
            nodes.inline(text=" throws ", classes=["javadoc-keyword"])
        ]
        for i, exc in enumerate(exceptions):
            if i > 0:
                result.append(nodes.inline(text=", "))
            t = TypeInfo(qualified=exc)
            result.extend(self.type_nodes(t))
        return result


# ---------------------------------------------------------------------------
# Node builder for a single Java type
# ---------------------------------------------------------------------------

class _NodeBuilder:
    def __init__(
        self,
        jtype: JavaType,
        renderer: _TypeRenderer,
        public_only: bool = False,
        reverse_index: Optional[Dict] = None,
    ):
        self.jtype = jtype
        self.r = renderer
        self.public_only = public_only
        self.reverse_index = reverse_index or {}

    def _visible(self, scope: str) -> bool:
        if not self.public_only:
            return True
        return scope in ("public", "protected")

    def build(self) -> nodes.section:
        jt = self.jtype
        qualified_id = _anchor_id(jt.qualified)

        # Title with simplified type params
        title = f"{jt.kind.title()} {jt.name}"
        if jt.type_params:
            tp_str = ", ".join(
                tp.display(simplify=self.r.simplify_name) for tp in jt.type_params
            )
            title += f"<{tp_str}>"
        sec = _make_section(title, qualified_id)
        sec["classes"].append("javadoc-type-section")
        sec["classes"].append(f"javadoc-{jt.kind}")

        # -- Header block
        header = nodes.container(classes=["javadoc-type-header"])

        # Package
        pkg_name = jt.qualified[: jt.qualified.rfind("." + jt.name.split(".")[0])]
        header += nodes.paragraph(
            text=f"Package: {pkg_name}", classes=["javadoc-package-name"]
        )

        # Declaration
        decl = nodes.paragraph(classes=["javadoc-declaration"])
        if jt.scope:
            decl += nodes.inline(text=jt.scope + " ", classes=["javadoc-modifier"])
        if jt.abstract:
            decl += nodes.inline(text="abstract ", classes=["javadoc-modifier"])
        decl += nodes.inline(text=f"{jt.kind} ", classes=["javadoc-keyword"])
        decl += nodes.strong(text=jt.name)

        # Type params (with simplified bounds)
        if jt.type_params:
            tp_str = ", ".join(
                tp.display(simplify=self.r.simplify_name) for tp in jt.type_params
            )
            decl += nodes.inline(text=f"<{tp_str}>", classes=["javadoc-type"])

        # Superclass
        if jt.superclass:
            super_base = jt.superclass.base_qualified
            if super_base not in ("java.lang.Object", "java.lang.Enum"):
                decl += nodes.inline(text=" extends ")
                decl += self.r.type_inline(jt.superclass)

        # Interfaces
        if jt.interfaces:
            kw = " implements " if jt.kind != "interface" else " extends "
            decl += nodes.inline(text=kw)
            for i, iface in enumerate(jt.interfaces):
                if i > 0:
                    decl += nodes.inline(text=", ")
                decl += self.r.type_inline(iface)

        header += decl

        if jt.comment:
            header += _comment_nodes(jt.comment)
            header.children[-1]["classes"].append("javadoc-description")

        if jt.tags:
            header += self._build_tags(jt.tags)

        sec += header

        # -- Known Subclasses / Implementing Classes
        ri = self.reverse_index.get(jt.qualified, {})
        subclasses = ri.get("subclasses", [])
        implementors = ri.get("implementors", [])

        if subclasses:
            sub_sec = nodes.container(classes=["javadoc-hierarchy"])
            sub_p = nodes.paragraph()
            sub_p += nodes.strong(text="Known Direct Subclasses: ")
            for i, sc in enumerate(sorted(subclasses)):
                if i > 0:
                    sub_p += nodes.inline(text=", ")
                name = sc.rsplit(".", 1)[-1]
                sub_p += nodes.reference(
                    text=name, refid=_anchor_id(sc),
                    classes=["javadoc-xref"],
                )
            sub_sec += sub_p
            sec += sub_sec

        if implementors:
            impl_sec = nodes.container(classes=["javadoc-hierarchy"])
            impl_p = nodes.paragraph()
            impl_p += nodes.strong(text="Known Implementing Classes: ")
            for i, ic in enumerate(sorted(implementors)):
                if i > 0:
                    impl_p += nodes.inline(text=", ")
                name = ic.rsplit(".", 1)[-1]
                impl_p += nodes.reference(
                    text=name, refid=_anchor_id(ic),
                    classes=["javadoc-xref"],
                )
            impl_sec += impl_p
            sec += impl_sec

        # -- Sections
        if jt.enum_constants:
            sec += self._build_enum_summary()
            sec += self._build_enum_detail()

        visible_fields = [f for f in jt.fields if self._visible(f.scope)]
        if visible_fields:
            sec += self._build_field_summary(visible_fields)
            sec += self._build_field_detail(visible_fields)

        visible_ctors = [c for c in jt.constructors if self._visible(c.scope)]
        if visible_ctors:
            sec += self._build_ctor_summary(visible_ctors)
            sec += self._build_ctor_detail(visible_ctors)

        visible_methods = [m for m in jt.methods if self._visible(m.scope)]
        if visible_methods:
            sec += self._build_method_summary(visible_methods)
            sec += self._build_method_detail(visible_methods)

        return sec

    # -- Tags --

    def _build_tags(self, tags: List) -> nodes.container:
        container = nodes.container(classes=["javadoc-tags"])
        for tag in tags:
            if tag.name in ("param", "return"):
                continue
            text = tag.text
            if tag.name and text.startswith(f"@{tag.name}"):
                text = text[len(f"@{tag.name}"):].strip()
            if tag.name == "author":
                p = nodes.paragraph(classes=["javadoc-tag-item"])
                p += nodes.strong(text="Author: ")
                p += nodes.inline(text=_flat_comment(text))
                container += p
            elif tag.name == "see":
                ref = text.strip()
                if ref.startswith("#"):
                    ref = ref[1:]
                display = ref.rsplit(".", 1)[-1] if "." in ref else ref
                p = nodes.paragraph(classes=["javadoc-tag-item"])
                p += nodes.strong(text="See Also: ")
                p += nodes.literal(text=_flat_comment(display))
                container += p
            elif tag.name == "since":
                p = nodes.paragraph(classes=["javadoc-tag-item"])
                p += nodes.strong(text="Since: ")
                p += nodes.inline(text=_flat_comment(text))
                container += p
            elif tag.name == "deprecated":
                p = nodes.paragraph(classes=["javadoc-tag-item", "javadoc-deprecated"])
                p += nodes.strong(text="Deprecated. ")
                p += nodes.inline(text=_flat_comment(text))
                container += p
            else:
                processed = _flat_comment(text)
                if processed:
                    p = nodes.paragraph(classes=["javadoc-tag-item"])
                    p += nodes.strong(text=f"@{tag.name}: ")
                    p += nodes.inline(text=processed)
                    container += p
        return container

    # -- Enum Constants --

    def _build_enum_summary(self) -> nodes.section:
        sec = _make_section(
            "Enum Constants", _anchor_id(self.jtype.qualified, "enum-constants")
        )
        sec["classes"].append("javadoc-summary")
        rows = []
        for ec in self.jtype.enum_constants:
            name_cell = nodes.container()
            name_p = nodes.paragraph()
            name_p += nodes.reference(
                text=ec.name,
                refid=_anchor_id(self.jtype.qualified, f"constant.{ec.name}"),
                classes=["javadoc-member-link"],
            )
            name_cell += name_p
            if ec.comment:
                desc = _flat_comment(ec.comment)
                name_cell += nodes.paragraph(
                    text=desc, classes=["javadoc-summary-desc"]
                )
            rows.append([name_cell])
        sec += _make_table(["Enum Constant"], rows)
        return sec

    def _build_enum_detail(self) -> nodes.section:
        sec = _make_section(
            "Enum Constant Detail",
            _anchor_id(self.jtype.qualified, "enum-constant-detail"),
        )
        sec["classes"].append("javadoc-detail")
        for ec in self.jtype.enum_constants:
            detail = nodes.section(
                ids=[_anchor_id(self.jtype.qualified, f"constant.{ec.name}")],
                classes=["javadoc-member-detail"],
            )
            detail += nodes.title(text=ec.name)
            sig = nodes.paragraph(
                text=f"public static final {self.jtype.name} {ec.name}",
                classes=["javadoc-signature"],
            )
            detail += sig
            if ec.comment:
                desc = _comment_nodes(ec.comment)
                desc["classes"].append("javadoc-member-description")
                detail += desc
            if ec.tags:
                detail += self._build_tags(ec.tags)
            sec += detail
        return sec

    # -- Fields --

    def _build_field_summary(self, fields: List[FieldInfo]) -> nodes.section:
        sec = _make_section(
            "Field Summary", _anchor_id(self.jtype.qualified, "field-summary")
        )
        sec["classes"].append("javadoc-summary")
        rows = []
        for f in fields:
            mod_p = nodes.paragraph()
            mod_p += nodes.inline(text=f.modifiers + " ", classes=["javadoc-modifier"])
            mod_p += self.r.type_inline(f.type)

            name_cell = nodes.container()
            name_p = nodes.paragraph()
            name_p += nodes.reference(
                text=f.name,
                refid=_anchor_id(self.jtype.qualified, f"field.{f.name}"),
                classes=["javadoc-member-link"],
            )
            name_cell += name_p
            if f.comment:
                desc = _flat_comment(f.comment)
                name_cell += nodes.paragraph(
                    text=desc, classes=["javadoc-summary-desc"]
                )
            rows.append([mod_p, name_cell])
        sec += _make_table(["Modifier and Type", "Field"], rows)
        return sec

    def _build_field_detail(self, fields: List[FieldInfo]) -> nodes.section:
        sec = _make_section(
            "Field Detail", _anchor_id(self.jtype.qualified, "field-detail")
        )
        sec["classes"].append("javadoc-detail")
        for f in fields:
            detail = nodes.section(
                ids=[_anchor_id(self.jtype.qualified, f"field.{f.name}")],
                classes=["javadoc-member-detail"],
            )
            detail += nodes.title(text=f.name)
            sig_text = f"{f.modifiers} {self.r.type_str(f.type)} {f.name}"
            if f.constant_value:
                sig_text += f" = {f.constant_value}"
            detail += nodes.paragraph(
                text=sig_text.strip(), classes=["javadoc-signature"]
            )
            if f.comment:
                desc = _comment_nodes(f.comment)
                desc["classes"].append("javadoc-member-description")
                detail += desc
            sec += detail
        return sec

    # -- Constructors --

    def _build_ctor_summary(self, ctors: List[ConstructorInfo]) -> nodes.section:
        sec = _make_section(
            "Constructor Summary",
            _anchor_id(self.jtype.qualified, "constructor-summary"),
        )
        sec["classes"].append("javadoc-summary")
        rows = []
        for c in ctors:
            name_cell = nodes.container()
            sig_p = nodes.paragraph()
            sig = f"{c.name}({self.r.param_list_str(c.parameters)})"
            sig_p += nodes.reference(
                text=sig,
                refid=_anchor_id(self.jtype.qualified,
                                 f"ctor.{c.name}.{len(c.parameters)}"),
                classes=["javadoc-member-link"],
            )
            name_cell += sig_p
            if c.comment:
                desc = _flat_comment(c.comment)
                name_cell += nodes.paragraph(
                    text=desc, classes=["javadoc-summary-desc"]
                )
            rows.append([name_cell])
        sec += _make_table(["Constructor"], rows)
        return sec

    def _build_ctor_detail(self, ctors: List[ConstructorInfo]) -> nodes.section:
        sec = _make_section(
            "Constructor Detail",
            _anchor_id(self.jtype.qualified, "constructor-detail"),
        )
        sec["classes"].append("javadoc-detail")
        for c in ctors:
            detail = nodes.section(
                ids=[_anchor_id(self.jtype.qualified,
                                f"ctor.{c.name}.{len(c.parameters)}")],
                classes=["javadoc-member-detail"],
            )
            detail += nodes.title(text=c.name)
            sig_text = f"{c.scope} {c.name}({self.r.param_list_str(c.parameters)})"
            if c.exceptions:
                sig_text += self.r.exceptions_str(c.exceptions)
            detail += nodes.paragraph(
                text=sig_text.strip(), classes=["javadoc-signature"]
            )
            if c.comment:
                desc = _comment_nodes(c.comment)
                desc["classes"].append("javadoc-member-description")
                detail += desc

            # Parse @param tag descriptions
            param_descs = self._parse_param_tags(c.tags)

            if c.parameters:
                detail += self._build_detail_section("Parameters", [
                    self._param_entry(p, param_descs.get(p.name, ""))
                    for p in c.parameters
                ])
            if c.exceptions:
                detail += self._build_detail_section("Throws", [
                    self._exception_entry(exc) for exc in c.exceptions
                ])

            # Other tags (skip @param — already merged above)
            self._render_remaining_tags(c.tags, detail)

            sec += detail
        return sec

    # -- Methods --

    def _build_method_summary(self, methods: List[MethodInfo]) -> nodes.section:
        sec = _make_section(
            "Method Summary", _anchor_id(self.jtype.qualified, "method-summary")
        )
        sec["classes"].append("javadoc-summary")
        rows = []
        for m in methods:
            mod_p = nodes.paragraph()
            mod_p += nodes.inline(text=m.modifiers + " ", classes=["javadoc-modifier"])
            mod_p += self.r.type_inline(m.return_type)

            name_cell = nodes.container()
            sig_p = nodes.paragraph()
            sig = f"{m.name}({self.r.param_list_str(m.parameters)})"
            sig_p += nodes.reference(
                text=sig,
                refid=_anchor_id(self.jtype.qualified, f"method.{m.anchor_key}"),
                classes=["javadoc-member-link"],
            )
            name_cell += sig_p
            if m.comment:
                desc = _flat_comment(m.comment)
                name_cell += nodes.paragraph(
                    text=desc, classes=["javadoc-summary-desc"]
                )
            rows.append([mod_p, name_cell])
        sec += _make_table(["Modifier and Type", "Method"], rows)
        return sec

    def _build_method_detail(self, methods: List[MethodInfo]) -> nodes.section:
        sec = _make_section(
            "Method Detail", _anchor_id(self.jtype.qualified, "method-detail")
        )
        sec["classes"].append("javadoc-detail")
        for m in methods:
            detail = nodes.section(
                ids=[_anchor_id(self.jtype.qualified, f"method.{m.anchor_key}")],
                classes=["javadoc-member-detail"],
            )
            detail += nodes.title(text=m.name)

            sig_text = (
                f"{m.modifiers} {self.r.type_str(m.return_type)} "
                f"{m.name}({self.r.param_list_str(m.parameters)})"
            )
            if m.exceptions:
                sig_text += self.r.exceptions_str(m.exceptions)
            detail += nodes.paragraph(
                text=sig_text.strip(), classes=["javadoc-signature"]
            )

            if m.comment:
                desc = _comment_nodes(m.comment)
                desc["classes"].append("javadoc-member-description")
                detail += desc

            # Parse @param tag descriptions
            param_descs = self._parse_param_tags(m.tags)

            if m.parameters:
                detail += self._build_detail_section("Parameters", [
                    self._param_entry(p, param_descs.get(p.name, ""))
                    for p in m.parameters
                ])

            # Merged Returns: type + @return description
            if m.return_type.qualified != "void":
                ret_entry = nodes.paragraph(classes=["javadoc-detail-entry"])
                ret_entry += self.r.type_inline(m.return_type)
                for tag in m.tags:
                    if tag.name == "return":
                        text = tag.text
                        if text.startswith("@return"):
                            text = text[len("@return"):].strip()
                        if text:
                            ret_entry += nodes.inline(
                                text=f" — {_flat_comment(text)}"
                            )
                        break
                detail += self._build_detail_section("Returns", [ret_entry])

            if m.exceptions:
                detail += self._build_detail_section("Throws", [
                    self._exception_entry(exc) for exc in m.exceptions
                ])

            # Other tags (skip @param and @return — already merged above)
            self._render_remaining_tags(m.tags, detail)

            sec += detail
        return sec

    # -- Helpers --

    def _build_detail_section(
        self, label: str, entries: List[nodes.Node]
    ) -> nodes.container:
        """Build a labeled detail section (Parameters, Returns, Throws)
        with consistent styling."""
        block = nodes.container(classes=["javadoc-detail-block"])
        block += nodes.paragraph(text=label, classes=["javadoc-detail-label"])
        for entry in entries:
            block += entry
        return block

    @staticmethod
    def _parse_param_tags(tags) -> dict:
        """Extract @param descriptions into a {name: description} dict."""
        param_descs = {}
        for tag in tags:
            if tag.name != "param":
                continue
            text = tag.text
            # Strip leading "@param "
            if text.startswith("@param"):
                text = text[len("@param"):].strip()
            # First word is the param name, rest is description
            parts = text.split(None, 1)
            if parts:
                pname = parts[0]
                raw_desc = parts[1] if len(parts) > 1 else ""
                if raw_desc:
                    # Clean the description through the comment processor
                    pdesc = _flat_comment(raw_desc)
                    # Skip if empty after processing, or if it's just whitespace
                    if pdesc and pdesc.strip():
                        param_descs[pname] = pdesc
        return param_descs

    def _param_entry(self, p, description: str = "") -> nodes.paragraph:
        para = nodes.paragraph(classes=["javadoc-detail-entry"])
        para += nodes.literal(text=p.name)
        para += nodes.inline(text=" — ")
        para += self.r.type_inline(p.type)
        if description:
            para += nodes.inline(text=f" — {description}")
        return para

    def _exception_entry(self, exc: str) -> nodes.paragraph:
        para = nodes.paragraph(classes=["javadoc-detail-entry"])
        t = TypeInfo(qualified=exc)
        for n in self.r.type_nodes(t):
            para += n
        return para

    def _render_remaining_tags(self, tags, detail) -> None:
        """Render non-param/return tags with proper formatting."""
        for tag in tags:
            if tag.name in ("param", "return"):
                continue
            text = tag.text
            if tag.name and text.startswith(f"@{tag.name}"):
                text = text[len(f"@{tag.name}"):].strip()
            if tag.name == "see":
                ref = text.strip()
                if ref.startswith("#"):
                    ref = ref[1:]
                display = ref.rsplit(".", 1)[-1] if "." in ref else ref
                p = nodes.paragraph(classes=["javadoc-tag-detail"])
                p += nodes.strong(text="See Also: ")
                p += nodes.literal(text=_flat_comment(display))
                detail += p
            elif tag.name == "author":
                p = nodes.paragraph(classes=["javadoc-tag-detail"])
                p += nodes.strong(text="Author: ")
                p += nodes.inline(text=_flat_comment(text))
                detail += p
            elif tag.name == "since":
                p = nodes.paragraph(classes=["javadoc-tag-detail"])
                p += nodes.strong(text="Since: ")
                p += nodes.inline(text=_flat_comment(text))
                detail += p
            elif tag.name == "deprecated":
                p = nodes.paragraph(classes=["javadoc-tag-detail", "javadoc-deprecated"])
                p += nodes.strong(text="Deprecated. ")
                p += nodes.inline(text=_flat_comment(text))
                detail += p
            else:
                processed = _flat_comment(text)
                if processed:
                    p = nodes.paragraph(classes=["javadoc-tag-detail"])
                    p += nodes.strong(text=f"@{tag.name}: ")
                    p += nodes.inline(text=processed)
                    detail += p


# ---------------------------------------------------------------------------
# Sphinx Directives
# ---------------------------------------------------------------------------

def _build_context(xml_path, options):
    """Parse XML and build shared rendering context."""
    model = parse_xml(xml_path)
    internal = model.all_qualified_names()
    reverse_index = model.build_reverse_index()
    jdk_url = options.get("jdk-url", "") or \
        "https://docs.oracle.com/en/java/javase/21/docs/api"
    resolver = LinkResolver(internal, jdk_base_url=jdk_url)
    return model, resolver, internal, reverse_index


class JavadocApiDirective(SphinxDirective):
    """
    Render the full Java API from an XML doclet file.

    Usage::

        .. javadoc-api:: _static/api.xml
           :package: com.example
           :public-only:
           :jdk-url: https://docs.oracle.com/en/java/javase/21/docs/api
    """

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    option_spec = {
        "package": directives.unchanged,
        "public-only": directives.flag,
        "jdk-url": directives.unchanged,
    }

    def run(self) -> List[nodes.Node]:
        env = self.state.document.settings.env
        rel_path = self.arguments[0]
        source_dir = Path(env.srcdir)
        xml_path = source_dir / rel_path
        if not xml_path.exists():
            doc_dir = Path(env.doc2path(env.docname)).parent
            xml_path = doc_dir / rel_path
        if not xml_path.exists():
            return [self.state_machine.reporter.error(
                f"javadoc-api: XML file not found: {rel_path}",
                line=self.lineno,
            )]

        env.note_dependency(str(xml_path))

        model, resolver, internal, reverse_index = _build_context(xml_path, self.options)
        public_only = "public-only" in self.options
        pkg_filter = self.options.get("package")

        result: List[nodes.Node] = []
        for pkg in model.packages:
            if pkg_filter:
                # Prefix match: "net.sf.jsqlparser" matches itself and all sub-packages
                if pkg.name != pkg_filter and not pkg.name.startswith(pkg_filter + "."):
                    continue
            result.extend(self._render_package(
                pkg, public_only, resolver, internal, reverse_index
            ))
        return result

    def _render_package(
        self, pkg, public_only, resolver, internal, reverse_index,
    ) -> List[nodes.Node]:
        pkg_id = _anchor_id(pkg.name)
        sec = _make_section(f"Package {pkg.name}", pkg_id)
        sec["classes"].append("javadoc-package-section")

        if pkg.comment:
            sec += _comment_nodes(pkg.comment)

        for kind, label in [
            ("interface", "Interfaces"),
            ("class", "Classes"),
            ("enum", "Enums"),
        ]:
            types = [t for t in pkg.types if t.kind == kind]
            if public_only:
                types = [t for t in types if t.scope == "public"]
            if not types:
                continue

            kind_sec = _make_section(label, _anchor_id(pkg.name, label.lower()))
            kind_sec["classes"].append("javadoc-kind-group")
            rows = []
            for jt in types:
                name_p = nodes.paragraph()
                name_p += nodes.reference(
                    text=jt.name, refid=_anchor_id(jt.qualified),
                    classes=["javadoc-member-link"],
                )
                desc = _flat_comment(jt.comment) if jt.comment else ""
                desc_p = nodes.paragraph(text=desc)
                rows.append([name_p, desc_p])
            kind_sec += _make_table([_singular(label), "Description"], rows)
            sec += kind_sec

        result: List[nodes.Node] = [sec]

        renderer = _TypeRenderer(resolver, internal, strip_pkg=pkg.name)
        for jt in pkg.types:
            if public_only and jt.scope != "public":
                continue
            builder = _NodeBuilder(
                jt, renderer, public_only=public_only,
                reverse_index=reverse_index,
            )
            result.append(builder.build())

        return result


class JavadocClassDirective(SphinxDirective):
    """Render a single Java type from an XML doclet file."""

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    option_spec = {
        "class": directives.unchanged_required,
        "public-only": directives.flag,
        "jdk-url": directives.unchanged,
    }

    def run(self) -> List[nodes.Node]:
        env = self.state.document.settings.env
        rel_path = self.arguments[0]
        source_dir = Path(env.srcdir)
        xml_path = source_dir / rel_path
        if not xml_path.exists():
            doc_dir = Path(env.doc2path(env.docname)).parent
            xml_path = doc_dir / rel_path
        if not xml_path.exists():
            return [self.state_machine.reporter.error(
                f"javadoc-class: XML file not found: {rel_path}",
                line=self.lineno,
            )]

        env.note_dependency(str(xml_path))

        model, resolver, internal, reverse_index = _build_context(xml_path, self.options)
        public_only = "public-only" in self.options
        class_name = self.options["class"]

        for pkg in model.packages:
            for jt in pkg.types:
                if jt.qualified == class_name or jt.name == class_name:
                    renderer = _TypeRenderer(resolver, internal, strip_pkg=pkg.name)
                    builder = _NodeBuilder(
                        jt, renderer, public_only=public_only,
                        reverse_index=reverse_index,
                    )
                    return [builder.build()]

        return [self.state_machine.reporter.error(
            f"javadoc-class: type '{class_name}' not found in {rel_path}",
            line=self.lineno,
        )]


class JavadocPackageDirective(SphinxDirective):
    """Render a package summary table only (no type detail)."""

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    option_spec = {
        "package": directives.unchanged_required,
        "public-only": directives.flag,
    }

    def run(self) -> List[nodes.Node]:
        env = self.state.document.settings.env
        rel_path = self.arguments[0]
        source_dir = Path(env.srcdir)
        xml_path = source_dir / rel_path
        if not xml_path.exists():
            doc_dir = Path(env.doc2path(env.docname)).parent
            xml_path = doc_dir / rel_path
        if not xml_path.exists():
            return [self.state_machine.reporter.error(
                f"javadoc-package: XML file not found: {rel_path}",
                line=self.lineno,
            )]

        env.note_dependency(str(xml_path))
        model = parse_xml(xml_path)
        public_only = "public-only" in self.options
        pkg_name = self.options["package"]

        for pkg in model.packages:
            if pkg.name != pkg_name:
                continue

            sec = _make_section(f"Package {pkg.name}", _anchor_id(pkg.name))
            sec["classes"].append("javadoc-package-section")

            for kind, label in [
                ("interface", "Interfaces"),
                ("class", "Classes"),
                ("enum", "Enums"),
            ]:
                types = [t for t in pkg.types if t.kind == kind]
                if public_only:
                    types = [t for t in types if t.scope == "public"]
                if not types:
                    continue
                kind_sec = _make_section(label, _anchor_id(pkg.name, label.lower()))
                kind_sec["classes"].append("javadoc-kind-group")
                rows = []
                for jt in types:
                    name_p = nodes.paragraph()
                    name_p += nodes.reference(
                        text=jt.name, refid=_anchor_id(jt.qualified),
                        classes=["javadoc-member-link"],
                    )
                    desc = _flat_comment(jt.comment) if jt.comment else ""
                    desc_p = nodes.paragraph(text=desc)
                    rows.append([name_p, desc_p])
                kind_sec += _make_table([_singular(label), "Description"], rows)
                sec += kind_sec
            return [sec]

        return [self.state_machine.reporter.error(
            f"javadoc-package: package '{pkg_name}' not found in {rel_path}",
            line=self.lineno,
        )]
