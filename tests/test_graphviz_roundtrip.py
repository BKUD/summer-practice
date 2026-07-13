from uml_dsl.graphviz_render import diagram_to_graphviz_svg
from uml_dsl.svg_parser import parse_svg_to_diagram
from uml_dsl.tdl_build import build_diagram
from uml_dsl.tdl_lexer import lex
from uml_dsl.tdl_parser import parse_tdl
from uml_dsl.tdl_serializer import diagram_to_tdl
from pathlib import Path
import xml.etree.ElementTree as ET


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

    restored_tdl = diagram_to_tdl(restored)
    rebuilt = build_diagram(parse_tdl(lex(restored_tdl)))

    rebuilt_class = rebuilt.classifiers["Робот"]

    assert len(rebuilt_class.attributes) == 2
    assert len(rebuilt_class.operations) == 1
    assert rebuilt_class.attributes[0].name == "имя"
    assert rebuilt_class.attributes[0].type_ == "String"
    assert rebuilt_class.operations[0].name == "двигаться"

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
    restored_tdl = diagram_to_tdl(restored)
    rebuilt = build_diagram(parse_tdl(lex(restored_tdl)))

    assert len(rebuilt.associations) == 1
    rebuilt_assoc = rebuilt.associations[0]

    assert rebuilt_assoc.name == "содержит"
    assert rebuilt_assoc.ends[0].role == "контейнер"
    assert rebuilt_assoc.ends[1].role == "элементы"

def test_missing_multiplicity_is_not_converted_to_many():
    source = """
КЛАСС Пример
  АТРИБУТЫ
    + значение : int
КОНЕЦ КЛАСС
"""

    diagram = build_diagram(parse_tdl(lex(source)))
    attribute = diagram.classifiers["Пример"].attributes[0]

    assert attribute.multiplicity is None

    svg = diagram_to_graphviz_svg(diagram)

    assert "[0..*]" not in svg

def _association_signature(association):
    return (
        association.name,
        association.is_derived,
        tuple(
            (
                end.participant.name,
                end.role,
                (
                    str(end.multiplicity)
                    if end.multiplicity is not None
                    else None
                ),
                end.aggregation.value,
                end.navigable,
            )
            for end in association.ends
        ),
    )


def test_robot_biologist_full_roundtrip(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    source_path = (
        project_root
        / "examples"
        / "robot_biologist.tdl"
    )

    source_tdl = source_path.read_text(encoding="utf-8")

    # TDL → Pydantic
    original = build_diagram(
        parse_tdl(lex(source_tdl))
    )

    # Pydantic → Graphviz SVG
    svg = diagram_to_graphviz_svg(original)
    (tmp_path / "robot_biologist.svg").write_text(
        svg,
        encoding="utf-8",
    )

    # SVG → Pydantic
    parse_result = parse_svg_to_diagram(svg)

    assert parse_result.success, parse_result.errors
    assert parse_result.diagram is not None
    assert not parse_result.errors

    restored_from_svg = parse_result.diagram

    assert (
            restored_from_svg.layout_commands
            == original.layout_commands
    )

    # Pydantic → TDL
    restored_tdl = diagram_to_tdl(restored_from_svg)
    (tmp_path / "robot_biologist_restored.tdl").write_text(
        restored_tdl,
        encoding="utf-8",
    )

    assert "РАЗМЕЩЕНИЕ" in restored_tdl
    assert (
            "РАСПРЕДЕЛИТЬ ПО ГОРИЗОНТАЛИ "
            "РоботБиолог ЛабиринтРоботБиолог "
            "ЯчейкаРоботБиолог ТипЯчеекБио ШАГ 10"
            in restored_tdl
    )
    assert (
            "ПРИВЯЗАТЬ Итератор ЛЕВЕЕ РоботБиолог"
            in restored_tdl
    )
    assert (
            "ПРИВЯЗАТЬ ТипНаправленийБиоНапр "
            "ВЫШЕ Итератор"
            in restored_tdl
    )

    # Восстановленный TDL → Pydantic
    rebuilt = build_diagram(
        parse_tdl(lex(restored_tdl))
    )

    assert rebuilt.layout_commands == original.layout_commands

    # Проверяем классы.
    assert set(rebuilt.classifiers) == set(original.classifiers)

    for class_name in original.classifiers:
        original_class = original.classifiers[class_name]
        rebuilt_class = rebuilt.classifiers[class_name]

        assert (
            rebuilt_class.model_dump(mode="json")
            == original_class.model_dump(mode="json")
        )

    # Проверяем ассоциации, включая кратности и композицию.
    original_associations = sorted(
        _association_signature(association)
        for association in original.associations
    )
    rebuilt_associations = sorted(
        _association_signature(association)
        for association in rebuilt.associations
    )

    assert rebuilt_associations == original_associations

def test_invalid_svg_layout_metadata_is_rejected():
    source = """
КЛАСС Пример
КОНЕЦ КЛАСС
"""

    diagram = build_diagram(parse_tdl(lex(source)))
    svg = diagram_to_graphviz_svg(diagram)

    root = ET.fromstring(svg)
    root.set("data-layout", "{broken json}")

    broken_svg = ET.tostring(
        root,
        encoding="unicode",
    )

    result = parse_svg_to_diagram(broken_svg)

    assert not result.success
    assert any(
        "data-layout" in str(error)
        for error in result.errors
    ), result.errors

    assert not result.success
    assert result.diagram is not None
    assert any(
        "data-layout" in str(error)
        for error in result.errors
    ), result.errors