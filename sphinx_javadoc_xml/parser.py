"""
Parser for the XML doclet format.

Converts XML into a structured Python data model supporting:
- Classes, interfaces, enums
- Type parameters with bounds (<T extends Foo>)
- Bounded wildcards (? extends / ? super)
- Exception declarations (throws)
- Enum constant comments, tags, annotations
- Deeply nested generic types
"""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class TypeInfo:
    """A Java type reference, possibly with generics."""

    qualified: str
    generics: List[TypeInfo] = field(default_factory=list)
    wildcard: bool = False
    extends_bound: Optional[TypeInfo] = None  # ? extends X
    super_bound: Optional[TypeInfo] = None  # ? super X
    dimension: int = 0  # array dimension

    @property
    def simple_name(self) -> str:
        base = self.qualified.split("<")[0]
        parts = base.rsplit(".", 1)
        return parts[-1] if len(parts) > 1 else parts[0]

    @property
    def base_qualified(self) -> str:
        """Qualified name without inline generics."""
        return self.qualified.split("<")[0]

    def display(self, short: bool = False, strip_pkg: str = "") -> str:
        if self.wildcard:
            result = "?"
            if self.extends_bound:
                result += f" extends {self.extends_bound.display(short=short, strip_pkg=strip_pkg)}"
            elif self.super_bound:
                result += f" super {self.super_bound.display(short=short, strip_pkg=strip_pkg)}"
            return result

        if short:
            base = self.simple_name
        elif strip_pkg:
            raw = self.base_qualified
            prefix = strip_pkg + "."
            base = raw[len(prefix):] if raw.startswith(prefix) else raw
        else:
            base = self.base_qualified

        if self.generics:
            generic_str = ", ".join(
                g.display(short=short, strip_pkg=strip_pkg) for g in self.generics
            )
            base = f"{base}<{generic_str}>"
        if self.dimension:
            base += "[]" * self.dimension
        return base


@dataclass
class TypeParamInfo:
    """A type parameter declaration, e.g. <T extends Expression>."""

    name: str
    bounds: List[str] = field(default_factory=list)

    def display(self, simplify=None) -> str:
        """Display the type parameter, optionally simplifying bound names.

        Parameters
        ----------
        simplify : callable, optional
            A function that takes a qualified name and returns a display name.
        """
        if self.bounds:
            if simplify:
                bound_strs = [simplify(b) for b in self.bounds]
            else:
                bound_strs = self.bounds
            return f"{self.name} extends {' & '.join(bound_strs)}"
        return self.name


@dataclass
class AnnotationArg:
    name: str
    values: List[str] = field(default_factory=list)


@dataclass
class AnnotationInfo:
    name: str
    qualified: str
    arguments: List[AnnotationArg] = field(default_factory=list)


@dataclass
class ParameterInfo:
    name: str
    type: TypeInfo = field(default_factory=lambda: TypeInfo(qualified="void"))


@dataclass
class TagInfo:
    name: str
    text: str = ""


@dataclass
class MethodInfo:
    name: str
    signature: str = ""
    qualified: str = ""
    scope: str = "public"
    return_type: TypeInfo = field(default_factory=lambda: TypeInfo(qualified="void"))
    parameters: List[ParameterInfo] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)
    annotations: List[AnnotationInfo] = field(default_factory=list)
    comment: str = ""
    tags: List[TagInfo] = field(default_factory=list)
    abstract: bool = False
    final: bool = False
    static: bool = False
    synchronized: bool = False
    native: bool = False
    var_args: bool = False
    default: bool = False  # interface default method

    @property
    def modifiers(self) -> str:
        parts = []
        if self.scope:
            parts.append(self.scope)
        if self.static:
            parts.append("static")
        if self.abstract:
            parts.append("abstract")
        if self.default:
            parts.append("default")
        if self.final:
            parts.append("final")
        if self.synchronized:
            parts.append("synchronized")
        if self.native:
            parts.append("native")
        return " ".join(parts)

    @property
    def anchor_key(self) -> str:
        """Unique key for disambiguating overloaded methods."""
        ptypes = ",".join(p.type.base_qualified for p in self.parameters)
        return f"{self.name}({ptypes})"


