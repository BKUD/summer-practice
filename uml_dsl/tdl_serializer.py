from __future__ import annotations

from typing import Any

from .diagram import ClassDiagram
from .enums import AggregationKind, Changeability
from .models import Class
from .relationships import AssociationEnd


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, int):
        return str(value)

    # Строки и дробные числа безопаснее заключать в кавычки,
    # поскольку текущий лексер TDL распознаёт только целые NUMBER.
    return _quote(str(value))


def _format_association_end(end: AssociationEnd) -> str:
    result = end.participant.name

    if end.multiplicity is not None:
        multiplicity = str(end.multiplicity)

        if ".." in multiplicity or "," in multiplicity:
            result += f" [{multiplicity}]"
        else:
            result += f" {multiplicity}"

    if end.role:
        result += f" : {end.role}"

    return result


def diagram_to_tdl(diagram: ClassDiagram) -> str:
    """Сериализует поддерживаемую Pydantic-модель диаграммы в TDL."""

    lines: list[str] = []

    for classifier in diagram.classifiers.values():
        if not isinstance(classifier, Class):
            raise ValueError(
                f"TDL-сериализатор пока не поддерживает "
                f"{type(classifier).__name__}"
            )

        header = f"КЛАСС {classifier.name}"
        if classifier.is_abstract:
            header += " АБСТРАКТНЫЙ"

        lines.append(header)

        if classifier.attributes:
            lines.append("  АТРИБУТЫ")

            for attribute in classifier.attributes:
                visibility = (
                    f"{attribute.visibility.value} "
                    if attribute.visibility is not None
                    else ""
                )

                line = f"    {visibility}{attribute.name}"

                if attribute.multiplicity is not None:
                    line += f" [{attribute.multiplicity}]"

                if attribute.type_:
                    line += f" : {attribute.type_}"

                if attribute.initial_value is not None:
                    line += f" = {_format_value(attribute.initial_value)}"

                if attribute.changeability == Changeability.READ_ONLY:
                    line += " {только_чтение}"

                lines.append(line)

        if classifier.operations:
            lines.append("  ОПЕРАЦИИ")

            for operation in classifier.operations:
                visibility = (
                    f"{operation.visibility.value} "
                    if operation.visibility is not None
                    else ""
                )

                # Текущая грамматика TDL поддерживает только имена параметров.
                parameters = ", ".join(
                    parameter.name for parameter in operation.parameters
                )

                line = (
                    f"    {visibility}"
                    f"{operation.name}({parameters})"
                )

                if operation.return_type:
                    line += f" : {operation.return_type}"

                properties: list[str] = []

                if operation.is_abstract:
                    properties.append("абстрактная")
                if operation.is_query:
                    properties.append("запрос")
                if operation.is_leaf:
                    properties.append("лист")

                if properties:
                    line += " {" + ", ".join(properties) + "}"

                lines.append(line)

        lines.append("КОНЕЦ КЛАСС")
        lines.append("")

    for generalization in diagram.generalizations:
        lines.append(
            "ОБОБЩЕНИЕ "
            f"{generalization.specific.name} -> "
            f"{generalization.general.name}"
        )

    for dependency in diagram.dependencies:
        line = (
            "ЗАВИСИМОСТЬ "
            f"{dependency.client.name} -> "
            f"{dependency.supplier.name}"
        )

        if dependency.stereotype is not None:
            line += f" {dependency.stereotype.value}"

        lines.append(line)

    for realization in diagram.realizations:
        lines.append(
            "РЕАЛИЗАЦИЯ "
            f"{realization.implementer.name} -> "
            f"{realization.interface_.name}"
        )

    for association in diagram.associations:
        if len(association.ends) != 2:
            raise ValueError(
                "Текущая грамматика TDL поддерживает "
                "только бинарные ассоциации"
            )

        if any(
            end.aggregation != AggregationKind.NONE
            for end in association.ends
        ):
            raise ValueError(
                "Текущая грамматика TDL ещё не умеет описывать "
                "агрегацию и композицию"
            )

        lines.append("")
        lines.append("АССОЦИАЦИЯ")
        lines.append(f"  {_format_association_end(association.ends[0])}")
        lines.append("  --")
        lines.append(f"  {_format_association_end(association.ends[1])}")

        if association.name:
            lines.append(f"  ИМЯ {_quote(association.name)}")

        if association.is_derived:
            lines.append("  ПРОИЗВОДНАЯ")

    return "\n".join(lines).rstrip() + "\n"