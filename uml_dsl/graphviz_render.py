"""
Graphviz pipeline: ClassDiagram -> DOT -> SVG -> enrich data-* attributes.
"""
from __future__ import annotations

import html
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List, Tuple
import json

from .diagram import ClassDiagram
from .enums import AggregationKind


def _q(value: str) -> str:
    """Quote value for DOT ids/strings."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _node_label(cls) -> str:
    """Создаёт HTML-подобную UML-метку для Graphviz."""

    class_name = html.escape(cls.name)

    if getattr(cls, "is_abstract", False):
        class_name = f"<I>{class_name}</I>"

    class_name = f"<B>{class_name}</B>"

    if getattr(cls, "stereotype", None):
        stereotype = html.escape(cls.stereotype.value)
        title = f"&laquo;{stereotype}&raquo;<BR/>{class_name}"
    else:
        title = class_name

    attributes = "<BR ALIGN=\"LEFT\"/>".join(
        html.escape(attribute.to_text())
        for attribute in getattr(cls, "attributes", [])
    )

    operations = "<BR ALIGN=\"LEFT\"/>".join(
        html.escape(operation.to_text())
        for operation in getattr(cls, "operations", [])
    )

    if not attributes:
        attributes = "&#160;"

    if not operations:
        operations = "&#160;"

    return (
        "<"
        '<TABLE BORDER="1" CELLBORDER="0" '
        'CELLSPACING="0" CELLPADDING="5">'
        f"<TR><TD>{title}</TD></TR>"
        "<HR/>"
        f'<TR><TD ALIGN="LEFT">{attributes}</TD></TR>'
        "<HR/>"
        f'<TR><TD ALIGN="LEFT">{operations}</TD></TR>'
        "</TABLE>"
        ">"
    )

def _requires_tb_rankdir(diagram: ClassDiagram) -> bool:
    return any(
        (
            command.get("kind") == "distribute"
            and command.get("axis") == "ГОРИЗОНТАЛИ"
        )
        or command.get("kind") == "bind"
        for command in diagram.layout_commands
    )


def _layout_to_dot(
    diagram: ClassDiagram,
    name_to_node: Dict[str, str],
) -> List[str]:
    """Преобразует команды размещения TDL в ограничения DOT."""

    lines: List[str] = []

    for command_index, command in enumerate(diagram.layout_commands):
        if command.get("kind") != "distribute":
            continue

        if command.get("axis") != "ГОРИЗОНТАЛИ":
            continue

        node_ids = [
            name_to_node[name]
            for name in command.get("elements", [])
            if name in name_to_node
        ]

        if len(node_ids) < 2:
            continue

        lines.append(f"  subgraph layout_horizontal_{command_index} {{")
        lines.append("    rank=same;")
        lines.append("    " + "; ".join(node_ids) + ";")
        lines.append("  }")

        for edge_index, (left, right) in enumerate(
            zip(node_ids, node_ids[1:])
        ):
            lines.append(
                f"  {left} -> {right} "
                "[style=invis, weight=100, constraint=true, "
                f'id="layout-edge-{command_index}-{edge_index}", '
                'class="layout-edge"];'
            )

    for command_index, command in enumerate(diagram.layout_commands):
        if command.get("kind") != "bind":
            continue

        elem1 = command.get("elem1")
        elem2 = command.get("elem2")
        direction = command.get("direction")

        if elem1 not in name_to_node or elem2 not in name_to_node:
            continue

        node1 = name_to_node[elem1]
        node2 = name_to_node[elem2]

        if direction in ("ЛЕВЕЕ", "ПРАВЕЕ"):
            left, right = (
                (node1, node2)
                if direction == "ЛЕВЕЕ"
                else (node2, node1)
            )

            lines.append(f"  subgraph layout_bind_{command_index} {{")
            lines.append("    rank=same;")
            lines.append(f"    {left}; {right};")
            lines.append("  }")

            lines.append(
                f"  {left} -> {right} "
                "[style=invis, weight=200, constraint=true, "
                f'id="layout-bind-{command_index}", '
                'class="layout-edge"];'
            )

        elif direction in ("ВЫШЕ", "НИЖЕ"):
            top, bottom = (
                (node1, node2)
                if direction == "ВЫШЕ"
                else (node2, node1)
            )

            lines.append(
                f"  {top} -> {bottom} "
                "[style=invis, weight=200, constraint=true, minlen=1, "
                f'id="layout-bind-{command_index}", '
                'class="layout-edge"];'
            )

    return lines

def _association_end_label(end) -> str:
    """Формирует подпись полюса: роль и кратность."""

    parts: List[str] = []

    if end.role:
        parts.append(end.role)

    if end.multiplicity is not None:
        parts.append(str(end.multiplicity))

    return " ".join(parts)

def diagram_to_dot(diagram: ClassDiagram) -> Tuple[str, Dict[str, str]]:
    """Render diagram to DOT and return node-id -> class-name map."""
    node_map: Dict[str, str] = {}
    name_to_node: Dict[str, str] = {}

    rankdir = "TB" if _requires_tb_rankdir(diagram) else "LR"

    lines: List[str] = [
        "digraph UML {",
        (
            f"  graph [rankdir={rankdir}, splines=polyline, "
            "nodesep=1.0, ranksep=1.0, pad=0.3, "
            "forcelabels=true, outputorder=edgesfirst];"
        ),
        '  node [shape=plain, fontsize=10, fontname="Arial"];',
        "  edge [fontsize=9, fontname=\"Arial\"];",
    ]

    for idx, (name, cls) in enumerate(diagram.classifiers.items()):
        node_id = f"C{idx}"
        node_map[node_id] = name
        name_to_node[name] = node_id
        label = _node_label(cls)
        lines.append(
            f"  {node_id} [shape=plain, label={label}];"
        )

    lines.extend(_layout_to_dot(diagram, name_to_node))

    for assoc in diagram.associations:
        src_end = assoc.ends[0]
        tgt_end = assoc.ends[1]

        src = src_end.participant.name
        tgt = tgt_end.participant.name

        if src not in name_to_node or tgt not in name_to_node:
            continue

        src_id = name_to_node[src]
        tgt_id = name_to_node[tgt]

        attrs = [
            "arrowhead=none",
            "color=black",
            "penwidth=1.0",
            "fontsize=9",
            'fontname="Arial"',
            "labelfloat=true",
            "labeldistance=2.0",
            "labelangle=25",
        ]

        if assoc.name:
            attrs.append(f"label={_q(assoc.name)}")

        src_label = _association_end_label(src_end)
        tgt_label = _association_end_label(tgt_end)

        if src_label:
            attrs.append(f"taillabel={_q(src_label)}")

        if tgt_label:
            attrs.append(f"headlabel={_q(tgt_label)}")

        if src_end.aggregation == AggregationKind.AGGREGATION:
            attrs.extend(["dir=both", "arrowtail=odiamond"])
        elif src_end.aggregation == AggregationKind.COMPOSITION:
            attrs.extend(["dir=both", "arrowtail=diamond"])

        lines.append(
            f"  {src_id} -> {tgt_id} [{', '.join(attrs)}];"
        )

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
        if len(assoc.ends) < 2:
            continue

        src_end = assoc.ends[0]
        tgt_end = assoc.ends[1]

        src = src_end.participant.name
        tgt = tgt_end.participant.name

        assoc_attrs = {
            "data-type": "association",
            "data-src": src,
            "data-tgt": tgt,
            "data-name": assoc.name or "",
            "data-derived": str(assoc.is_derived).lower(),
            "data-src-aggregation": src_end.aggregation.value,
            "data-tgt-aggregation": tgt_end.aggregation.value,
        }

        if src_end.role is not None:
            assoc_attrs["data-src-role"] = src_end.role

        if tgt_end.role is not None:
            assoc_attrs["data-tgt-role"] = tgt_end.role

        if src_end.multiplicity is not None:
            assoc_attrs["data-src-multiplicity"] = str(
                src_end.multiplicity
            )

        if tgt_end.multiplicity is not None:
            assoc_attrs["data-tgt-multiplicity"] = str(
                tgt_end.multiplicity
            )

        if src_end.navigable is not None:
            assoc_attrs["data-src-navigable"] = str(
                src_end.navigable
            ).lower()

        if tgt_end.navigable is not None:
            assoc_attrs["data-tgt-navigable"] = str(
                tgt_end.navigable
            ).lower()

        rel_queues[(src, tgt)].append(assoc_attrs)

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
            g.set("data-model",
                json.dumps(
                    uml_cls.model_dump(mode="json"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

        elif "edge" in cls_attr:
            if (
                    "layout-edge" in cls_attr
                    or (g.get("id") or "").startswith("layout-edge-")
            ):
                continue

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