@dataclass
class FieldInfo:
    name: str
    qualified: str = ""
    scope: str = "public"
    type: TypeInfo = field(default_factory=lambda: TypeInfo(qualified="void"))
    constant_value: Optional[str] = None
    volatile: bool = False
    transient: bool = False
    static: bool = False
    final: bool = False
    comment: str = ""
    tags: List[TagInfo] = field(default_factory=list)
    annotations: List[AnnotationInfo] = field(default_factory=list)

    @property
    def modifiers(self) -> str:
        parts = []
        if self.scope:
            parts.append(self.scope)
        if self.static:
            parts.append("static")
        if self.final:
            parts.append("final")
        if self.volatile:
            parts.append("volatile")
        if self.transient:
            parts.append("transient")
        return " ".join(parts)


@dataclass
class ConstructorInfo:
    name: str
    signature: str = ""
    scope: str = "public"
    parameters: List[ParameterInfo] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)
    annotations: List[AnnotationInfo] = field(default_factory=list)
    comment: str = ""
    tags: List[TagInfo] = field(default_factory=list)


@dataclass
class EnumConstant:
    name: str
    comment: str = ""
    tags: List[TagInfo] = field(default_factory=list)
    annotations: List[AnnotationInfo] = field(default_factory=list)


@dataclass
class JavaType:
    """Represents a class, interface, or enum."""

    kind: str  # 'class', 'interface', 'enum'
    name: str
    qualified: str
    scope: str = "public"
    comment: str = ""
    tags: List[TagInfo] = field(default_factory=list)
    type_params: List[TypeParamInfo] = field(default_factory=list)
    superclass: Optional[TypeInfo] = None
    interfaces: List[TypeInfo] = field(default_factory=list)
    constructors: List[ConstructorInfo] = field(default_factory=list)
    methods: List[MethodInfo] = field(default_factory=list)
    fields: List[FieldInfo] = field(default_factory=list)
    enum_constants: List[EnumConstant] = field(default_factory=list)
    annotations: List[AnnotationInfo] = field(default_factory=list)
    abstract: bool = False
    serializable: bool = False
    error: bool = False
    exception: bool = False


@dataclass
class PackageInfo:
    name: str
    types: List[JavaType] = field(default_factory=list)
    comment: str = ""


@dataclass
class ApiModel:
    packages: List[PackageInfo] = field(default_factory=list)

    def all_qualified_names(self) -> Set[str]:
        """Return a set of all qualified type names defined in this model."""
        names: Set[str] = set()
        for pkg in self.packages:
            for jt in pkg.types:
                names.add(jt.qualified)
        return names

    def build_reverse_index(self) -> Dict[str, Dict[str, List[str]]]:
        """Build a reverse type hierarchy index.

        Returns a dict mapping qualified type name to:
          {"subclasses": [...], "implementors": [...]}
        """
        index: Dict[str, Dict[str, List[str]]] = {}
        for pkg in self.packages:
            for jt in pkg.types:
                # Superclass → subclass
                if jt.superclass:
                    parent = jt.superclass.base_qualified
                    if parent not in ("java.lang.Object", "java.lang.Enum"):
                        index.setdefault(parent, {"subclasses": [], "implementors": []})
                        index[parent]["subclasses"].append(jt.qualified)
                # Interfaces → implementor
                for iface in jt.interfaces:
                    parent = iface.base_qualified
                    index.setdefault(parent, {"subclasses": [], "implementors": []})
                    index[parent]["implementors"].append(jt.qualified)
        return index


# ---------------------------------------------------------------------------
# XML Parsing
# ---------------------------------------------------------------------------


