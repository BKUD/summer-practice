import pytest

from uml_dsl.enums import AggregationKind
from uml_dsl.graphviz_render import (
    diagram_to_dot,
    diagram_to_graphviz_svg,
)
from uml_dsl.svg_parser import parse_svg_to_diagram
from uml_dsl.tdl_build import build_diagram
from uml_dsl.tdl_lexer import lex
from uml_dsl.tdl_parser import parse_tdl
from uml_dsl.tdl_serializer import diagram_to_tdl


@pytest.mark.parametrize(
    ("keyword", "expected_kind", "expected_arrow"),
    [
        (
            "АГРЕГАЦИЯ",
            AggregationKind.AGGREGATION,
            "arrowtail=odiamond",
        ),
        (
            "КОМПОЗИЦИЯ",
            AggregationKind.COMPOSITION,
            "arrowtail=diamond",
        ),
    ],
)
def test_aggregation_roundtrip(
    keyword,
    expected_kind,
    expected_arrow,
):
    source = f"""
КЛАСС Целое
КОНЕЦ КЛАСС

КЛАСС Часть
КОНЕЦ КЛАСС

АССОЦИАЦИЯ
  Целое 1 : контейнер {keyword}
  --
  Часть [0..*] : элементы
  ИМЯ "содержит"
"""

    original = build_diagram(parse_tdl(lex(source)))

    assert len(original.associations) == 1
    assert original.associations[0].ends[0].aggregation == expected_kind

    dot, _ = diagram_to_dot(original)

    assert expected_arrow in dot
    assert "dir=both" in dot

    svg = diagram_to_graphviz_svg(original)
    parse_result = parse_svg_to_diagram(svg)

    assert parse_result.success, parse_result.errors
    assert parse_result.diagram is not None

    restored = parse_result.diagram
    restored_end = restored.associations[0].ends[0]

    assert restored_end.aggregation == expected_kind

    restored_tdl = diagram_to_tdl(restored)

    assert keyword in restored_tdl

    rebuilt = build_diagram(parse_tdl(lex(restored_tdl)))

    assert (
        rebuilt.associations[0].ends[0].aggregation
        == expected_kind
    )