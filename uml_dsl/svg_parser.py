"""
Парсер SVG с data-атрибутами обратно в Pydantic-модель UML.
Использует BeautifulSoup для парсинга XML.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple, Any

from pydantic import BaseModel, Field
import json

from .models import (
    Class, Attribute, Operation, Parameter,
    MultiplicityRange, Visibility, Scope, Stereotype
)
from .relationships import (
    Association, AssociationEnd, Dependency, 
    Generalization, Realization, AggregationKind
)
from .diagram import ClassDiagram, ClassPosition


class ParseResult(BaseModel):
    """Результат парсинга SVG в Pydantic-модель."""
    success: bool
    diagram: Optional[ClassDiagram] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def parse_transform(transform_str: str) -> Tuple[float, float]:
    """Извлекает координаты из transform="translate(x,y)"."""
    if not transform_str or "translate" not in transform_str:
        return (0.0, 0.0)
    # translate(10,20) или translate(10 20)
    import re
    match = re.search(r'translate\(([^,)]+)[,\s]+([^)]+)\)', transform_str)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    return (0.0, 0.0)


def parse_svg_to_diagram(svg_content: str) -> ParseResult:
    """
    Парсит SVG с data-атрибутами и восстанавливает ClassDiagram.
    
    Собирает ошибки и предупреждения вместо выбрасывания исключений.
    
    Args:
        svg_content: содержимое SVG-файла
        
    Returns:
        ParseResult с диаграммой, ошибками и предупреждениями
    """
    errors: List[str] = []
    warnings: List[str] = []
    
    try:
        root = ET.fromstring(svg_content)
    except ET.ParseError as e:
        return ParseResult(
            success=False,
            errors=[f"Ошибка парсинга XML: {e}"]
        )
    
    # Проверка наличия классов
    class_elements = root.findall('.//*[@data-type="class"]')
    if not class_elements:
        return ParseResult(
            success=False,
            errors=["Диаграмма не содержит размеченных классов. Убедитесь, что SVG сгенерирован TDL."]
        )
    
    # Создаём пустую диаграмму
    diagram = ClassDiagram(title="Imported from SVG")

    layout_json = root.get("data-layout")

    if layout_json:
        try:
            layout_commands = json.loads(layout_json)

            if not isinstance(layout_commands, list):
                raise ValueError(
                    "data-layout должен содержать JSON-массив"
                )

            if not all(
                    isinstance(command, dict)
                    for command in layout_commands
            ):
                raise ValueError(
                    "Каждая команда data-layout должна быть объектом"
                )

            diagram.layout_commands = layout_commands

        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            errors.append(
                f"Некорректные данные размещения data-layout: {exc}"
            )
    
    # 1. Сначала парсим все классы (они нужны для ссылок в отношениях)
    class_positions = {}
    
    for elem in class_elements:
        class_id = elem.get('data-id')
        if not class_id:
            errors.append(f"Класс без атрибута data-id (элемент {elem.tag})")
            continue

        model_json = elem.get("data-model")

        if model_json:
            try:
                model_data = json.loads(model_json)
                cls = Class.model_validate(model_data)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                errors.append(
                    f"Класс '{class_id}': некорректный data-model: {exc}"
                )
                continue
        else:
            # Совместимость со старыми SVG, где полной модели ещё не было.
            name = elem.get("data-name", class_id)
            stereo = elem.get("data-stereotype")
            is_abstract = elem.get("data-abstract") == "true"

            cls = Class(
                name=name,
                stereotype=Stereotype(stereo) if stereo else None,
                is_abstract=is_abstract,
            )

            warnings.append(
                f"Класс '{name}' не содержит data-model; "
                "атрибуты и операции восстановить невозможно"
            )

        name = cls.name

        
        diagram.add_classifier(cls)
        
        # Сохраняем позицию
        transform = elem.get('transform', '')
        x, y = parse_transform(transform)
        
        # Ищем rect с размерами (первый внутри группы)
        rect = elem.find('.//rect')
        if rect is not None:
            width = float(rect.get('width', '120'))
            height = float(rect.get('height', '60'))
        else:
            width, height = 120, 60
            
        class_positions[name] = ClassPosition(
            classifier_name=name,
            x=x, y=y,
            width=width, height=height
        )
    
    # Добавляем все позиции в диаграмму
    diagram.positions.update(class_positions)
    
    # 2. Парсим отношения (ассоциации)
    for elem in root.findall('.//*[@data-type="association"]'):
        src = elem.get('data-src')
        tgt = elem.get('data-tgt')
        
        if not src or not tgt:
            warnings.append(f"Ассоциация без data-src или data-tgt (игнорируется)")
            continue
            
        src_cls = diagram.classifiers.get(src)
        tgt_cls = diagram.classifiers.get(tgt)
        
        if not src_cls:
            errors.append(f"Ассоциация: класс-источник '{src}' не найден")
            continue
        if not tgt_cls:
            errors.append(f"Ассоциация: класс-целевой '{tgt}' не найден")
            continue
        
        # Создаём полюса ассоциации
        src_multiplicity = elem.get('data-src-multiplicity')
        tgt_multiplicity = elem.get('data-tgt-multiplicity')
        
        src_agg = elem.get('data-src-aggregation', 'none')
        tgt_agg = elem.get('data-tgt-aggregation', 'none')
        
        src_nav = elem.get('data-src-navigable')
        tgt_nav = elem.get('data-tgt-navigable')

        src_role = elem.get("data-src-role")
        tgt_role = elem.get("data-tgt-role")
        
        # Парсим кратность с обработкой ошибок
        src_mult_obj = None
        if src_multiplicity:
            try:
                src_mult_obj = MultiplicityRange.from_str(src_multiplicity)
            except (ValueError, IndexError) as e:
                warnings.append(f"Ассоциация '{src}→{tgt}': некорректная кратность источника '{src_multiplicity}'")
        
        tgt_mult_obj = None
        if tgt_multiplicity:
            try:
                tgt_mult_obj = MultiplicityRange.from_str(tgt_multiplicity)
            except (ValueError, IndexError) as e:
                warnings.append(f"Ассоциация '{src}→{tgt}': некорректная кратность целевой '{tgt_multiplicity}'")

        end1 = AssociationEnd(
            participant=src_cls,
            role=src_role or None,
            multiplicity=src_mult_obj,
            aggregation=AggregationKind(src_agg),
            navigable={"true": True, "false": False}.get(src_nav)
            if src_nav
            else None,
        )

        end2 = AssociationEnd(
            participant=tgt_cls,
            role=tgt_role or None,
            multiplicity=tgt_mult_obj,
            aggregation=AggregationKind(tgt_agg),
            navigable={"true": True, "false": False}.get(tgt_nav)
            if tgt_nav
            else None,
        )
        
        assoc = Association(
            name=elem.get('data-name'),
            is_derived=elem.get('data-derived') == 'true',
            ends=[end1, end2]
        )
        
        diagram.add_association(assoc)
    
    # 3. Парсим зависимости
    for elem in root.findall('.//*[@data-type="dependency"]'):
        src = elem.get('data-src')
        tgt = elem.get('data-tgt')
        
        if not src or not tgt:
            warnings.append(f"Зависимость без data-src или data-tgt (игнорируется)")
            continue
            
        src_cls = diagram.classifiers.get(src)
        tgt_cls = diagram.classifiers.get(tgt)
        
        if not src_cls:
            errors.append(f"Зависимость: класс-клиент '{src}' не найден")
            continue
        if not tgt_cls:
            errors.append(f"Зависимость: класс-поставщик '{tgt}' не найден")
            continue
        
        stereo = elem.get('data-stereotype')
        # Используем стереотип только если он задан и не пустой
        stereotype = stereo if stereo else None
        
        dep = Dependency(
            client=src_cls,
            supplier=tgt_cls,
            stereotype=stereotype
        )
        
        diagram.dependencies.append(dep)
    
    # 4. Парсим обобщения
    for elem in root.findall('.//*[@data-type="generalization"]'):
        src = elem.get('data-src')
        tgt = elem.get('data-tgt')
        
        if not src or not tgt:
            warnings.append(f"Обобщение без data-src или data-tgt (игнорируется)")
            continue
            
        src_cls = diagram.classifiers.get(src)
        tgt_cls = diagram.classifiers.get(tgt)
        
        if not src_cls:
            errors.append(f"Обобщение: класс-частный '{src}' не найден")
            continue
        if not tgt_cls:
            errors.append(f"Обобщение: класс-общий '{tgt}' не найден")
            continue
        
        is_substitutable = elem.get('data-substitutable') != 'false'
        
        gen = Generalization(
            specific=src_cls,
            general=tgt_cls,
            is_substitutable=is_substitutable
        )
        
        diagram.generalizations.append(gen)
    
    # 5. Парсим реализации
    for elem in root.findall('.//*[@data-type="realization"]'):
        src = elem.get('data-src')
        tgt = elem.get('data-tgt')
        
        if not src or not tgt:
            warnings.append(f"Реализация без data-src или data-tgt (игнорируется)")
            continue
            
        src_cls = diagram.classifiers.get(src)
        tgt_cls = diagram.classifiers.get(tgt)
        
        if not src_cls:
            errors.append(f"Реализация: класс-реализатор '{src}' не найден")
            continue
        if not tgt_cls:
            errors.append(f"Реализация: интерфейс '{tgt}' не найден")
            continue
        
        real = Realization(
            implementer=src_cls,
            interface_=tgt_cls
        )
        
        diagram.realizations.append(real)
    
    # Возвращаем результат с диаграммой и любыми накопленными предупреждениями
    return ParseResult(
        success=not errors,
        diagram=diagram,
        errors=errors,
        warnings=warnings,
    )


# Добавляем вспомогательный метод в MultiplicityRange
def multiplicity_range_from_str(s: str) -> MultiplicityRange:
    """Парсит строку вида '1..*' или '0..1' или '*'."""
    if not s:
        return MultiplicityRange(lower=0, upper=None)
    
    if s == '*':
        return MultiplicityRange(lower=0, upper=None)
    
    if '..' in s:
        parts = s.split('..')
        lower = int(parts[0])
        upper = None if parts[1] == '*' else int(parts[1])
        return MultiplicityRange(lower=lower, upper=upper)
    
    # Одиночное число
    val = int(s)
    return MultiplicityRange(lower=val, upper=val)

# Monkey-patch для удобства
MultiplicityRange.from_str = staticmethod(multiplicity_range_from_str)