def _parse_type(elem: ET.Element) -> TypeInfo:
    qualified = html.unescape(elem.get("qualified", "void"))
    dimension = int(elem.get("dimension", "0"))
    generics = []
    extends_bound = None
    super_bound = None

    for child in elem:
        if child.tag == "generic":
            generics.append(_parse_type(child))
        elif child.tag == "wildcard":
            # Bounds are nested inside <wildcard>:
            #   <generic qualified="? extends X">
            #     <wildcard>
            #       <extendsBound qualified="X"/>
            #     </wildcard>
            #   </generic>
            for wc_child in child:
                if wc_child.tag == "extendsBound":
                    extends_bound = _parse_type(wc_child)
                elif wc_child.tag == "superBound":
                    super_bound = _parse_type(wc_child)
        elif child.tag == "extendsBound":
            # Fallback: some doclets may place bounds as siblings
            extends_bound = _parse_type(child)
        elif child.tag == "superBound":
            super_bound = _parse_type(child)

    wildcard = elem.find("wildcard") is not None

    return TypeInfo(
        qualified=qualified,
        generics=generics,
        wildcard=wildcard,
        extends_bound=extends_bound,
        super_bound=super_bound,
        dimension=dimension,
    )


def _parse_annotation(elem: ET.Element) -> AnnotationInfo:
    ann = AnnotationInfo(
        name=elem.get("name", ""),
        qualified=elem.get("qualified", ""),
    )
    for arg_elem in elem.findall("argument"):
        arg = AnnotationArg(name=arg_elem.get("name", ""))
        for val_elem in arg_elem.findall("value"):
            arg.values.append(val_elem.text or "")
        ann.arguments.append(arg)
    return ann


def _parse_parameter(elem: ET.Element) -> ParameterInfo:
    p = ParameterInfo(name=elem.get("name", ""))
    type_elem = elem.find("type")
    if type_elem is not None:
        p.type = _parse_type(type_elem)
    return p


def _parse_tags(elem: ET.Element) -> List[TagInfo]:
    tags = []
    for tag_elem in elem.findall("tag"):
        tags.append(TagInfo(
            name=tag_elem.get("name", ""),
            text=tag_elem.get("text", ""),
        ))
    return tags


def _parse_exceptions(elem: ET.Element) -> List[str]:
    return [e.get("qualified", "") for e in elem.findall("exception")]


def _parse_method(elem: ET.Element) -> MethodInfo:
    m = MethodInfo(
        name=elem.get("name", ""),
        signature=elem.get("signature", ""),
        qualified=elem.get("qualified", ""),
        scope=elem.get("scope", ""),
        abstract=elem.get("abstract") == "true",
        final=elem.get("final") == "true",
        static=elem.get("static") == "true",
        synchronized=elem.get("synchronized") == "true",
        native=elem.get("native") == "true",
        var_args=elem.get("varArgs") == "true",
    )
    for p_elem in elem.findall("parameter"):
        m.parameters.append(_parse_parameter(p_elem))
    ret = elem.find("return")
    if ret is not None:
        m.return_type = _parse_type(ret)
    for ann_elem in elem.findall("annotation"):
        m.annotations.append(_parse_annotation(ann_elem))
    comment_elem = elem.find("comment")
    if comment_elem is not None and comment_elem.text:
        m.comment = comment_elem.text.strip()
    m.tags = _parse_tags(elem)
    m.exceptions = _parse_exceptions(elem)
    return m


def _parse_constructor(elem: ET.Element) -> ConstructorInfo:
    c = ConstructorInfo(
        name=elem.get("name", ""),
        signature=elem.get("signature", ""),
        scope=elem.get("scope", ""),
    )
    for p_elem in elem.findall("parameter"):
        c.parameters.append(_parse_parameter(p_elem))
    for ann_elem in elem.findall("annotation"):
        c.annotations.append(_parse_annotation(ann_elem))
    comment_elem = elem.find("comment")
    if comment_elem is not None and comment_elem.text:
        c.comment = comment_elem.text.strip()
    c.tags = _parse_tags(elem)
    c.exceptions = _parse_exceptions(elem)
    return c


