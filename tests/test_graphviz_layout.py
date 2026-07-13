from uml_dsl.graphviz_render import diagram_to_dot
from uml_dsl.tdl_build import build_diagram
from uml_dsl.tdl_lexer import lex
from uml_dsl.tdl_parser import parse_tdl


TDL_SOURCE = """
КЛАСС A
КОНЕЦ КЛАСС

КЛАСС B
КОНЕЦ КЛАСС

КЛАСС C
КОНЕЦ КЛАСС

РАЗМЕЩЕНИЕ
  РАСПРЕДЕЛИТЬ ПО ГОРИЗОНТАЛИ A B C ШАГ 10
КОНЕЦ РАЗМЕЩЕНИЕ
"""


def test_horizontal_distribution_is_translated_to_dot():
    diagram = build_diagram(parse_tdl(lex(TDL_SOURCE)))

    assert len(diagram.layout_commands) == 1
    assert diagram.layout_commands[0]["axis"] == "ГОРИЗОНТАЛИ"

    dot, node_map = diagram_to_dot(diagram)
    name_to_node = {
        class_name: node_id
        for node_id, class_name in node_map.items()
    }

    node_a = name_to_node["A"]
    node_b = name_to_node["B"]
    node_c = name_to_node["C"]

    assert "rankdir=TB" in dot
    assert "rank=same" in dot
    assert f"{node_a}; {node_b}; {node_c};" in dot
    assert f"{node_a} -> {node_b}" in dot
    assert f"{node_b} -> {node_c}" in dot
    assert 'class="layout-edge"' in dot

BIND_TDL_SOURCE = """
КЛАСС A
КОНЕЦ КЛАСС

КЛАСС B
КОНЕЦ КЛАСС

КЛАСС C
КОНЕЦ КЛАСС

РАЗМЕЩЕНИЕ
  ПРИВЯЗАТЬ A ЛЕВЕЕ B
  ПРИВЯЗАТЬ C ВЫШЕ A
КОНЕЦ РАЗМЕЩЕНИЕ
"""


def test_bind_commands_are_translated_to_dot():
    diagram = build_diagram(parse_tdl(lex(BIND_TDL_SOURCE)))

    dot, node_map = diagram_to_dot(diagram)
    name_to_node = {
        class_name: node_id
        for node_id, class_name in node_map.items()
    }

    node_a = name_to_node["A"]
    node_b = name_to_node["B"]
    node_c = name_to_node["C"]

    assert "rankdir=TB" in dot

    # A находится левее B.
    assert f"{node_a}; {node_b};" in dot
    assert f"{node_a} -> {node_b}" in dot

    # C находится выше A.
    assert f"{node_c} -> {node_a}" in dot

    assert dot.count('class="layout-edge"') == 2

def test_class_uses_graphviz_html_label():
    diagram = build_diagram(parse_tdl(lex("""
КЛАСС Пример
  АТРИБУТЫ
    + значение : int
  ОПЕРАЦИИ
    + получить() : int
КОНЕЦ КЛАСС
""")))

    dot, _ = diagram_to_dot(diagram)

    assert "label=<<TABLE" in dot
    assert 'label="<TABLE' not in dot
    assert "<HR/>" in dot
    assert "значение" in dot
    assert "получить" in dot