from uml_dsl.graphviz_render import diagram_to_graphviz_svg
from uml_dsl.svg_parser import parse_svg_to_diagram
from uml_dsl.tdl_build import build_diagram
from uml_dsl.tdl_lexer import lex
from uml_dsl.tdl_parser import parse_tdl


TDL_SOURCE = """
КЛАСС Робот
  АТРИБУТЫ
    - имя : Строка
    + скорость : цел

  ОПЕРАЦИИ
    + двигаться(направление) : цел
КОНЕЦ КЛАСС
"""


def test_graphviz_roundtrip_preserves_class_members():
    original = build_diagram(parse_tdl(lex(TDL_SOURCE)))

    svg = diagram_to_graphviz_svg(original)
    result = parse_svg_to_diagram(svg)

    assert result.success, result.errors
    assert result.diagram is not None

    restored = result.diagram

    assert set(restored.classifiers) == set(original.classifiers)

    original_class = original.classifiers["Робот"]
    restored_class = restored.classifiers["Робот"]

    assert len(restored_class.attributes) == len(original_class.attributes)
    assert len(restored_class.operations) == len(original_class.operations)

    assert restored_class.attributes[0].name == "имя"
    assert restored_class.attributes[0].type_ == "String"

    assert restored_class.operations[0].name == "двигаться"
    assert restored_class.operations[0].return_type == "int"