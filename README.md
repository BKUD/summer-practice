# ontol_v3_students

Система для текстового описания, генерации, проверки и обратного восстановления UML-диаграмм классов.

## Возможности

- русскоязычный язык **TDL (Text Diagram Language)**;
- строгая UML-модель на **Pydantic v2**;
- генерация **DOT** и автоматический рендеринг через **Graphviz**;
- SVG с семантическими `data-*` атрибутами;
- обратный разбор **SVG → Pydantic**;
- сериализация **Pydantic → TDL**;
- семантическая валидация диаграмм;
- команды размещения элементов;
- поддержка legacy SVG;
- CLI и веб-интерфейс на **Streamlit**;
- экспорт в SVG, PNG и JPG.

Полное описание архитектуры и модулей находится в [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md).

---

## Архитектура

```text
TDL
→ Lexer
→ Parser
→ AST
→ Pydantic
→ DOT
→ Graphviz
→ SVG с data-атрибутами
→ Pydantic
→ TDL
```

Основные модули:

- `uml_dsl/models.py` — UML-классы, атрибуты, операции и параметры;
- `uml_dsl/relationships.py` — ассоциации, зависимости, обобщения и реализации;
- `uml_dsl/diagram.py` — контейнер диаграммы и семантическая валидация;
- `uml_dsl/tdl_lexer.py` — лексический анализ TDL;
- `uml_dsl/tdl_parser.py` — синтаксический анализ TDL;
- `uml_dsl/tdl_ast.py` — абстрактное синтаксическое дерево;
- `uml_dsl/tdl_build.py` — построение Pydantic-модели;
- `uml_dsl/graphviz_render.py` — генерация DOT и SVG;
- `uml_dsl/svg_metadata.py` — версия и ключи SVG-метаданных;
- `uml_dsl/svg_parser.py` — обратный разбор SVG;
- `uml_dsl/tdl_serializer.py` — сериализация модели обратно в TDL;
- `uml_dsl/tdl_run.py` — программный API и CLI;
- `uml_dsl/app.py` — Streamlit-интерфейс;
- `uml_dsl/export.py` — экспорт PNG/JPG.

---

## Поддерживаемые элементы UML

- классы и абстрактные классы;
- атрибуты;
- операции и параметры;
- видимость;
- типы и кратности;
- ассоциации;
- роли полюсов;
- навигация;
- агрегация;
- композиция;
- зависимости;
- обобщения;
- реализации.

Поддерживаются декларативные команды размещения: выравнивание, распределение, привязка и фиксация.

---

## Требования

- Python 3.10 или новее;
- системный Graphviz;
- команда `dot` должна быть доступна в `PATH`.

Проверка Graphviz:

```powershell
dot -V
Get-Command dot
```

Проект вызывает системный `dot` напрямую. Python-пакет `graphviz` не требуется.

---

## Установка

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Если PowerShell блокирует активацию:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Для разработки и тестирования:

```powershell
python -m pip install -r requirements-dev.txt
```

---

## Быстрый старт

### Генерация SVG из TDL

```powershell
python -m uml_dsl.tdl_run `
  .\examples\robot_biologist.tdl `
  -o .\output\robot.svg
```

Параметр `-o` / `--output` задаёт путь сохранения SVG.

### Запуск Streamlit

```powershell
python -m streamlit run uml_dsl/app.py
```

После запуска приложение обычно доступно по адресу:

```text
http://localhost:8501
```

В интерфейсе доступны:

- ввод или загрузка TDL;
- генерация SVG;
- превью диаграммы;
- загрузка и валидация SVG;
- просмотр ошибок и предупреждений;
- экспорт в SVG, PNG и JPG.

---

## Программный API

```python
from uml_dsl.tdl_run import tdl_to_svg

source = """
КЛАСС Пример
КОНЕЦ КЛАСС
"""

svg = tdl_to_svg(source)
```

Обратный парсинг:

```python
from uml_dsl.svg_parser import parse_svg_to_diagram

result = parse_svg_to_diagram(svg)

if result.success:
    diagram = result.diagram
else:
    print(result.errors)
```

Сериализация обратно в TDL:

```python
from uml_dsl.tdl_serializer import diagram_to_tdl

tdl = diagram_to_tdl(diagram)
```

---

## SVG-метаданные

Сгенерированный SVG содержит служебные атрибуты:

- `data-tdl-schema`;
- `data-layout`;
- `data-model`;
- `data-type`;
- `data-src`;
- `data-tgt`;
- роли, кратности, навигацию и типы агрегации.

Текущая версия:

```xml
data-tdl-schema="1"
```

SVG без версии поддерживаются как legacy-формат с предупреждением.

---

## Тестирование

Установить зависимости:

```powershell
python -m pip install -r requirements-dev.txt
```

Запустить все тесты:

```powershell
python -m pytest -q
```

Проверенный результат:

```text
22 passed
```

Отдельная проверка CLI:

```powershell
python -m pytest tests/test_tdl_run.py -q
```

---

## Структура репозитория

```text
ontol_v3_students/
├── uml_dsl/
│   ├── app.py
│   ├── diagram.py
│   ├── enums.py
│   ├── export.py
│   ├── graphviz_render.py
│   ├── models.py
│   ├── relationships.py
│   ├── svg_metadata.py
│   ├── svg_parser.py
│   ├── tdl_ast.py
│   ├── tdl_build.py
│   ├── tdl_lexer.py
│   ├── tdl_parser.py
│   ├── tdl_run.py
│   └── tdl_serializer.py
├── examples/
│   └── robot_biologist.tdl
├── tests/
├── requirements.txt
├── requirements-dev.txt
├── PROJECT_DOCUMENTATION.md
└── README.md
```

---

## Ограничения

- основной поддерживаемый тип — UML-диаграмма классов;
- команды размещения задают ограничения Graphviz, а не точные пиксельные координаты;
- интерактивное drag-and-drop редактирование не входит в текущую реализацию;
- полноценное восстановление возможно только для SVG с семантическими `data-*` атрибутами;
- сложные N-арные ассоциации могут требовать дополнительного расширения сериализатора.

---

## Документация

Подробное описание архитектуры, форматов, модулей, тестов и ограничений:

**[PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md)**
