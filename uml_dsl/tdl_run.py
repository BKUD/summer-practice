#!/usr/bin/env python3
"""
TDL → SVG: чтение файла .tdl, разбор, сборка модели, рендер в SVG.
Запуск: python -m uml_dsl.tdl_run <файл.tdl> [выход.svg|выход.png]
       или из корня: python -m uml_dsl.tdl_run examples/example.tdl
       для PNG: python -m uml_dsl.tdl_run examples/example.tdl out.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .graphviz_render import diagram_to_graphviz_svg
from .tdl_build import build_diagram
from .tdl_lexer import lex
from .tdl_parser import parse_tdl


def tdl_to_svg(tdl_source: str) -> str:
    """
    Преобразовать текст TDL в SVG.

    Используется Streamlit-приложением и может вызываться
    программно без работы с файлами.
    """
    tokens = lex(tdl_source)
    ast = parse_tdl(tokens)
    diagram = build_diagram(ast)

    return diagram_to_graphviz_svg(diagram)


def render_tdl_file(
    input_path: Path,
    output_path: Path,
) -> Path:
    """Преобразовать TDL-файл в SVG и сохранить результат."""

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Входной TDL-файл не найден: {input_path}"
        )

    source = input_path.read_text(encoding="utf-8")

    # Используем ту же функцию, что и Streamlit.
    svg = tdl_to_svg(source)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        svg,
        encoding="utf-8",
    )

    return output_path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Преобразование диаграммы TDL "
            "в SVG через Graphviz."
        )
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Путь к исходному .tdl-файлу.",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Путь для сохранения итогового .svg-файла.",
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        output_path = render_tdl_file(
            input_path=args.input,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            f"Ошибка генерации SVG: {exc}",
            file=sys.stderr,
        )
        return 1

    resolved_path = output_path.resolve()

    print(f"SVG сохранён: {resolved_path}")
    print(f"Размер: {resolved_path.stat().st_size} байт")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())