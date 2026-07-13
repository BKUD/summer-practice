"""
Модель диаграммы: контейнер классов, отношений, глобальная валидация
и полный рендеринг в интерактивный SVG.

Все проверки и поля подкреплены цитатами из книги «Моделирование на UML»
(Новиков, Иванов), разделы 3.1–3.3.
"""
from __future__ import annotations

import html as html_mod
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field, model_validator

from .enums import (
    AggregationKind,
    Stereotype,
    Visibility,
)
from .models import (
    SVG_CHAR_WIDTH,
    SVG_FONT_FAMILY,
    SVG_FONT_SIZE,
    SVG_FONT_WEIGHT,
    SVG_LINE_HEIGHT,
    SVG_MIN_WIDTH,
    SVG_PADDING,
    SVG_STROKE,
    SVG_STROKE_WIDTH,
    Classifier,
    Class,
    PRIMITIVE_TYPE_MAP,
)
from .relationships import (
    Association,
    AssociationClass,
    AssociationEnd,
    AggregationEnd,
    Dependency,
    Generalization,
    GeneralizationSet,
    Realization,
)


# ─── Вспомогательные функции геометрии ─────────────────────────────────


def _get_edge_midpoints(rx: float, ry: float, rw: float, rh: float) -> Dict[str, Tuple[float, float]]:
    """Возвращает координаты середин всех 4 сторон прямоугольника."""
    cx = rx + rw / 2
    cy = ry + rh / 2
    return {
        'top': (cx, ry),
        'bottom': (cx, ry + rh),
        'left': (rx, cy),
        'right': (rx + rw, cy),
    }


def _line_crosses_rect_interior(
    x1: float, y1: float, x2: float, y2: float,
    rx: float, ry: float, rw: float, rh: float,
) -> bool:
    """Проверяет, проходит ли отрезок (x1,y1)-(x2,y2) через внутренность прямоугольника."""
    # Центр прямоугольника
    cx = rx + rw / 2
    cy = ry + rh / 2
    
    # Если хотя бы одна точка внутри - считаем что проходит
    def point_inside(px, py):
        return rx < px < rx + rw and ry < py < ry + rh
    
    if point_inside(x1, y1) or point_inside(x2, y2):
        return True
    
    # Проверяем, пересекает ли отрезок стороны прямоугольника,
    # и при этом средняя точка отрезка внутри прямоугольника
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2
    
    if point_inside(mx, my):
        return True
    
    return False


