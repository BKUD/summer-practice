"""
Graphviz pipeline: ClassDiagram -> DOT -> SVG -> enrich data-* attributes.
"""
from __future__ import annotations

import html
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List, Tuple

from .diagram import ClassDiagram
from .enums import AggregationKind


def _q(value: str) -> str:
    """Quote value for DOT ids/strings."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _node_label(cls) -> str:
    """Build Graphviz record label for UML class."""
    title = cls.name
    if getattr(cls, "is_abstract", False):
        title = f"<I>{html.escape(title)}</I>"
    else:
        title = html.escape(title)

    if getattr(cls, "stereotype", None):
        st = html.escape(cls.stereotype.value)
        title = f"&laquo;{st}&raquo;<BR/>{title}"

    attrs = "<BR ALIGN=\"LEFT\"/>".join(
        html.escape(a.to_text()) for a in getattr(cls, "attributes", [])
    ) or " "
    ops = "<BR ALIGN=\"LEFT\"/>".join(
        html.escape(o.to_text()) for o in getattr(cls, "operations", [])
    ) or " "
    return f"<{title}<BR/>{attrs}<BR/>{ops}>"


def diagram_to_dot(diagram: ClassDiagram) -> Tuple[str, Dict[str, str]]:
    """Render diagram to DOT and return node-id -> class-name map."""
    node_map: Dict[str, str] = {}
    name_to_node: Dict[str, str] = {}

    lines: List[str] = [
        "digraph UML {",
        "  graph [rankdir=LR, splines=ortho, nodesep=0.8, ranksep=1.0, pad=0.3];",
        "  node [shape=box, fontsize=10, fontname=\"Arial\"];",
        "  edge [fontsize=9, fontname=\"Arial\"];",
    ]

    for idx, (name, cls) in enumerate(diagram.classifiers.items()):
        node_id = f"C{idx}"
        node_map[node_id] = name
        name_to_node[name] = node_id
        label = _node_label(cls)
        lines.append(f"  {node_id} [label={_q(label)} shape=plaintext];")

    for assoc in diagram.associations:
        if not assoc.is_binary():
            continue
        src = assoc.ends[0].participant.name
        tgt = assoc.ends[1].participant.name
        if src not in name_to_node or tgt not in name_to_node:
            continue
        src_id = name_to_node[src]
        tgt_id = name_to_node[tgt]
        attrs = ["arrowhead=none", "color=black"]
        if assoc.name:
            attrs.append(f"label={_q(assoc.name)}")
        if assoc.ends[0].aggregation == AggregationKind.AGGREGATION:
            attrs += ["dir=both", "arrowtail=odiamond"]
        elif assoc.ends[0].aggregation == AggregationKind.COMPOSITION:
            attrs += ["dir=both", "arrowtail=diamond"]
        lines.append(f"  {src_id} -> {tgt_id} [{', '.join(attrs)}];")

    for gen in diagram.generalizations:
        src = gen.specific.name
        tgt = gen.general.name
        if src in name_to_node and tgt in name_to_node:
            lines.append(
                f"  {name_to_node[src]} -> {name_to_node[tgt]} "
                "[arrowhead=empty, style=solid];"
            )

    for dep in diagram.dependencies:
        src = dep.client.name
        tgt = dep.supplier.name
        if src in name_to_node and tgt in name_to_node:
            label = dep.stereotype.value if dep.stereotype else ""
            attrs = ["arrowhead=vee", "style=dashed"]
            if label:
                attrs.append(f"label={_q(f'<<{label}>>')}")
            lines.append(f"  {name_to_node[src]} -> {name_to_node[tgt]} [{', '.join(attrs)}];")

    for real in diagram.realizations:
        src = real.implementer.name
        tgt = real.interface_.name
        if src in name_to_node and tgt in name_to_node:
            lines.append(
                f"  {name_to_node[src]} -> {name_to_node[tgt]} "
                "[arrowhead=empty, style=dashed];"
            )

    lines.append("}")
    return "\n".join(lines), node_map


def _run_dot_to_svg(dot_text: str) -> str:
    """Call Graphviz dot and return SVG text."""
    try:
        result = subprocess.run(
            ["dot", "-Tsvg"],
            input=dot_text.encode("utf-8"),
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Graphviz 'dot' не найден. Установите Graphviz и добавьте dot в PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Ошибка Graphviz dot: {stderr}") from exc
    return result.stdout.decode("utf-8", errors="replace")


def enrich_svg_with_data_attrs(
    svg_text: str,
    diagram: ClassDiagram,
    node_map: Dict[str, str],
) -> str:
    """Add data-* attributes to Graphviz-generated SVG."""
    root = ET.fromstring(svg_text)

    rel_queues: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)

    for assoc in diagram.associations:
        if not assoc.is_binary():
            continue
        src = assoc.ends[0].participant.name
        tgt = assoc.ends[1].participant.name
        rel_queues[(src, tgt)].append(
            {
                "data-type": "association",
                "data-src": src,
                "data-tgt": tgt,
                "data-name": assoc.name or "",
                "data-derived": str(assoc.is_derived).lower(),
            }
        )
    for gen in diagram.generalizations:
        src = gen.specific.name
        tgt = gen.general.name
        rel_queues[(src, tgt)].append(
            {
                "data-type": "generalization",
                "data-src": src,
                "data-tgt": tgt,
                "data-substitutable": str(gen.is_substitutable).lower(),
            }
        )
    for dep in diagram.dependencies:
        src = dep.client.name
        tgt = dep.supplier.name
        attrs = {
            "data-type": "dependency",
            "data-src": src,
            "data-tgt": tgt,
        }
        if dep.stereotype:
            attrs["data-stereotype"] = dep.stereotype.value
        rel_queues[(src, tgt)].append(attrs)
    for real in diagram.realizations:
        src = real.implementer.name
        tgt = real.interface_.name
        rel_queues[(src, tgt)].append(
            {
                "data-type": "realization",
                "data-src": src,
                "data-tgt": tgt,
            }
        )

    for g in root.iter():
        if not g.tag.endswith("g"):
            continue
        cls_attr = (g.get("class") or "").split()
        if "node" in cls_attr:
            title_el = next((c for c in list(g) if c.tag.endswith("title")), None)
            if title_el is None or not title_el.text:
                continue
            node_id = title_el.text.strip()
            class_name = node_map.get(node_id)
            if not class_name:
                continue
            uml_cls = diagram.classifiers[class_name]
            g.set("class", "uml-class")
            g.set("data-id", class_name)
            g.set("data-name", class_name)
            g.set("data-type", "class")
            g.set("data-stereotype", uml_cls.stereotype.value if uml_cls.stereotype else "")
            g.set("data-abstract", str(uml_cls.is_abstract).lower())
            g.set("data-attributes-count", str(len(uml_cls.attributes)))
            g.set("data-operations-count", str(len(uml_cls.operations)))

        elif "edge" in cls_attr:
            title_el = next((c for c in list(g) if c.tag.endswith("title")), None)
            if title_el is None or not title_el.text or "->" not in title_el.text:
                continue
            src_id, tgt_id = [x.strip() for x in title_el.text.split("->", 1)]
            src_name = node_map.get(src_id)
            tgt_name = node_map.get(tgt_id)
            if not src_name or not tgt_name:
                continue
            q = rel_queues.get((src_name, tgt_name))
            if not q:
                continue
            rel_attrs = q.pop(0)
            g.set("class", "uml-edge")
            for k, v in rel_attrs.items():
                g.set(k, v)

    return ET.tostring(root, encoding="unicode")


def diagram_to_graphviz_svg(diagram: ClassDiagram) -> str:
    """Full Graphviz rendering pipeline."""
    dot_text, node_map = diagram_to_dot(diagram)
    raw_svg = _run_dot_to_svg(dot_text)
    return enrich_svg_with_data_attrs(raw_svg, diagram, node_map)
