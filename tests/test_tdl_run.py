from pathlib import Path

from uml_dsl.tdl_run import (
    main,
    render_tdl_file,
    tdl_to_svg,
)

import xml.etree.ElementTree as ET

SVG_NAMESPACE = "http://www.w3.org/2000/svg"


SIMPLE_TDL = """
КЛАСС Пример
КОНЕЦ КЛАСС
"""


def assert_valid_tdl_svg(svg: str) -> None:
    root = ET.fromstring(svg)

    assert root.tag == f"{{{SVG_NAMESPACE}}}svg"
    assert root.get("data-tdl-schema") == "1"

    class_elements = root.findall(
        './/*[@data-type="class"]'
    )

    assert class_elements

def test_tdl_to_svg_public_api():
    svg = tdl_to_svg(SIMPLE_TDL)

    assert_valid_tdl_svg(svg)
    assert "Пример" in svg

def test_render_tdl_file_creates_parent_directory(
    tmp_path: Path,
):
    input_path = tmp_path / "input.tdl"
    output_path = (
        tmp_path
        / "nested"
        / "output"
        / "diagram.svg"
    )

    input_path.write_text(
        SIMPLE_TDL,
        encoding="utf-8",
    )

    result_path = render_tdl_file(
        input_path=input_path,
        output_path=output_path,
    )

    assert result_path == output_path
    assert output_path.is_file()

    svg = output_path.read_text(encoding="utf-8")

    assert_valid_tdl_svg(svg)

def test_cli_main_writes_svg(tmp_path: Path):
    input_path = tmp_path / "input.tdl"
    output_path = tmp_path / "output" / "diagram.svg"

    input_path.write_text(
        SIMPLE_TDL,
        encoding="utf-8",
    )

    exit_code = main(
        [
            str(input_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert output_path.is_file()


def test_cli_main_returns_error_for_missing_input(
    tmp_path: Path,
):
    missing_path = tmp_path / "missing.tdl"
    output_path = tmp_path / "diagram.svg"

    exit_code = main(
        [
            str(missing_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    assert not output_path.exists()