def _find_best_edge_connection(
    r1x: float, r1y: float, r1w: float, r1h: float,
    r2x: float, r2y: float, r2w: float, r2h: float,
) -> Tuple[Tuple[float, float], str, Tuple[float, float], str]:
    """Находит оптимальную пару середин сторон для соединения двух прямоугольников.
    
    Алгоритм:
    1. Вычисляет середины всех сторон обоих прямоугольников
    2. Перебирает все 16 возможных пар
    3. Отбрасывает пары, где отрезок проходит через внутренность любого прямоугольника
    4. Из оставшихся выбирает пару с минимальным расстоянием
    
    Returns:
        Tuple: (point_on_r1, side1_name, point_on_r2, side2_name)
    """
    edges1 = _get_edge_midpoints(r1x, r1y, r1w, r1h)
    edges2 = _get_edge_midpoints(r2x, r2y, r2w, r2h)
    
    best_pair = None
    best_sides = None
    min_dist = float('inf')
    
    for edge1_name, p1 in edges1.items():
        for edge2_name, p2 in edges2.items():
            # Проверяем, не проходит ли отрезок через внутренность прямоугольников
            if _line_crosses_rect_interior(p1[0], p1[1], p2[0], p2[1], r1x, r1y, r1w, r1h):
                continue
            if _line_crosses_rect_interior(p1[0], p1[1], p2[0], p2[1], r2x, r2y, r2w, r2h):
                continue
            
            # Вычисляем расстояние
            dist = (p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2
            
            if dist < min_dist:
                min_dist = dist
                best_pair = (p1, p2)
                best_sides = (edge1_name, edge2_name)
    
    # Если не нашли подходящую пару (очень редкий случай), берем центры
    if best_pair is None:
        c1 = (r1x + r1w / 2, r1y + r1h / 2)
        c2 = (r2x + r2w / 2, r2y + r2h / 2)
        return (c1, 'center', c2, 'center')
    
    return (best_pair[0], best_sides[0], best_pair[1], best_sides[1])


def _build_orthogonal_path(
    p1: Tuple[float, float], side1: str,
    p2: Tuple[float, float], side2: str,
    start_offset: float = 0.0,
    end_offset: float = 0.0,
) -> List[Tuple[float, float]]:
    """Строит ортогональный путь с минимумом изгибов между двумя точками на рёбрах.
    
    Если offset > 0, добавляет короткий перпендикулярный сегмент для правильной ориентации маркера.
    
    Args:
        p1: первая точка (x, y)
        side1: название стороны первой точки ('top', 'bottom', 'left', 'right', 'center')
        p2: вторая точка (x, y)
        side2: название стороны второй точки
        start_offset: длина перпендикулярного сегмента в начале (по умолчанию 0)
        end_offset: длина перпендикулярного сегмента в конце (по умолчанию 0)
        
    Returns:
        Список точек для polyline (минимум 2 точки)
    """
    # Для правильной ориентации маркера добавляем короткие перпендикулярные сегменты
    start_segment = None
    end_segment = None
    
    if start_offset > 0:
        # Добавляем сегмент наружу от первой точки
        if side1 == 'left':
            start_segment = (p1[0] - start_offset, p1[1])
        elif side1 == 'right':
            start_segment = (p1[0] + start_offset, p1[1])
        elif side1 == 'top':
            start_segment = (p1[0], p1[1] - start_offset)
        elif side1 == 'bottom':
            start_segment = (p1[0], p1[1] + start_offset)
    
    if end_offset > 0:
        # Добавляем сегмент наружу от второй точки
        if side2 == 'left':
            end_segment = (p2[0] - end_offset, p2[1])
        elif side2 == 'right':
            end_segment = (p2[0] + end_offset, p2[1])
        elif side2 == 'top':
            end_segment = (p2[0], p2[1] - end_offset)
        elif side2 == 'bottom':
            end_segment = (p2[0], p2[1] + end_offset)
    
    # Строим основной путь между исходными точками
    tolerance = 5
    is_vertical = abs(p1[0] - p2[0]) < tolerance
    is_horizontal = abs(p1[1] - p2[1]) < tolerance
    
    # Прямая линия если выровнены (0 изгибов)
    if is_vertical or is_horizontal:
        path = [p1, p2]
    else:
        # Определяем ориентацию сторон
        s1_vert = side1 in ('left', 'right')
        s2_vert = side2 in ('left', 'right')
        
        # L-образный путь (1 изгиб) - предпочтительнее
        if s1_vert and not s2_vert:
            path = [p1, (p1[0], p2[1]), p2]
        elif not s1_vert and s2_vert:
            path = [p1, (p2[0], p1[1]), p2]
        # Z-образный путь (2 изгиба)
        elif s1_vert and s2_vert:
            mid_x = (p1[0] + p2[0]) / 2
            path = [p1, (mid_x, p1[1]), (mid_x, p2[1]), p2]
        else:
            mid_y = (p1[1] + p2[1]) / 2
            path = [p1, (p1[0], mid_y), (p2[0], mid_y), p2]
    
    # Добавляем перпендикулярные сегменты
    if start_segment:
        path = [start_segment] + path
    if end_segment:
        # Для marker-end: путь идет от p2 к endSegment, маркер на endSegment ориентирован НАРУЖУ
        # Путь: ... -> p2 (на ребре) -> endSegment (снаружи, маркер здесь)
        path = path + [end_segment]
    
    return path


def _orthogonal_route(
    sx: float, sy: float, sw: float, sh: float,
    tx: float, ty: float, tw: float, th: float,
) -> List[Tuple[float, float]]:
    """Создаёт ломаную с прямыми углами между двумя прямоугольниками.

    Возвращает список точек [(x,y), ...] для polyline.
    """
    scx, scy = sx + sw / 2, sy + sh / 2
    tcx, tcy = tx + tw / 2, ty + th / 2
    dx = tcx - scx
    dy = tcy - scy

    # Обнаружение самоассоциации (один и тот же прямоугольник)
    if abs(sx - tx) < 1 and abs(sy - ty) < 1 and abs(sw - tw) < 1 and abs(sh - th) < 1:
        # Петля: выход справа, вверх, влево, вход сверху
        off = 30
        return [
            (sx + sw, scy - 10),
            (sx + sw + off, scy - 10),
            (sx + sw + off, sy - off),
            (scx + 10, sy - off),
            (scx + 10, sy),
        ]

    if abs(dx) >= abs(dy):
        # Преимущественно горизонтальное
        if dx >= 0:
            exit_x = sx + sw
            enter_x = tx
        else:
            exit_x = sx
            enter_x = tx + tw
        mid_x = (exit_x + enter_x) / 2
        # Если прямоугольники перекрываются по горизонтали
        if (dx >= 0 and exit_x >= enter_x) or (dx < 0 and exit_x <= enter_x):
            mid_x = exit_x + (25 if dx >= 0 else -25)
        return [
            (exit_x, scy),
            (mid_x, scy),
            (mid_x, tcy),
            (enter_x, tcy),
        ]
    else:
        # Преимущественно вертикальное
        if dy >= 0:
            exit_y = sy + sh
            enter_y = ty
        else:
            exit_y = sy
            enter_y = ty + th
        mid_y = (exit_y + enter_y) / 2
        if (dy >= 0 and exit_y >= enter_y) or (dy < 0 and exit_y <= enter_y):
            mid_y = exit_y + (25 if dy >= 0 else -25)
        return [
            (scx, exit_y),
            (scx, mid_y),
            (tcx, mid_y),
            (tcx, enter_y),
        ]
    half_h = ch / 2

    # Наклон луча
    if abs(dx) < 1e-9:
        # вертикальная линия
        return mx, (cy if dy < 0 else cy + ch)

    if abs(dy) < 1e-9:
        # горизонтальная
        return (cx if dx < 0 else cx + cw), my

    t_right = half_w / abs(dx) if dx != 0 else float("inf")
    t_bottom = half_h / abs(dy) if dy != 0 else float("inf")
    t = min(t_right, t_bottom)
    return mx + dx * t, my + dy * t


# ═══════════════════════════════════════════════════════════════════════════
# Позиция класса на диаграмме
# ═══════════════════════════════════════════════════════════════════════════


class ClassPosition(BaseModel):
    """Позиция и размер класса на диаграмме (для SVG рендеринга)."""
    classifier_name: str
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Диаграмма классов
# ═══════════════════════════════════════════════════════════════════════════


class ClassDiagram(BaseModel):
    """Контейнер всей модели диаграммы классов (§3.1–§3.3).

    Содержит классификаторы, отношение и глобальную валидацию.
    """
    title: str = Field(
        default="UML Class Diagram",
        description="Заголовок диаграммы.",
    )
    classifiers: Dict[str, Classifier] = Field(
        default_factory=dict,
        description="Словарь классификаторов (ключ — имя).",
    )
    associations: List[Association] = Field(
        default_factory=list,
        description="Ассоциации (бинарные, n-арные).",
    )
    association_classes: List[AssociationClass] = Field(
        default_factory=list,
        description="Классы ассоциаций (§3.3.8).",
    )
    generalizations: List[Generalization] = Field(
        default_factory=list,
        description="Обобщения.",
    )
    generalization_sets: List[GeneralizationSet] = Field(
        default_factory=list,
        description="Наборы обобщений.",
    )
    dependencies: List[Dependency] = Field(
        default_factory=list,
        description="Зависимости.",
    )
    realizations: List[Realization] = Field(
        default_factory=list,
        description="Реализации.",
    )

    # Позиции (заполняются при layout или пользовательском позиционировании)
    positions: Dict[str, ClassPosition] = Field(
        default_factory=dict,
        description="Позиции классификаторов на холсте.",
    )

    # ──── Удобные методы добавления ────────────────────────────────────

    def add_classifier(self, c: Classifier) -> "ClassDiagram":
        self.classifiers[c.name] = c
        return self

    def add_association(self, a: Association) -> "ClassDiagram":
        self.associations.append(a)
        return self

    def add_aggregation(
        self,
        whole: Any,
        part: Any,
        whole_multiplicity: Optional[MultiplicityRange] = None,
        part_multiplicity: Optional[MultiplicityRange] = None,
        name: Optional[str] = None,
        aggregation_kind: AggregationKind = AggregationKind.AGGREGATION,
        navigable_whole: Optional[bool] = None,
        navigable_part: Optional[bool] = None,
        **kw: Any,
    ) -> "ClassDiagram":
        """Convenience helper to add an aggregation/composition between two classifiers.

        `whole` and `part` may be either names (str) or `Classifier`/`Class` objects.
        The `whole` end will be created as `AggregationEnd` with the provided
        `aggregation_kind` (AGGREGATION or COMPOSITION). The `part` end will be
        a regular `AssociationEnd`.
        """
        # resolve participants to Classifier objects
        w_obj = whole
        p_obj = part
        if isinstance(whole, str):
            w_obj = self.classifiers.get(whole)
            if w_obj is None:
                raise ValueError(f"Unknown classifier '{whole}'")
        if isinstance(part, str):
            p_obj = self.classifiers.get(part)
            if p_obj is None:
                raise ValueError(f"Unknown classifier '{part}'")

        # Build ends
        w_end = AggregationEnd(
            participant=w_obj,
            aggregation=aggregation_kind,
            multiplicity=whole_multiplicity,
            navigable=navigable_whole,
        )
        p_end = AssociationEnd(
            participant=p_obj,
            multiplicity=part_multiplicity,
            navigable=navigable_part,
        )

        assoc = Association(name=name, ends=[w_end, p_end], **kw)
        self.associations.append(assoc)
        return self

    def add_generalization(
        self, specific: str, general: str, **kw: Any,
        ) -> "ClassDiagram":
        # Accept either names or Classifier objects. Resolve names to objects.
        s_obj = specific
        g_obj = general
        if isinstance(specific, str):
            s_obj = self.classifiers.get(specific)
            if s_obj is None:
                raise ValueError(f"Unknown classifier '{specific}'")
        if isinstance(general, str):
            g_obj = self.classifiers.get(general)
            if g_obj is None:
                raise ValueError(f"Unknown classifier '{general}'")
        self.generalizations.append(
            Generalization(specific=s_obj, general=g_obj, **kw)
        )
        return self

    def add_dependency(
        self, client: Any, supplier: Any, **kw: Any,
    ) -> "ClassDiagram":
        # Accept either names or Class objects. Resolve names to objects.
        c_obj = client
        s_obj = supplier
        if isinstance(client, str):
            c_obj = self.classifiers.get(client)
            if c_obj is None:
                raise ValueError(f"Unknown classifier '{client}'")
        if isinstance(supplier, str):
            s_obj = self.classifiers.get(supplier)
            if s_obj is None:
                raise ValueError(f"Unknown classifier '{supplier}'")
        self.dependencies.append(
            Dependency(client=c_obj, supplier=s_obj, **kw)
        )
        return self

    def add_realization(
        self, implementing: Any, interface: Any,
    ) -> "ClassDiagram":
        # Accept either names or Classifier objects. Resolve names to objects.
        impl_obj = implementing
        intf_obj = interface
        if isinstance(implementing, str):
            impl_obj = self.classifiers.get(implementing)
            if impl_obj is None:
                raise ValueError(f"Unknown classifier '{implementing}'")
        if isinstance(interface, str):
            intf_obj = self.classifiers.get(interface)
            if intf_obj is None:
                raise ValueError(f"Unknown classifier '{interface}'")
        self.realizations.append(
            Realization(implementer=impl_obj, interface_=intf_obj)
        )
        return self

    # ──── Глобальная валидация ──────────────────────────────────────────

    def validate_no_inheritance_cycles(self) -> None:
        """Цитата: «Обобщения в модели должны образовывать строгий частичный
        порядок.»  → циклы наследования = синтаксическая ошибка.
        """
        graph: Dict[str, List[str]] = {}
        for g in self.generalizations:
            graph.setdefault(g.specific.name, []).append(g.general.name)
        for gs in self.generalization_sets:
            for g in gs.generalizations:
                graph.setdefault(g.specific.name, []).append(g.general.name)

        visiting: Set[str] = set()
        visited: Set[str] = set()

        def dfs(node: str) -> None:
            if node in visiting:
                raise ValueError(
                    f"Обнаружен цикл наследования с участием '{node}'"
                )
            if node in visited:
                return
            visiting.add(node)
            for parent in graph.get(node, []):
                dfs(parent)
            visiting.discard(node)
            visited.add(node)

        for n in list(graph.keys()):
            dfs(n)

    def validate_composition_constraint(self) -> None:
        """Цитата: «Композиционно часть A может входить только в одно целое B,
        часть существует, только пока существует целое.»

        Проверяем, что классификатор не является «частью» в двух
        различных композициях.
        """
        parts_count: Dict[str, int] = {}
        for assoc in self.associations:
            comp_ends = [
                e for e in assoc.ends
                if getattr(e, "aggregation", AggregationKind.NONE) == AggregationKind.COMPOSITION
            ]
            if not comp_ends:
                continue
            for end in assoc.ends:
                if getattr(end, "aggregation", AggregationKind.NONE) != AggregationKind.COMPOSITION:
                    parts_count[end.participant.name] = (
                        parts_count.get(end.participant.name, 0) + 1
                    )
        for part, count in parts_count.items():
            if count > 1:
                raise ValueError(
                    f"Класс '{part}' является частью в {count} композициях "
                    "(допускается максимум 1)"
                )

    def validate_multiple_inheritance_conflicts(self) -> None:
        """Цитата: «Конфликт при множественном наследовании возникает, если
        подкласс наследует атрибуты с одинаковыми именами, но разными типами
        от разных суперклассов.»
        """
        parents_map: Dict[str, List[str]] = {}
        for g in self.generalizations:
            parents_map.setdefault(g.specific.name, []).append(g.general.name)

        for child_name, parents in parents_map.items():
            if len(parents) < 2:
                continue
            inherited: Dict[str, List[Tuple[str, Optional[str]]]] = {}
            for p_name in parents:
                pcls = self.classifiers.get(p_name)
                if pcls:
                    for attr in pcls.attributes:
                        inherited.setdefault(attr.name, []).append(
                            (p_name, attr.type_)
                        )
            for attr_name, sources in inherited.items():
                if len(sources) > 1:
                    types = set(t for _, t in sources)
                    if len(types) > 1:
                        src_names = ", ".join(p for p, _ in sources)
                        raise ValueError(
                            f"Конфликт множественного наследования в '{child_name}': "
                            f"атрибут '{attr_name}' имеет разные типы от "
                            f"родителей {src_names}"
                        )

    def validate_all_ends_reference_known_classifiers(self) -> None:
        """Проверяем, что все полюса ассоциаций ссылаются на известные
        классификаторы."""
        known = set(self.classifiers.keys())
        for assoc in self.associations:
            for end in assoc.ends:
                if end.participant.name not in known:
                    raise ValueError(
                        f"Полюс ассоциации ссылается на неизвестный "
                        f"классификатор '{end.participant.name}'"
                    )

    def validate_all(self) -> None:
        """Выполнить все глобальные проверки."""
        self.validate_no_inheritance_cycles()
        self.validate_composition_constraint()
        self.validate_multiple_inheritance_conflicts()
        self.validate_redefines_references()
        self.validate_attribute_type_references()
        self.validate_parameter_type_references()
        self.validate_template_parameter_type_references()
        self.validate_all_ends_reference_known_classifiers()

    def validate_redefines_references(self) -> None:
        """Проверяем, что каждое `redefines` ссылается на реально существующее
        имя элемента (атрибута или операции) в родительских (ancestor) классификаторах.
        """
        # Build parent map
        parents_map: Dict[str, List[str]] = {}
        for g in self.generalizations:
            parents_map.setdefault(g.specific.name, []).append(g.general.name)
        for gs in self.generalization_sets:
            for g in gs.generalizations:
                parents_map.setdefault(g.specific.name, []).append(g.general.name)

        # helper to collect ancestors
        def collect_ancestors(name: str) -> Set[str]:
            res: Set[str] = set()
            stack = parents_map.get(name, [])[:]
            while stack:
                p = stack.pop()
                if p in res:
                    continue
                res.add(p)
                stack.extend(parents_map.get(p, []))
            return res

        for cls_name, cls in self.classifiers.items():
            ancestors = collect_ancestors(cls_name)
            if not ancestors:
                continue
            # collect names of members in ancestors
            anc_attrs: Set[str] = set()
            anc_ops: Set[str] = set()
            for a_name in ancestors:
                a_cls = self.classifiers.get(a_name)
                if not a_cls:
                    continue
                for attr in a_cls.attributes:
                    anc_attrs.add(attr.name)
                for op in a_cls.operations:
                    anc_ops.add(op.name)

            # check attributes
            for attr in cls.attributes:
                if getattr(attr, "redefines", None):
                    if attr.redefines not in anc_attrs:
                        raise ValueError(
                            f"Класс '{cls_name}': атрибут '{attr.name}' переопределяет несуществующий элемент '{attr.redefines}' в родителях"
                        )
            # check operations
            for op in cls.operations:
                if getattr(op, "redefines", None):
                    if op.redefines not in anc_ops:
                        raise ValueError(
                            f"Класс '{cls_name}': операция '{op.name}' переопределяет несуществующий элемент '{op.redefines}' в родителях"
                        )

    def validate_parameter_type_references(self) -> None:
        """Проверяем, что типы параметров и возвращаемые типы либо примитивы,
        либо известные классификаторы на диаграмме.
        """
        known = set(self.classifiers.keys())
        prim_names = set(PRIMITIVE_TYPE_MAP.keys())
        for cls_name, cls in self.classifiers.items():
            for op in cls.operations:
                for p in op.parameters:
                    if not p.type_:
                        continue
                    if p.type_ in prim_names:
                        continue
                    if p.type_ not in known:
                        raise ValueError(
                            f"Параметр '{p.name}' операции '{op.name}' класса '{cls_name}' ссылается на неизвестный тип '{p.type_}'"
                        )
                    target = self.classifiers.get(p.type_)
                    if not isinstance(target, Class):
                        raise ValueError(
                            f"Параметр '{p.name}' операции '{op.name}' класса '{cls_name}' ссылается на тип '{p.type_}', который не является Class"
                        )
                # return type
                if op.return_type:
                    if op.return_type in prim_names:
                        continue
                    if op.return_type not in known:
                        raise ValueError(
                            f"Операция '{op.name}' класса '{cls_name}' имеет неизвестный возвращаемый тип '{op.return_type}'"
                        )
                    ret_target = self.classifiers.get(op.return_type)
                    if not isinstance(ret_target, Class):
                        raise ValueError(
                            f"Операция '{op.name}' класса '{cls_name}' имеет возвращаемый тип '{op.return_type}', который не является Class"
                        )

    def validate_template_parameter_type_references(self) -> None:
        """Проверяем, что для каждого параметра шаблона его `type_` и
        `default_value` либо примитив, либо известный классификатор на диаграмме.
        """
        known = set(self.classifiers.keys())
        prim_names = set(PRIMITIVE_TYPE_MAP.keys())
        for cls_name, cls in self.classifiers.items():
            tpl_params = getattr(cls, "template_parameters", None) or []
            for tp in tpl_params:
                # type_ check
                if tp.type_:
                    if tp.type_ in prim_names:
                        pass
                    elif tp.type_ not in known:
                        raise ValueError(
                            f"Параметр шаблона '{tp.name}' класса '{cls_name}' ссылается на неизвестный тип '{tp.type_}'"
                        )
                    else:
                        target = self.classifiers.get(tp.type_)
                        if not isinstance(target, Class):
                            raise ValueError(
                                f"Параметр шаблона '{tp.name}' класса '{cls_name}' ссылается на тип '{tp.type_}', который не является Class"
                            )
                # default_value check — interpreted as a type name when present
                if tp.default_value:
                    if tp.default_value in prim_names:
                        pass
                    elif tp.default_value not in known:
                        raise ValueError(
                            f"Параметр шаблона '{tp.name}' класса '{cls_name}' имеет неизвестное значение по умолчанию типа '{tp.default_value}'"
                        )
                    else:
                        dv_target = self.classifiers.get(tp.default_value)
                        if not isinstance(dv_target, Class):
                            raise ValueError(
                                f"Параметр шаблона '{tp.name}' класса '{cls_name}' имеет значение по умолчанию типа '{tp.default_value}', который не является Class"
                            )

    def validate_attribute_type_references(self) -> None:
        """Проверяем, что для каждого атрибута ссылаемый тип либо примитив, либо
        известный классификатор на диаграмме.
        """
        known = set(self.classifiers.keys())
        prim_names = set(PRIMITIVE_TYPE_MAP.keys())
        for cls_name, cls in self.classifiers.items():
            for attr in cls.attributes:
                if not attr.type_:
                    continue
                if attr.type_ in prim_names:
                    continue
                if attr.type_ not in known:
                    raise ValueError(
                        f"Атрибут '{attr.name}' класса '{cls_name}' ссылается на неизвестный тип '{attr.type_}'"
                    )

    # ──── Layout ───────────────────────────────────────────────────────

    def auto_layout(
        self,
        cols: int = 3,
        spacing_x: int = 300,
        spacing_y: int = 250,
        start_x: int = 40,
        start_y: int = 40,
    ) -> None:
        """Простая сеточная раскладка классов."""
        names = list(self.classifiers.keys())
        for idx, name in enumerate(names):
            cls = self.classifiers[name]
            w, h = cls.get_box_size()
            row = idx // cols
            col = idx % cols
            x = start_x + col * spacing_x
            y = start_y + row * spacing_y
            self.positions[name] = ClassPosition(
                classifier_name=name, x=x, y=y, width=w, height=h,
            )

    # ──── SVG рендеринг ─────────────────────────────────────────────────

    def _svg_defs(self) -> str:
        """Определения градиентов и маркеров стрелок."""
        return """<defs>
  <linearGradient x1="0" x2="1" id="Gradient" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#f0c955"/>
    <stop offset=".5" stop-color="#ffebc2"/>
    <stop offset="1" stop-color="#f0c955"/>
  </linearGradient>
  <linearGradient id="Obj_Gradient" xlink:href="#Gradient"
    gradientTransform="rotate(90) scale(36)" />
  <linearGradient id="Obj_Gradient_2" xlink:href="#Gradient"
    gradientTransform="translate(0,36) rotate(90) scale(72)" />
  <linearGradient id="Obj_Gradient_3" xlink:href="#Gradient"
    gradientTransform="translate(0,108) rotate(90) scale(56)" />

  <!-- Маркер: открытая стрелка навигации -->
  <marker id="arrow-nav" viewBox="0 0 10 10" refX="10" refY="5"
    markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10" fill="none" stroke="black" stroke-width="1.5"/>
  </marker>

    <!-- Маркер: треугольник обобщения (пустой) - указывает на general -->
  <marker id="arrow-gen" viewBox="0 0 14 14" refX="8" refY="7"
    markerWidth="12" markerHeight="12" orient="auto-start-reverse">
    <path d="M14,0 L0,7 L14,14 Z" fill="white" stroke="black" stroke-width="1.5"/>
  </marker>

    <!-- Маркер: треугольник реализации (пустой, пунктирная линия) - указывает на general -->
  <marker id="arrow-real" viewBox="0 0 14 14" refX="1" refY="7"
    markerWidth="12" markerHeight="12" orient="auto-start-reverse">
    <path d="M14,0 L0,7 L14,14 Z" fill="white" stroke="black" stroke-width="1.5"/>
  </marker>

  <!-- Маркер: стрелка зависимости (StickArrow - точная копия из оригинала) -->
  <marker id="arrow-dep" orient="auto" overflow="visible" markerUnits="strokeWidth"
    viewBox="-11 -5 12 10" markerWidth="12" markerHeight="10">
    <path d="M -9.6000004 0 L 0 0 M 0 3.6000001 L -9.6000004 0 L 0 -3.6000001"
      fill="none" stroke="currentColor" stroke-width="1"/>
  </marker>

  <!-- Ромб агрегации (пустой) -->
  <marker id="diamond-agg" viewBox="0 0 16 10" refX="0" refY="5"
    markerWidth="14" markerHeight="10" orient="auto-start-reverse">
    <path d="M0,5 L8,0 L16,5 L8,10 Z" fill="white" stroke="black" stroke-width="1.2"/>
  </marker>

  <!-- Ромб композиции (закрашенный) -->
  <marker id="diamond-comp" viewBox="0 0 16 10" refX="0" refY="5"
    markerWidth="14" markerHeight="10" orient="auto-start-reverse">
    <path d="M0,5 L8,0 L16,5 L8,10 Z" fill="black" stroke="black" stroke-width="1.2"/>
  </marker>

  <!-- X (крестик) — не навигируем -->
  <marker id="cross-x" viewBox="0 0 10 10" refX="5" refY="5"
    markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <line x1="2" y1="2" x2="8" y2="8" stroke="black" stroke-width="1.5"/>
    <line x1="8" y1="2" x2="2" y2="8" stroke="black" stroke-width="1.5"/>
  </marker>
</defs>"""

    def _svg_styles(self) -> str:
        """CSS стили для интерактивного SVG."""
        return """<style type="text/css">
<![CDATA[
.uml-class { cursor: grab; }
.uml-class:active { cursor: grabbing; }
.uml-edge polyline, .uml-edge line { cursor: pointer; }
.uml-edge:hover polyline, .uml-edge:hover line { stroke-width: 2.5; }
.toolbar-button {
  cursor: pointer;
  user-select: none;
}
.toolbar-button:hover rect { fill: #4a5568; }
.toolbar-button:active rect { fill: #2d3748; }
.toolbar-text { 
  pointer-events: none;
  font-family: Arial, sans-serif;
  font-size: 11px;
  fill: white;
}
.status-text {
  font-family: Arial, sans-serif;
  font-size: 10px;
  fill: #666;
}
]]>
</style>"""

    def _svg_toolbar(self, width: int) -> str:
        """Панель инструментов через SVG элементы."""
        return f"""<g id="toolbar">
  <rect x="0" y="0" width="{width}" height="32" fill="#2d3748" opacity="0.95"/>
  
  <!-- Кнопка: Экспорт SVG -->
  <g class="toolbar-button" id="btn-export" transform="translate(10,6)">
    <rect x="0" y="0" width="100" height="20" rx="3" fill="#374151"/>
    <text class="toolbar-text" x="50" y="14" text-anchor="middle">💾 Экспорт SVG</text>
  </g>
  
  <!-- Кнопка: Копировать -->
  <g class="toolbar-button" id="btn-copy" transform="translate(120,6)">
    <rect x="0" y="0" width="110" height="20" rx="3" fill="#374151"/>
    <text class="toolbar-text" x="55" y="14" text-anchor="middle">📋 Копировать</text>
  </g>
  
  <!-- Кнопка: Сброс -->
  <g class="toolbar-button" id="btn-reset" transform="translate(240,6)">
    <rect x="0" y="0" width="80" height="20" rx="3" fill="#374151"/>
    <text class="toolbar-text" x="40" y="14" text-anchor="middle">↺ Сброс</text>
  </g>
  
  <!-- Статус -->
  <text id="status-text" class="status-text" x="{width - 10}" y="20" text-anchor="end"></text>
</g>"""

    def _svg_script(self) -> str:
        """JavaScript для интерактивности: drag&drop и экспорт."""
        return """<script type="text/javascript">
<![CDATA[
(function(){
"use strict";

const svg = document.querySelector("svg");
if (!svg) return;

// ─── Утилиты ────────────────────────────────────────────────────────────

function getTranslate(el){
  const t = el.getAttribute("transform")||"";
  const m = /translate\\(\\s*([^,\\s]+)[,\\s]+([^)]+)\\)/.exec(t);
  return m ? [parseFloat(m[1]),parseFloat(m[2])] : [0,0];
}
function setTranslate(el,x,y){
  el.setAttribute("transform",`translate(${x},${y})`);
}
function getBBox(el){
  const bb = el.querySelector(".uml-bbox");
  if(bb) return {
    x: parseFloat(bb.getAttribute("x")),
    y: parseFloat(bb.getAttribute("y")),
    width: parseFloat(bb.getAttribute("width")),
    height: parseFloat(bb.getAttribute("height"))
  };
  return el.getBBox();
}
function getClassRect(id){
  const g = svg.querySelector(`.uml-class[data-id="${id}"]`);
  if(!g) return null;
  const [tx,ty] = getTranslate(g);
  const bb = getBBox(g);
  return {x:tx+bb.x, y:ty+bb.y, width:bb.width, height:bb.height};
}

// ─── Ортогональная маршрутизация ────────────────────────────────────────

function orthoRoute(sr, tr){
  const scx=sr.x+sr.width/2, scy=sr.y+sr.height/2;
  const tcx=tr.x+tr.width/2, tcy=tr.y+tr.height/2;
  const dx=tcx-scx, dy=tcy-scy;
  // Самоассоциация
  if(Math.abs(sr.x-tr.x)<1 && Math.abs(sr.y-tr.y)<1
     && Math.abs(sr.width-tr.width)<1 && Math.abs(sr.height-tr.height)<1){
    const off=30;
    return [
      {x:sr.x+sr.width, y:scy-10},{x:sr.x+sr.width+off, y:scy-10},
      {x:sr.x+sr.width+off, y:sr.y-off},{x:scx+10, y:sr.y-off},
      {x:scx+10, y:sr.y}
    ];
  }
  if(Math.abs(dx)>=Math.abs(dy)){
    let ex,en;
    if(dx>=0){ex=sr.x+sr.width;en=tr.x}else{ex=sr.x;en=tr.x+tr.width}
    let mx=(ex+en)/2;
    if((dx>=0&&ex>=en)||(dx<0&&ex<=en)) mx=ex+(dx>=0?25:-25);
    return [{x:ex,y:scy},{x:mx,y:scy},{x:mx,y:tcy},{x:en,y:tcy}];
  } else {
    let ey,ee;
    if(dy>=0){ey=sr.y+sr.height;ee=tr.y}else{ey=sr.y;ee=tr.y+tr.height}
    let my=(ey+ee)/2;
    if((dy>=0&&ey>=ee)||(dy<0&&ey<=ee)) my=ey+(dy>=0?25:-25);
    return [{x:scx,y:ey},{x:scx,y:my},{x:tcx,y:my},{x:tcx,y:ee}];
  }
}

// ─── Перемещение классов (drag) ─────────────────────────────────────────

let dragTarget=null, dragStart={x:0,y:0}, dragOrig=[0,0];

svg.addEventListener('pointerdown', e => {
    if(e.button !== 0) return;
    const g = e.target.closest && e.target.closest('.uml-class');
    if(!g) return;
    e.stopPropagation();
    e.preventDefault();
    dragTarget = g;
    dragStart = { x: e.clientX, y: e.clientY };
    dragOrig = getTranslate(g);
    g.style.cursor = 'grabbing';
});

svg.addEventListener('pointermove', e => {
    if(!dragTarget) return;
    const dx = e.clientX - dragStart.x;
    const dy = e.clientY - dragStart.y;
    setTranslate(dragTarget, dragOrig[0] + dx, dragOrig[1] + dy);
    updateAllEdges();
});

svg.addEventListener('pointerup', e => {
    if(dragTarget){
        dragTarget.style.cursor = 'grab';
        dragTarget = null;
    }
});

svg.addEventListener('pointercancel', e => {
    if(dragTarget){ dragTarget = null; }
});

// ─── Оптимальное соединение рёбер (как в Python) ─────────────────────

function getEdgeMidpoints(r){
  const cx=r.x+r.width/2, cy=r.y+r.height/2;
  return {
    top:    {x:cx, y:r.y},
    bottom: {x:cx, y:r.y+r.height},
    left:   {x:r.x, y:cy},
    right:  {x:r.x+r.width, y:cy}
  };
}

function lineCrossesRectInterior(x1,y1,x2,y2,r){
  function inside(px,py){ return px>r.x && px<r.x+r.width && py>r.y && py<r.y+r.height; }
  if(inside(x1,y1)||inside(x2,y2)) return true;
  const mx=(x1+x2)/2, my=(y1+y2)/2;
  return inside(mx,my);
}

function findBestEdgeConnection(r1,r2){
  const e1=getEdgeMidpoints(r1), e2=getEdgeMidpoints(r2);
  const sides=['top','bottom','left','right'];
  let best=null, minD=Infinity;
  for(const s1 of sides){
    for(const s2 of sides){
      const p1=e1[s1], p2=e2[s2];
      if(lineCrossesRectInterior(p1.x,p1.y,p2.x,p2.y,r1)) continue;
      if(lineCrossesRectInterior(p1.x,p1.y,p2.x,p2.y,r2)) continue;
      const d=(p1.x-p2.x)**2+(p1.y-p2.y)**2;
      if(d<minD){ minD=d; best={p1,p2,side1:s1,side2:s2}; }
    }
  }
  if(!best){
    const c1x=r1.x+r1.width/2, c1y=r1.y+r1.height/2;
    const c2x=r2.x+r2.width/2, c2y=r2.y+r2.height/2;
    best={p1:{x:c1x,y:c1y}, p2:{x:c2x,y:c2y}, side1:'center', side2:'center'};
  }
  return best;
}

function buildOrthogonalPath(p1,side1,p2,side2,startOffset=0,endOffset=0){
  // Для правильной ориентации маркера добавляем короткие перпендикулярные сегменты
  let startSegment=null;
  let endSegment=null;
  
  if(startOffset>0){
    // Добавляем сегмент наружу от первой точки
    if(side1==='left'){
      startSegment={x:p1.x-startOffset, y:p1.y};
    }else if(side1==='right'){
      startSegment={x:p1.x+startOffset, y:p1.y};
    }else if(side1==='top'){
      startSegment={x:p1.x, y:p1.y-startOffset};
    }else if(side1==='bottom'){
      startSegment={x:p1.x, y:p1.y+startOffset};
    }
  }
  
  if(endOffset>0){
    // Добавляем сегмент наружу от второй точки
    if(side2==='left'){
      endSegment={x:p2.x-endOffset, y:p2.y};
    }else if(side2==='right'){
      endSegment={x:p2.x+endOffset, y:p2.y};
    }else if(side2==='top'){
      endSegment={x:p2.x, y:p2.y-endOffset};
    }else if(side2==='bottom'){
      endSegment={x:p2.x, y:p2.y+endOffset};
    }
  }
  
  // Строим основной путь между исходными точками
  const tolerance=5;
  const isVertical=Math.abs(p1.x-p2.x)<tolerance;
  const isHorizontal=Math.abs(p1.y-p2.y)<tolerance;
  
  let path;
  
  // Прямая линия если выровнены (0 изгибов)
  if(isVertical||isHorizontal){
    path=[p1,p2];
  } else {
    // Определяем ориентацию сторон
    const s1Vert=(side1==='left'||side1==='right');
    const s2Vert=(side2==='left'||side2==='right');
    
    // L-образный путь (1 изгиб) - предпочтительнее
    if(s1Vert && !s2Vert){
      path=[p1, {x:p1.x,y:p2.y}, p2];
    } else if(!s1Vert && s2Vert){
      path=[p1, {x:p2.x,y:p1.y}, p2];
    } 
    // Z-образный путь (2 изгиба)
    else if(s1Vert && s2Vert){
      const midX=(p1.x+p2.x)/2;
      path=[p1, {x:midX,y:p1.y}, {x:midX,y:p2.y}, p2];
    } else {
      const midY=(p1.y+p2.y)/2;
      path=[p1, {x:p1.x,y:midY}, {x:p2.x,y:midY}, p2];
    }
  }
  
  // Добавляем перпендикулярные сегменты
  if(startSegment){
    path=[startSegment].concat(path);
  }
  if(endSegment){
    // Для marker-end: путь идет от p2 к endSegment, маркер на endSegment ориентирован НАРУЖУ
    // Путь: ... -> p2 (на ребре) -> endSegment (снаружи, маркер здесь)
    path=path.concat([endSegment]);
  }
  
  return path;
}

// ─── Данные рёбер ─────────────────────────────────────────────────────

const edges = [];

function initEdges(){
  svg.querySelectorAll(".uml-edge[data-src][data-tgt]").forEach(g=>{
    const pl = g.querySelector("polyline, line");
    if(!pl) return;
    edges.push({
      group: g,
      polyline: pl,
      srcId: g.dataset.src,
      tgtId: g.dataset.tgt,
    });
  });
}

function updateAllEdges(){
  edges.forEach(edge=>{
    const sr = getClassRect(edge.srcId);
    const tr = getClassRect(edge.tgtId);
    if(!sr||!tr) return;

    const conn=findBestEdgeConnection(sr,tr);
    
    // Определяем offset для маркеров
    const markerStart=edge.polyline.getAttribute('marker-start');
    const markerEnd=edge.polyline.getAttribute('marker-end');
    const isDependency=edge.polyline.classList.contains('uml-dep');
    
    let startOffset=0;
    let endOffset=0;
    
    if(markerStart || markerEnd){
      endOffset=12;
      // Для dependency добавляем отступ и в начале
      if(isDependency){
        startOffset=12;
      }
    }
    
    const pts = buildOrthogonalPath(conn.p1, conn.side1, conn.p2, conn.side2, startOffset, endOffset);
    const mid_x = (pts[0].x + pts[pts.length-1].x) / 2;
    const mid_y = (pts[0].y + pts[pts.length-1].y) / 2;
    
    edge.polyline.setAttribute("points", pts.map(p=>`${p.x},${p.y}`).join(" "));
    updateLabels(edge, mid_x, mid_y);
  });
}

function updateLabels(edge, mid_x, mid_y){
  edge.group.querySelectorAll("[data-near], text.uml-dep-label").forEach(el=>{
    if(el.tagName.toLowerCase()==='text'){
      el.setAttribute("x", mid_x.toFixed(1));
      el.setAttribute("y", mid_y.toFixed(1));
    } else if(el.tagName.toLowerCase()==='foreignObject' && el.hasAttribute('data-near')){
      const base_x = mid_x;
      const base_y = mid_y;
      const ox = Math.max(0, parseFloat(el.dataset.offx||"8"));
      const oy = Math.min(0, parseFloat(el.dataset.offy||"-8"));
      const w = parseFloat(el.getAttribute('width') || '120');
      const h = parseFloat(el.getAttribute('height') || '24');
      const x = base_x + ox;
      const y = base_y + oy - h;
      el.setAttribute('x', x.toFixed(1));
      el.setAttribute('y', y.toFixed(1));
    }
  });
}

// ─── Экспорт и сохранение ─────────────────────────────────────────────

const originalTransforms = new Map();
svg.querySelectorAll('.uml-class').forEach(g => {
    originalTransforms.set(g.dataset.id, g.getAttribute('transform') || 'translate(0,0)');
});

function exportSVG() {
    const clone = svg.cloneNode(true);
    
    // Удаляем toolbar и скрипты
    const toolbar = clone.querySelector('#toolbar');
    if(toolbar) toolbar.remove();
    const scripts = clone.querySelectorAll('script');
    scripts.forEach(s => s.remove());
    const styles = clone.querySelectorAll('style');
    styles.forEach(s => s.remove());
    
    // Обновляем transform с округлением
    clone.querySelectorAll('.uml-class').forEach((g, idx) => {
        const original = svg.querySelectorAll('.uml-class')[idx];
        const [x, y] = getTranslate(original);
        g.setAttribute('transform', `translate(${Math.round(x)},${Math.round(y)})`);
    });
    
    // Удаляем служебные атрибуты
    clone.querySelectorAll('.uml-edge').forEach(edge => {
        edge.removeAttribute('data-src');
        edge.removeAttribute('data-tgt');
    });
    
    const serializer = new XMLSerializer();
    let svgString = serializer.serializeToString(clone);
    
    if (!svgString.startsWith('<?xml')) {
        svgString = '<?xml version="1.0" encoding="UTF-8"?>\\n' + svgString;
    }
    
    return svgString;
}

function downloadSVG() {
    const svgData = exportSVG();
    const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElementNS('http://www.w3.org/1999/xhtml', 'a');
    a.href = url;
    a.download = 'diagram_updated.svg';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showStatus('✓ SVG скачан');
}

function copySVG() {
    const svgData = exportSVG();
    navigator.clipboard.writeText(svgData).then(() => {
        showStatus('✓ SVG скопирован');
    }).catch(err => {
        showStatus('✗ Ошибка: ' + err.message);
    });
}

function resetPositions() {
    svg.querySelectorAll('.uml-class').forEach(g => {
        const id = g.dataset.id;
        const orig = originalTransforms.get(id);
        if (orig) g.setAttribute('transform', orig);
    });
    updateAllEdges();
    showStatus('✓ Сброшено');
}

function showStatus(msg) {
    const status = svg.querySelector('#status-text');
    if(!status) return;
    status.textContent = msg;
    setTimeout(() => { status.textContent = ''; }, 3000);
}

// ─── Привязка кнопок ──────────────────────────────────────────────────

svg.querySelector('#btn-export')?.addEventListener('click', downloadSVG);
svg.querySelector('#btn-copy')?.addEventListener('click', copySVG);
svg.querySelector('#btn-reset')?.addEventListener('click', resetPositions);

// ─── Инициализация ─────────────────────────────────────────────────────

initEdges();
updateAllEdges();

})();
]]>
</script>"""

    def _render_association_svg(
        self, assoc: Association, positions: Dict[str, ClassPosition],
    ) -> str:
        """Рендерит бинарную ассоциацию как SVG polyline с ортогональной маршрутизацией."""
        if not assoc.is_binary():
            return self._render_nary_association_svg(assoc, positions)

        e0 = assoc.ends[0]
        e1 = assoc.ends[1]
        p0 = positions.get(e0.participant.name)
        p1 = positions.get(e1.participant.name)
        if not p0 or not p1:
            return ""

        esc = html_mod.escape

        # Сначала определяем маркеры
        marker_start = ""
        marker_end = ""

        # Агрегация / Композиция (учитываем также специализированные AggregationEnd)
        for i, end in enumerate([e0, e1]):
            agg_kind = getattr(end, "aggregation", AggregationKind.NONE)
            if agg_kind == AggregationKind.AGGREGATION:
                if i == 0:
                    marker_start = ' marker-start="url(#diamond-agg)"'
                else:
                    marker_end = ' marker-end="url(#diamond-agg)"'
            elif agg_kind == AggregationKind.COMPOSITION:
                if i == 0:
                    marker_start = ' marker-start="url(#diamond-comp)"'
                else:
                    marker_end = ' marker-end="url(#diamond-comp)"'

        # Навигация
        for i, end in enumerate([e0, e1]):
            if end.navigable is True:
                if i == 0:
                    marker_start = marker_start or ' marker-start="url(#arrow-nav)"'
                else:
                    marker_end = marker_end or ' marker-end="url(#arrow-nav)"'
            elif end.navigable is False:
                if i == 0:
                    marker_start = marker_start or ' marker-start="url(#cross-x)"'
                else:
                    marker_end = marker_end or ' marker-end="url(#cross-x)"'

        # Find optimal edge connection and build orthogonal path
        (p1_point, p1_side, p2_point, p2_side) = _find_best_edge_connection(
            p0.x, p0.y, p0.width, p0.height,
            p1.x, p1.y, p1.width, p1.height
        )
        # Add perpendicular segment for markers if present (12px to account for marker size)
        end_offset = 12.0 if (marker_start or marker_end) else 0.0
        pts = _build_orthogonal_path(p1_point, p1_side, p2_point, p2_side, end_offset=end_offset)
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

        parts: list[str] = []
        # Формируем data-атрибуты для ассоциации
        assoc_data = [
            f'data-src="{esc(e0.participant.name)}"',
            f'data-tgt="{esc(e1.participant.name)}"',
            f'data-type="association"',
            f'data-name="{esc(assoc.name) if assoc.name else ""}"',
            f'data-derived="{str(assoc.is_derived).lower()}"',
            f'data-src-multiplicity="{str(e0.multiplicity) if e0.multiplicity else ""}"',
            f'data-tgt-multiplicity="{str(e1.multiplicity) if e1.multiplicity else ""}"',
            f'data-src-role="{esc(e0.role) if e0.role else ""}"',
            f'data-tgt-role="{esc(e1.role) if e1.role else ""}"',
            f'data-src-navigable="{str(e0.navigable).lower() if e0.navigable is not None else "none"}"',
            f'data-tgt-navigable="{str(e1.navigable).lower() if e1.navigable is not None else "none"}"',
            f'data-src-aggregation="{e0.aggregation.value}"',
            f'data-tgt-aggregation="{e1.aggregation.value}"',
        ]

        parts.append(f'<g class="uml-edge" {" ".join(assoc_data)}>')

        # Polyline
        parts.append(
            f'<polyline points="{pts_str}" fill="none" '
            f'stroke="black" stroke-width="1.5"'
            f'{marker_start}{marker_end}/>'
        )

        # Имя ассоциации — всегда сверху справа от маршрута (top-right)
        if assoc.name:
            mi = len(pts) // 2
            mx, my = pts[mi]
            prefix = "/" if assoc.is_derived else ""
            # label as a resizable foreignObject positioned top-right
            lab_w = 140
            lab_h = 24
            lx = mx + 8
            ly = my - lab_h - 8
            parts.append(
                f'<foreignObject class="edge-fo" data-near="mid" data-offx="8" data-offy="-8" '
                f'x="{lx:.1f}" y="{ly:.1f}" width="{lab_w}" height="{lab_h}">'
                f'<div xmlns="http://www.w3.org/1999/xhtml" class="label-box">{esc(prefix + assoc.name)}</div>'
                f'<div xmlns="http://www.w3.org/1999/xhtml" class="label-resize"/></foreignObject>'
            )

        # Кратности и роли на полюсах
        for i, (end, pt) in enumerate([
            (e0, pts[0]),
            (e1, pts[-1]),
        ]):
            near = "src" if i == 0 else "tgt"
            px, py_label = pt
            # Определяю направление первого/последнего сегмента
            if i == 0 and len(pts) > 1:
                seg_dx = pts[1][0] - pts[0][0]
                seg_dy = pts[1][1] - pts[0][1]
            elif i == 1 and len(pts) > 1:
                seg_dx = pts[-1][0] - pts[-2][0]
                seg_dy = pts[-1][1] - pts[-2][1]
            else:
                seg_dx, seg_dy = 1, 0

            label_parts: list[str] = []
            if end.multiplicity:
                label_parts.append(str(end.multiplicity))
            if end.role:
                prefix2 = "/" if end.is_derived else ""
                vis = end.role_visibility.value if end.role_visibility else ""
                label_parts.append(f"{vis}{prefix2}{end.role}")
            if end.collection_kind.value != "set":
                label_parts.append(f"{{{end.collection_kind.value}}}")
            if end.changeability:
                label_parts.append(f"{{{end.changeability.value}}}")
            if end.subsets:
                target = end.subsets
                name = getattr(target, "role", None) or getattr(getattr(target, "participant", None), "name", str(target))
                label_parts.append(f"{{subsets {name}}}")
            if end.is_union:
                label_parts.append("{union}")
            if end.redefines:
                label_parts.append(f"{{redefines {end.redefines}}}")

            if label_parts:
                # Смещение перпендикулярно сегменту
                if abs(seg_dx) >= abs(seg_dy):  # горизонтальный сегмент
                    off_x = 4 if seg_dx >= 0 else -4
                    off_y = -12
                else:  # вертикальный сегмент
                    off_x = 8
                    off_y = 4 if seg_dy >= 0 else -4
                # label near segment end — use foreignObject for wrapping/resizing
                lab_text = esc(" ".join(label_parts))
                lab_w = 140
                lab_h = 24
                lx = px + off_x - lab_w / 2
                ly = py_label + off_y - lab_h / 2
                parts.append(
                    f'<foreignObject class="edge-fo" data-near="{near}" data-offx="{off_x}" data-offy="{off_y}" '
                    f'x="{lx:.1f}" y="{ly:.1f}" width="{lab_w}" height="{lab_h}">'
                    f'<div xmlns="http://www.w3.org/1999/xhtml" class="label-box">{lab_text}</div>'
                    f'<div xmlns="http://www.w3.org/1999/xhtml" class="label-resize"/></foreignObject>'
                )

            # Квалификатор
            if end.qualifiers:
                qw = 60
                qh = 14 * len(end.qualifiers) + 4
                qx = px - qw / 2
                qy = py_label - qh / 2
                parts.append(
                    f'<rect x="{qx:.1f}" y="{qy:.1f}" width="{qw}" '
                    f'height="{qh}" fill="white" stroke="black" '
                    f'stroke-width="1"/>'
                )
                for qi, qa in enumerate(end.qualifiers):
                    parts.append(
                        f'<text x="{qx + 3:.1f}" '
                        f'y="{qy + 12 + qi * 14:.1f}" '
                        f'font-family="{SVG_FONT_FAMILY}" font-size="9" '
                        f'fill="black">{esc(qa.to_text())}</text>'
                    )

        parts.append("</g>")
        return "\n".join(parts)

    def _render_nary_association_svg(
        self, assoc: Association, positions: Dict[str, ClassPosition],
    ) -> str:
        """Рендерит n-арную ассоциацию через ромб (§3.3.6)."""
        esc = html_mod.escape
        # Вычисляем центр — среднее позиций всех участников
        xs: list[float] = []
        ys: list[float] = []
        for end in assoc.ends:
            p = positions.get(end.participant.name)
            if p:
                xs.append(p.x + p.width / 2)
                ys.append(p.y + p.height / 2)
        if not xs:
            return ""
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        ds = 16  # половина ромба

        # Формируем data-атрибуты для n-арной ассоциации
        nary_data = [
            f'data-type="nary-association"',
            f'data-name="{esc(assoc.name) if assoc.name else ""}"',
            f'data-derived="{str(assoc.is_derived).lower()}"',
            f'data-arity="{len(assoc.ends)}"',
        ]

        # Добавляем список участников через data-participants
        participants = ",".join(end.participant.name for end in assoc.ends if end.participant)
        nary_data.append(f'data-participants="{esc(participants)}"')

        parts: list[str] = [f'<g class="uml-assoc-nary" {" ".join(nary_data)}>']
        # Ромб
        parts.append(
            f'<polygon points="{cx},{cy - ds} {cx + ds},{cy} '
            f'{cx},{cy + ds} {cx - ds},{cy}" '
            f'fill="white" stroke="black" stroke-width="1.5"/>'
        )
        if assoc.name:
            parts.append(
                f'<text x="{cx}" y="{cy - ds - 4}" text-anchor="middle" '
                f'font-family="{SVG_FONT_FAMILY}" font-size="{SVG_FONT_SIZE}" '
                f'fill="black">{esc(assoc.name)}</text>'
            )
        # Линии к каждому классификатору
        for end in assoc.ends:
            p = positions.get(end.participant.name)
            if not p:
                continue
            ex, ey = _find_intersection_point(
                p.x, p.y, p.width, p.height, cx, cy,
            )
            parts.append(
                f'<line x1="{cx:.1f}" y1="{cy:.1f}" '
                f'x2="{ex:.1f}" y2="{ey:.1f}" '
                f'stroke="black" stroke-width="1.5"/>'
            )
        parts.append("</g>")
        return "\n".join(parts)

    def _render_generalization_svg(
        self, gen: Generalization, positions: Dict[str, ClassPosition],
    ) -> str:
        """Рендерит обобщение — ортогональная ломаная с пустым треугольником."""
        p_spec = positions.get(gen.specific.name)
        p_gen = positions.get(gen.general.name)
        if not p_spec or not p_gen:
            return ""
        esc = html_mod.escape
        
        # Find optimal edge connection and build orthogonal path
        # Path goes from general to specific, marker-end at specific points back to general
        (p1_point, p1_side, p2_point, p2_side) = _find_best_edge_connection(
            p_gen.x, p_gen.y, p_gen.width, p_gen.height,
            p_spec.x, p_spec.y, p_spec.width, p_spec.height
        )
        # No additional offset - marker is positioned at the edge of the rectangle
        pts = _build_orthogonal_path(p1_point, p1_side, p2_point, p2_side, end_offset=0.0)
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        # Формируем data-атрибуты для обобщения
        gen_data = [
            f'data-src="{esc(gen.specific.name)}"',
            f'data-tgt="{esc(gen.general.name)}"',
            f'data-type="generalization"',
            f'data-substitutable="{str(gen.is_substitutable).lower()}"',
        ]

        return f'<g class="uml-edge" {" ".join(gen_data)}>' + \
            f'<polyline points="{pts_str}" fill="none" ' + \
            f'stroke="black" stroke-width="1.5" marker-end="url(#arrow-gen)"/>' + \
            f'</g>'

    def _render_dependency_svg(
        self, dep: Dependency, positions: Dict[str, ClassPosition],
    ) -> str:
        """Рендерит зависимость — пунктирная стрелка от supplier к client.
        
        Алгоритм: всегда использует оптимальное соединение рёбер.
        Строит ортогональный путь между найденными точками подключения.
        """
        esc = html_mod.escape
        p_client = positions.get(dep.client.name)
        p_supplier = positions.get(dep.supplier.name)
        if not p_client or not p_supplier:
            return ""

        # Find optimal edge connection and build orthogonal path
        (p1_point, p1_side, p2_point, p2_side) = _find_best_edge_connection(
            p_client.x, p_client.y, p_client.width, p_client.height,
            p_supplier.x, p_supplier.y, p_supplier.width, p_supplier.height
        )
        # Add perpendicular segments on both ends (12px to account for marker size)
        pts = _build_orthogonal_path(p1_point, p1_side, p2_point, p2_side, start_offset=12.0, end_offset=12.0)
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        mid_x = (pts[0][0] + pts[-1][0]) / 2
        mid_y = (pts[0][1] + pts[-1][1]) / 2

        parts: list[str] = []
        # Формируем data-атрибуты для зависимости
        dep_data = [
            f'data-src="{esc(dep.client.name)}"',
            f'data-tgt="{esc(dep.supplier.name)}"',
            f'data-type="dependency"',
            f'data-stereotype="{dep.stereotype.value if dep.stereotype else ""}"',
        ]

        parts.append(f'<g class="uml-edge" {" ".join(dep_data)}>')
        
        parts.append(
            f'<polyline points="{pts_str}" fill="none" '
            f'stroke="black" stroke-linecap="round" stroke-linejoin="round" '
            f'stroke-width="1" stroke-dasharray="8,5" '
            f'marker-end="url(#arrow-dep)" class="uml-dep"/>'
        )

        # Stereotype label as SVG text (matching original format)
        if dep.stereotype:
            # Format stereotype value: instanceOf -> instance Of
            stereo_text = dep.stereotype.value
            import re
            stereo_formatted = re.sub(r'([a-z])([A-Z])', r'\1 \2', stereo_text)
            parts.append(
                f'<text x="{mid_x:.1f}" y="{mid_y:.1f}" '
                f'fill="black" font-family="Arial" font-size="11" font-weight="500" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'class="uml-dep-label">«{esc(stereo_formatted)}»</text>'
            )

        parts.append("</g>")
        return "\n".join(parts)

    def _render_realization_svg(
        self, real: Realization, positions: Dict[str, ClassPosition],
    ) -> str:
        """Рендерит реализацию — пунктирная ортогональная ломаная с пустым треугольником."""
        esc = html_mod.escape
        p_impl = positions.get(real.implementing_classifier)
        p_intf = positions.get(real.interface)
        if not p_impl or not p_intf:
            return ""
        
        # Find optimal edge connection and build orthogonal path
        # Path goes from interface to implementer, marker-end at implementer points back to interface
        (p1_point, p1_side, p2_point, p2_side) = _find_best_edge_connection(
            p_intf.x, p_intf.y, p_intf.width, p_intf.height,
            p_impl.x, p_impl.y, p_impl.width, p_impl.height
        )
        # No additional offset - marker is positioned at the edge of the rectangle
        pts = _build_orthogonal_path(p1_point, p1_side, p2_point, p2_side, end_offset=0.0)
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        
        real_data = [
            f'data-src="{esc(real.implementing_classifier)}"',
            f'data-tgt="{esc(real.interface)}"',
            f'data-type="realization"',
        ]
        
        return f'<g class="uml-edge" {" ".join(real_data)}>' + \
            f'<polyline points="{pts_str}" fill="none" ' + \
            f'stroke="black" stroke-width="1.5" stroke-dasharray="10,5" ' + \
            f'marker-end="url(#arrow-real)"/>' + \
            f'</g>'

    def _render_gen_set_svg(
        self, gs: GeneralizationSet, positions: Dict[str, ClassPosition],
    ) -> str:
        """Рендерит набор обобщений с общей стрелкой и ограничениями."""
        if not gs.generalizations:
            return ""
        esc = html_mod.escape
        # Все подклассы + общий суперкласс (все gen.general одинаковые)
        general_name = gs.generalizations[0].general.name
        p_gen = positions.get(general_name)
        if not p_gen:
            return ""

        parts: list[str] = ['<g class="uml-genset">']
        for g in gs.generalizations:
            svg = self._render_generalization_svg(g, positions)
            if svg:
                parts.append(svg)

        # Метка ограничения
        label = gs.constraint_label()
        if gs.name:
            label = f"{gs.name.name}: {label}"
        # Размещаем метку у суперкласса
        lx = p_gen.x + p_gen.width + 8
        ly = p_gen.y + p_gen.height + 18
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" '
            f'font-family="{SVG_FONT_FAMILY}" font-size="10" '
            f'fill="gray">{esc(label)}</text>'
        )
        parts.append("</g>")
        return "\n".join(parts)

    def to_svg(
        self,
        width: int = 1400,
        height: int = 900,
        interactive: bool = True,
    ) -> str:
        """Полный рендеринг диаграммы в SVG.
        
        Args:
            width: ширина SVG
            height: высота SVG  
            interactive: если True, встраивает JavaScript для drag&drop и экспорта
        """
        if not self.positions:
            self.auto_layout()

        pos = self.positions
        parts: list[str] = []
        parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{width}" height="{height}">'
        )
        
        if interactive:
            parts.append(self._svg_styles())
        
        parts.append(self._svg_defs())

        # Рисуем отношения (под классами)
        for assoc in self.associations:
            parts.append(self._render_association_svg(assoc, pos))
        for assoc in self.association_classes:
            parts.append(self._render_association_svg(assoc, pos))
        for gen in self.generalizations:
            parts.append(self._render_generalization_svg(gen, pos))
        for gs in self.generalization_sets:
            parts.append(self._render_gen_set_svg(gs, pos))
        for dep in self.dependencies:
            parts.append(self._render_dependency_svg(dep, pos))
        for real in self.realizations:
            parts.append(self._render_realization_svg(real, pos))

        # Collect instance names (clients in INSTANCE_OF dependencies)
        instance_names = set()
        for dep in self.dependencies:
            if dep.stereotype and dep.stereotype.value == "instanceOf":
                instance_names.add(dep.client.name)
        
        # Рисуем классификаторы (поверх)
        for cls_name, cls in self.classifiers.items():
            pcls = pos.get(cls_name)
            x = pcls.x if pcls else 0.0
            y = pcls.y if pcls else 0.0
            is_instance = cls_name in instance_names
            parts.append(cls.to_svg(x, y, class_id=cls_name, is_instance=is_instance))

        if interactive:
            parts.append(self._svg_toolbar(width))
            parts.append(self._svg_script())
        
        parts.append("</svg>")
        return "\n".join(parts)

    def to_html(self, width: int = 1400, height: int = 900) -> str:
        """Полный рендеринг в интерактивную HTML страницу.

        Поддерживает:
        - Перемещение классов мышкой (drag & drop)
        - Ломаные стрелки с прямыми углами (двойной клик → добавить точку изгиба)
        - Перемещение конца стрелки по прямоугольнику класса
        - Перемещение точек изгиба стрелок
        """
        svg_content = self.to_svg(width, height)
        return INTERACTIVE_HTML_TEMPLATE.replace("%%SVG%%", svg_content)


