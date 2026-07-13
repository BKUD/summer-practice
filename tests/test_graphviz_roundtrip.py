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

RELATION_TDL = """
КЛАСС Контейнер
КОНЕЦ КЛАСС

КЛАСС Элемент
КОНЕЦ КЛАСС

АССОЦИАЦИЯ
  Контейнер 1 : контейнер
  --
  Элемент [0..*] : элементы
  ИМЯ "содержит"
"""


def test_graphviz_roundtrip_preserves_association():
    original = build_diagram(parse_tdl(lex(RELATION_TDL)))

    svg = diagram_to_graphviz_svg(original)
    result = parse_svg_to_diagram(svg)

    assert result.success, result.errors
    assert result.diagram is not None

    restored = result.diagram

    assert len(original.associations) == 1
    assert len(restored.associations) == 1

    original_assoc = original.associations[0]
    restored_assoc = restored.associations[0]

    assert restored_assoc.name == original_assoc.name
    assert restored_assoc.is_derived == original_assoc.is_derived
    assert len(restored_assoc.ends) == len(original_assoc.ends)

    for original_end, restored_end in zip(
        original_assoc.ends,
        restored_assoc.ends,
    ):
        assert (
            restored_end.participant.name
            == original_end.participant.name
        )
        assert restored_end.role == original_end.role
        assert restored_end.navigable == original_end.navigable

        assert restored_end.multiplicity is not None
        assert original_end.multiplicity is not None

        assert (
            restored_end.multiplicity.lower
            == original_end.multiplicity.lower
        )
        assert (
            restored_end.multiplicity.upper
            == original_end.multiplicity.upper
        )