def _parse_field(elem: ET.Element) -> FieldInfo:
    f = FieldInfo(
        name=elem.get("name", ""),
        qualified=elem.get("qualified", ""),
        scope=elem.get("scope", ""),
        volatile=elem.get("volatile") == "true",
        transient=elem.get("transient") == "true",
        static=elem.get("static") == "true",
        final=elem.get("final") == "true",
    )
    type_elem = elem.find("type")
    if type_elem is not None:
        f.type = _parse_type(type_elem)
    const_elem = elem.find("constant")
    if const_elem is not None and const_elem.text:
        f.constant_value = const_elem.text.strip()
    comment_elem = elem.find("comment")
    if comment_elem is not None and comment_elem.text:
        f.comment = comment_elem.text.strip()
    f.tags = _parse_tags(elem)
    for ann_elem in elem.findall("annotation"):
        f.annotations.append(_parse_annotation(ann_elem))
    return f


def _parse_java_type(elem: ET.Element, kind: str) -> JavaType:
    jt = JavaType(
        kind=kind,
        name=elem.get("name", ""),
        qualified=elem.get("qualified", ""),
        scope=elem.get("scope", "public"),
        abstract=elem.get("abstract") == "true",
        serializable=elem.get("serializable") == "true",
        error=elem.get("error") == "true",
        exception=elem.get("exception") == "true",
    )

    comment_elem = elem.find("comment")
    if comment_elem is not None and comment_elem.text:
        jt.comment = comment_elem.text.strip()

    jt.tags = _parse_tags(elem)

    # Type parameters: <generic name="T"><bound>...</bound></generic>
    for g_elem in elem.findall("generic"):
        name = g_elem.get("name")
        if name:
            bounds = []
            for b in g_elem.findall("bound"):
                if b.text:
                    bounds.append(b.text.strip())
            jt.type_params.append(TypeParamInfo(name=name, bounds=bounds))

    # Superclass: first <class> child
    class_elems = elem.findall("class")
    if class_elems:
        jt.superclass = _parse_type(class_elems[0])

    # Interfaces
    for iface_elem in elem.findall("interface"):
        jt.interfaces.append(_parse_type(iface_elem))

    # Enum constants (with comment, tags, annotations)
    for const_elem in elem.findall("constant"):
        ec = EnumConstant(name=const_elem.get("name", ""))
        ce = const_elem.find("comment")
        if ce is not None and ce.text:
            ec.comment = ce.text.strip()
        ec.tags = _parse_tags(const_elem)
        for ann_elem in const_elem.findall("annotation"):
            ec.annotations.append(_parse_annotation(ann_elem))
        jt.enum_constants.append(ec)

    for ctor_elem in elem.findall("constructor"):
        jt.constructors.append(_parse_constructor(ctor_elem))

    for meth_elem in elem.findall("method"):
        jt.methods.append(_parse_method(meth_elem))

    for field_elem in elem.findall("field"):
        jt.fields.append(_parse_field(field_elem))

    for ann_elem in elem.findall("annotation"):
        jt.annotations.append(_parse_annotation(ann_elem))

    return jt


def parse_xml(source) -> ApiModel:
    """
    Parse a javadoc XML file and return the full API model.

    Parameters
    ----------
    source : str or Path
        Path to the XML file, or an XML string.
    """
    if isinstance(source, Path) or (
        isinstance(source, str) and not source.strip().startswith("<")
    ):
        tree = ET.parse(str(source))
        root = tree.getroot()
    else:
        root = ET.fromstring(source)

    model = ApiModel()

    for pkg_elem in root.findall("package"):
        pkg = PackageInfo(name=pkg_elem.get("name", ""))

        for kind_tag in ("class", "enum", "interface"):
            for type_elem in pkg_elem.findall(kind_tag):
                if type_elem.get("name"):
                    jt = _parse_java_type(type_elem, kind_tag)
                    pkg.types.append(jt)

        model.packages.append(pkg)

    return model