# ═══════════════════════════════════════════════════════════════════════════
# Интерактивный HTML шаблон с JavaScript для drag-and-drop
# ═══════════════════════════════════════════════════════════════════════════

INTERACTIVE_HTML_TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>UML Class Diagram — Interactive Viewer</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Arial,sans-serif;background:#e8e8e8;overflow:hidden;display:flex;flex-direction:column}
#toolbar{background:#333;color:#fff;padding:8px 12px;display:flex;gap:10px;align-items:center;box-shadow:0 2px 4px rgba(0,0,0,0.2)}
#toolbar button{background:#555;color:#fff;border:none;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:13px;font-family:Arial,sans-serif}
#toolbar button:hover{background:#777}
#toolbar button:active{background:#999}
#toolbar .separator{width:1px;height:20px;background:#666;margin:0 4px}
#canvas-wrap{flex:1;overflow:auto;position:relative}
svg{background:#f6f6f6;cursor:default}
.uml-class{cursor:grab}
.uml-class:active{cursor:grabbing}
.uml-edge polyline{cursor:pointer}
.uml-edge:hover polyline{stroke-width:2.5}
/* label box and resize handle for foreignObject labels */
.label-box{position:relative; font-family:Arial, sans-serif; font-size:10px; padding:4px; background:transparent; color:black; word-wrap:break-word}
.label-resize{position:absolute; right:0; top:0; width:8px; height:100%; cursor:e-resize}
#status{color:#aaa;font-size:12px;margin-left:auto}
</style>
</head>
<body>
<div id="toolbar">
  <button id="btn-export-svg" title="Скачать SVG с текущими позициями">💾 Экспорт SVG</button>
  <button id="btn-copy-svg" title="Копировать SVG в буфер обмена">📋 Копировать SVG</button>
  <div class="separator"></div>
  <button id="btn-reset" title="Вернуть исходные позиции">↺ Сброс</button>
  <span id="status"></span>
</div>
<div id="canvas-wrap">
%%SVG%%
</div>
<script>
(function(){
"use strict";

const svg = document.querySelector("svg");

// ─── Утилиты ────────────────────────────────────────────────────────────

function getTranslate(el){
  const t = el.getAttribute("transform")||"";
  const m = /translate\(\s*([^,\s]+)[,\s]+([^)]+)\)/.exec(t);
  return m ? [parseFloat(m[1]),parseFloat(m[2])] : [0,0];
}
function setTranslate(el,x,y){
  el.setAttribute("transform",`translate(${x},${y})`);
}
function getBBox(el){
  const bb = el.querySelector(".uml-bbox");
  if(bb) return {
    x: parseFloat(bb.getAttribute("x")),
    y: parseFloat(bb.getAttribute("y")),
    width: parseFloat(bb.getAttribute("width")),
    height: parseFloat(bb.getAttribute("height"))
  };
  return el.getBBox();
}

// ─── Получить прямоугольник класса ──────────────────────────────────────

function getClassRect(id){
  const g = svg.querySelector(`.uml-class[data-id="${id}"]`);
  if(!g) return null;
  const [tx,ty] = getTranslate(g);
  const bb = getBBox(g);
  return {x:tx+bb.x, y:ty+bb.y, width:bb.width, height:bb.height};
}

// ─── Ортогональная маршрутизация ────────────────────────────────────────

function orthoRoute(sr, tr){
  const scx=sr.x+sr.width/2, scy=sr.y+sr.height/2;
  const tcx=tr.x+tr.width/2, tcy=tr.y+tr.height/2;
  const dx=tcx-scx, dy=tcy-scy;
  // Самоассоциация
  if(Math.abs(sr.x-tr.x)<1 && Math.abs(sr.y-tr.y)<1
     && Math.abs(sr.width-tr.width)<1 && Math.abs(sr.height-tr.height)<1){
    const off=30;
    return [
      {x:sr.x+sr.width, y:scy-10},{x:sr.x+sr.width+off, y:scy-10},
      {x:sr.x+sr.width+off, y:sr.y-off},{x:scx+10, y:sr.y-off},
      {x:scx+10, y:sr.y}
    ];
  }
  if(Math.abs(dx)>=Math.abs(dy)){
    let ex,en;
    if(dx>=0){ex=sr.x+sr.width;en=tr.x}else{ex=sr.x;en=tr.x+tr.width}
    let mx=(ex+en)/2;
    if((dx>=0&&ex>=en)||(dx<0&&ex<=en)) mx=ex+(dx>=0?25:-25);
    return [{x:ex,y:scy},{x:mx,y:scy},{x:mx,y:tcy},{x:en,y:tcy}];
  } else {
    let ey,ee;
    if(dy>=0){ey=sr.y+sr.height;ee=tr.y}else{ey=sr.y;ee=tr.y+tr.height}
    let my=(ey+ee)/2;
    if((dy>=0&&ey>=ee)||(dy<0&&ey<=ee)) my=ey+(dy>=0?25:-25);
    return [{x:scx,y:ey},{x:scx,y:my},{x:tcx,y:my},{x:tcx,y:ee}];
  }
}

// ─── Оптимальный выбор точек соединения ──────────────────────────────────

function getEdgeMidpoints(r){
  const cx = r.x + r.width/2, cy = r.y + r.height/2;
  return {
    top: {x: cx, y: r.y},
    bottom: {x: cx, y: r.y + r.height},
    left: {x: r.x, y: cy},
    right: {x: r.x + r.width, y: cy}
  };
}

function lineCrossesRectInterior(x1, y1, x2, y2, r){
  // Проверяет, проходит ли отрезок через внутренность прямоугольника
  function pointInside(px, py){
    return r.x < px && px < r.x + r.width && r.y < py && py < r.y + r.height;
  }
  
  if(pointInside(x1, y1) || pointInside(x2, y2)) return true;
  
  // Проверяем среднюю точку
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  if(pointInside(mx, my)) return true;
  
  return false;
}

function findBestEdgeConnection(r1, r2){
  // Находит оптимальную пару середин сторон для соединения двух прямоугольников
  const edges1 = getEdgeMidpoints(r1);
  const edges2 = getEdgeMidpoints(r2);
  
  let bestPair = null;
  let minDist = Infinity;
  
  for(const [name1, p1] of Object.entries(edges1)){
    for(const [name2, p2] of Object.entries(edges2)){
      // Проверяем, не проходит ли отрезок через внутренность прямоугольников
      if(lineCrossesRectInterior(p1.x, p1.y, p2.x, p2.y, r1)) continue;
      if(lineCrossesRectInterior(p1.x, p1.y, p2.x, p2.y, r2)) continue;
      
      // Вычисляем расстояние
      const dist = (p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2;
      
      if(dist < minDist){
        minDist = dist;
        bestPair = {p1, p2};
      }
    }
  }
  
  // Если не нашли подходящую пару, берем центры
  if(!bestPair){
    const c1 = {x: r1.x + r1.width/2, y: r1.y + r1.height/2};
    const c2 = {x: r2.x + r2.width/2, y: r2.y + r2.height/2};
    bestPair = {p1: c1, p2: c2};
  }
  
  return bestPair;
}

// ─── Перемещение классов (drag) ─────────────────────────────────────────

let dragTarget=null, dragStart={x:0,y:0}, dragOrig=[0,0];

// Use event delegation so pointerdown on any child element inside
// a `.uml-class` group will still start a drag for that group.
svg.addEventListener('pointerdown', e => {
    if(e.button !== 0) return;
    const g = e.target.closest && e.target.closest('.uml-class');
    if(!g) return;
    e.stopPropagation();
    dragTarget = g;
    dragStart = { x: e.clientX, y: e.clientY };
    dragOrig = getTranslate(g);
    try { g.setPointerCapture(e.pointerId); } catch(_) {}
    g.style.cursor = 'grabbing';
});

svg.addEventListener('pointermove', e => {
    if(!dragTarget) return;
    const dx = e.clientX - dragStart.x;
    const dy = e.clientY - dragStart.y;
    setTranslate(dragTarget, dragOrig[0] + dx, dragOrig[1] + dy);
    updateAllEdges();
});

svg.addEventListener('pointerup', e => {
    if(dragTarget){
        try { dragTarget.releasePointerCapture && dragTarget.releasePointerCapture(e.pointerId); } catch(_) {}
        dragTarget.style.cursor = 'grab';
        dragTarget = null;
    }
});

svg.addEventListener('pointercancel', e => {
    if(dragTarget){ dragTarget = null; }
});

// ─── Данные рёбер ─────────────────────────────────────────────────────

const edges = [];

function initEdges(){
  svg.querySelectorAll(".uml-edge[data-src][data-tgt]").forEach(g=>{
    const pl = g.querySelector("polyline, line");
    if(!pl) return;
    edges.push({
      group: g,
      polyline: pl,
      srcId: g.dataset.src,
      tgtId: g.dataset.tgt,
    });
  });
}

// ─── Обновление позиций всех рёбер ─────────────────────────────────────

function updateAllEdges(){
  edges.forEach(edge=>{
    const sr = getClassRect(edge.srcId);
    const tr = getClassRect(edge.tgtId);
    if(!sr||!tr) return;

    // Find optimal edge connection points
    const {p1, p2} = findBestEdgeConnection(sr, tr);
    
    // Check if edge is a simple line or polyline
    const isLine = edge.polyline.tagName.toLowerCase() === 'line';
    
    let mid_x, mid_y;

    if(isLine){
      // Update simple line with optimal connection points
      edge.polyline.setAttribute('x1', p1.x.toFixed(1));
      edge.polyline.setAttribute('y1', p1.y.toFixed(1));
      edge.polyline.setAttribute('x2', p2.x.toFixed(1));
      edge.polyline.setAttribute('y2', p2.y.toFixed(1));
      mid_x = (p1.x + p2.x) / 2;
      mid_y = (p1.y + p2.y) / 2;
    } else {
      // Update polyline with orthogonal routing
      const pts = orthoRoute(sr, tr);
      // Use optimal connection points for endpoints
      if(pts.length >= 2){
        pts[0] = p1;
        pts[pts.length-1] = p2;
      }
      edge.polyline.setAttribute("points",
        pts.map(p=>`${p.x},${p.y}`).join(" "));
      mid_x = (pts[0].x + pts[pts.length-1].x) / 2;
      mid_y = (pts[0].y + pts[pts.length-1].y) / 2;
    }

    // Update text labels (support both <text> and foreignObject .edge-fo)
    edge.group.querySelectorAll("[data-near], text.uml-dep-label").forEach(el=>{
      if(el.tagName.toLowerCase()==='text'){
        el.setAttribute("x", mid_x.toFixed(1));
        el.setAttribute("y", mid_y.toFixed(1));
      } else if(el.tagName.toLowerCase()==='foreignObject' && el.hasAttribute('data-near')){
        const base_x = mid_x;
        const base_y = mid_y;
        const ox = Math.max(0, parseFloat(el.dataset.offx||"8"));
        const oy = Math.min(0, parseFloat(el.dataset.offy||"-8"));
        const w = parseFloat(el.getAttribute('width') || '120');
        const h = parseFloat(el.getAttribute('height') || '24');
        const x = base_x + ox;
        const y = base_y + oy - h;
        el.setAttribute('x', x.toFixed(1));
        el.setAttribute('y', y.toFixed(1));
      }
    });
  });
}

// ─── Инициализация ──────────────────────────────────────────────────────

initEdges();
updateAllEdges();

// ─── Инициализация ресайзеров для меток (drag to widen)
function initLabelResizers(){
    svg.querySelectorAll('foreignObject.edge-fo').forEach(fo=>{
        // inner element inside foreignObject
        const inner = fo.querySelector('.label-resize');
        if(!inner) return;
        inner.addEventListener('pointerdown', e=>{
            e.stopPropagation();
            e.preventDefault();
            const startX = e.clientX;
            const startW = parseFloat(fo.getAttribute('width')||'120');
            function onMove(ev){
                const nw = Math.max(40, startW + (ev.clientX - startX));
                fo.setAttribute('width', nw.toFixed(1));
                updateAllEdges();
            }
            function onUp(){ window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp); }
            window.addEventListener('pointermove', onMove);
            window.addEventListener('pointerup', onUp);
        });
    });
}

initLabelResizers();

// ─── Экспорт и сохранение SVG ──────────────────────────────────────────

// Сохраняем оригинальные позиции для сброса
const originalTransforms = new Map();
svg.querySelectorAll('.uml-class').forEach(g => {
    originalTransforms.set(g.dataset.id, g.getAttribute('transform') || 'translate(0,0)');
});

function exportSVG() {
    // Клонируем SVG
    const clone = svg.cloneNode(true);
    
    // Обновляем transform для всех классов на актуальные
    clone.querySelectorAll('.uml-class').forEach((g, idx) => {
        const original = svg.querySelectorAll('.uml-class')[idx];
        const [x, y] = getTranslate(original);
        g.setAttribute('transform', `translate(${Math.round(x)},${Math.round(y)})`);
    });
    
    // Удаляем временные классы и атрибуты для чистого SVG
    clone.querySelectorAll('.uml-edge').forEach(edge => {
        edge.removeAttribute('data-src');
        edge.removeAttribute('data-tgt');
    });
    
    // Сериализуем
    const serializer = new XMLSerializer();
    let svgString = serializer.serializeToString(clone);
    
    // Добавляем XML declaration если отсутствует
    if (!svgString.startsWith('<?xml')) {
        svgString = '<?xml version=\"1.0\" encoding=\"UTF-8\"?>\\n' + svgString;
    }
    
    return svgString;
}

function downloadSVG() {
    const svgData = exportSVG();
    const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'diagram_updated.svg';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    showStatus('✓ SVG скачан');
}

function copySVGToClipboard() {
    const svgData = exportSVG();
    navigator.clipboard.writeText(svgData).then(() => {
        showStatus('✓ SVG скопирован в буфер обмена');
    }).catch(err => {
        showStatus('✗ Ошибка копирования: ' + err.message);
    });
}

function resetPositions() {
    svg.querySelectorAll('.uml-class').forEach(g => {
        const id = g.dataset.id;
        const origTransform = originalTransforms.get(id);
        if (origTransform) {
            g.setAttribute('transform', origTransform);
        }
    });
    updateAllEdges();
    showStatus('✓ Позиции сброшены');
}

function showStatus(msg) {
    const status = document.getElementById('status');
    status.textContent = msg;
    setTimeout(() => { status.textContent = ''; }, 3000);
}

// Привязываем кнопки
document.getElementById('btn-export-svg').addEventListener('click', downloadSVG);
document.getElementById('btn-copy-svg').addEventListener('click', copySVGToClipboard);
document.getElementById('btn-reset').addEventListener('click', resetPositions);

})();
</script>
</body>
</html>"""
