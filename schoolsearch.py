#!/usr/bin/env python3
"""Schoolsearch — лабораторна робота №1 з дисципліни «Бази даних».

Програма читає students.txt із поточного каталогу, виконує пошук за
вимогами R1–R11, підтримує додавання, статистику, оновлення, видалення
та експорт поточного стану в JSON/XML.

Сторонні бібліотеки не використовуються.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter


@dataclass(frozen=True)
class Teacher:
    last_name: str
    first_name: str


@dataclass(frozen=True)
class Student:
    record_id: int
    last_name: str
    first_name: str
    grade: int
    classroom: int
    bus: int
    teacher: Teacher


class SchoolSearch:
    """Зберігає дані в пам'яті та виконує всі операції над ними."""

    def __init__(self) -> None:
        self.students: list[Student] = []
        # Викладачі, додані окремою командою AddTeacher.
        self.added_teachers: set[Teacher] = set()
        self.next_id = 1
        self.dirty = False
        self.load_read_ms = 0.0
        self.load_parse_ms = 0.0

    @staticmethod
    def _nonempty(text: str, field_name: str) -> str:
        value = text.strip()
        if not value:
            raise ValueError(f'Поле «{field_name}» не може бути порожнім.')
        if any(ord(ch) < 32 for ch in value):
            raise ValueError(f'Поле «{field_name}» містить керувальні символи.')
        return value

    @staticmethod
    def _number(text: str, field_name: str) -> int:
        value = text.strip()
        if not re.fullmatch(r'[0-9]+', value):
            raise ValueError(f'Поле «{field_name}» має бути невід’ємним цілим числом.')
        return int(value)

    @classmethod
    def _student_from_fields(cls, fields: list[str], record_id: int) -> Student:
        if len(fields) != 7:
            raise ValueError('Запис студента повинен містити рівно 7 полів.')

        last_name = cls._nonempty(fields[0], 'StLastName')
        first_name = cls._nonempty(fields[1], 'StFirstName')
        grade = cls._number(fields[2], 'Grade')
        classroom = cls._number(fields[3], 'Classroom')
        bus = cls._number(fields[4], 'Bus')
        teacher_last = cls._nonempty(fields[5], 'TLastName')
        teacher_first = cls._nonempty(fields[6], 'TFirstName')

        return Student(
            record_id=record_id,
            last_name=last_name,
            first_name=first_name,
            grade=grade,
            classroom=classroom,
            bus=bus,
            teacher=Teacher(teacher_last, teacher_first),
        )

    @classmethod
    def _student_from_text(cls, text: str, record_id: int) -> Student:
        row = next(csv.reader([text], skipinitialspace=True))
        return cls._student_from_fields(row, record_id)

    @classmethod
    def _teacher_from_text(cls, text: str) -> Teacher:
        row = next(csv.reader([text], skipinitialspace=True))
        if len(row) != 2:
            raise ValueError('Викладач повинен містити рівно 2 поля: прізвище,ім’я.')
        return Teacher(
            cls._nonempty(row[0], 'TLastName'),
            cls._nonempty(row[1], 'TFirstName'),
        )

    def load(self, filename: str = 'students.txt') -> None:
        """R9/R11: читає students.txt; некоректний файл не завантажується частково."""

        path = Path(filename)

        start = perf_counter()
        try:
            text = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError) as exc:
            raise ValueError(f'не вдалося прочитати {filename}: {exc}') from exc
        self.load_read_ms = (perf_counter() - start) * 1000

        start = perf_counter()
        parsed_students: list[Student] = []
        reader = csv.reader(text.splitlines(), skipinitialspace=True)

        try:
            for line_number, row in enumerate(reader, start=1):
                try:
                    student = self._student_from_fields(row, line_number)
                except ValueError as exc:
                    raise ValueError(f'рядок {line_number}: {exc}') from exc
                parsed_students.append(student)
        except csv.Error as exc:
            raise ValueError(f'помилка CSV: {exc}') from exc

        if not parsed_students:
            raise ValueError('students.txt порожній.')

        self.load_parse_ms = (perf_counter() - start) * 1000
        self.students = parsed_students
        self.added_teachers = set()
        self.next_id = len(parsed_students) + 1
        self.dirty = False

    def teachers(self) -> set[Teacher]:
        """Поточна множина викладачів: із записів студентів + додані окремо."""

        return {student.teacher for student in self.students} | self.added_teachers

    def search(self, kind: str, value: str | int) -> tuple[list[Student], float]:
        """R8: вимірюється тільки сам відбір; розбір команди й друк не входять у час."""

        if kind == 'S':
            predicate = lambda s: s.last_name == value
        elif kind == 'T':
            predicate = lambda s: s.teacher.last_name == value
        elif kind == 'C':
            predicate = lambda s: s.classroom == value
        elif kind == 'B':
            predicate = lambda s: s.bus == value
        elif kind == 'G':
            predicate = lambda s: s.grade == value
        else:
            raise ValueError('Невідомий тип пошуку.')

        start = perf_counter()
        result = [student for student in self.students if predicate(student)]
        elapsed_ms = (perf_counter() - start) * 1000
        return result, elapsed_ms

    def add_student(self, record_text: str) -> int:
        student = self._student_from_text(record_text, self.next_id)
        self.students.append(student)
        self.next_id += 1
        self.dirty = True
        return student.record_id

    def add_teacher(self, teacher_text: str) -> None:
        teacher = self._teacher_from_text(teacher_text)
        if teacher in self.teachers():
            raise ValueError('Такий викладач уже існує.')
        self.added_teachers.add(teacher)
        self.dirty = True

    def _index_by_id(self, record_id: int) -> int:
        for index, student in enumerate(self.students):
            if student.record_id == record_id:
                return index
        raise ValueError('Запису студента з таким ID немає.')

    def update_student(self, record_id: int, record_text: str) -> None:
        index = self._index_by_id(record_id)
        replacement = self._student_from_text(record_text, record_id)
        self.students[index] = replacement
        self.dirty = True

    def delete_student(self, record_id: int) -> None:
        index = self._index_by_id(record_id)
        del self.students[index]
        self.dirty = True

    def save(self, file_format: str, filename: str) -> None:
        """Зберігає поточний стан у одному з двох форматів: JSON або XML."""

        fmt = file_format.upper()
        if fmt not in {'JSON', 'XML'}:
            raise ValueError('Формат збереження має бути JSON або XML.')

        path = Path(filename)
        required_suffix = '.json' if fmt == 'JSON' else '.xml'
        if path.suffix.lower() != required_suffix:
            raise ValueError(f'Для формату {fmt} файл повинен мати розширення {required_suffix}.')

        data_students = [asdict(student) for student in self.students]
        data_teachers = [
            asdict(teacher)
            for teacher in sorted(self.teachers(), key=lambda t: (t.last_name, t.first_name))
        ]

        target_dir = path.resolve().parent
        if not target_dir.exists():
            raise OSError(f'Каталог не існує: {target_dir}')

        descriptor, temp_name = tempfile.mkstemp(dir=target_dir)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                if fmt == 'JSON':
                    json.dump(
                        {'students': data_students, 'teachers': data_teachers},
                        output,
                        ensure_ascii=False,
                        indent=2,
                    )
                else:
                    root = ET.Element('school')

                    students_node = ET.SubElement(root, 'students')
                    for student in self.students:
                        student_node = ET.SubElement(students_node, 'student')
                        ET.SubElement(student_node, 'id').text = str(student.record_id)
                        ET.SubElement(student_node, 'last_name').text = student.last_name
                        ET.SubElement(student_node, 'first_name').text = student.first_name
                        ET.SubElement(student_node, 'grade').text = str(student.grade)
                        ET.SubElement(student_node, 'classroom').text = str(student.classroom)
                        ET.SubElement(student_node, 'bus').text = str(student.bus)
                        teacher_node = ET.SubElement(student_node, 'teacher')
                        ET.SubElement(teacher_node, 'last_name').text = student.teacher.last_name
                        ET.SubElement(teacher_node, 'first_name').text = student.teacher.first_name

                    teachers_node = ET.SubElement(root, 'teachers')
                    for teacher in sorted(self.teachers(), key=lambda t: (t.last_name, t.first_name)):
                        teacher_node = ET.SubElement(teachers_node, 'teacher')
                        ET.SubElement(teacher_node, 'last_name').text = teacher.last_name
                        ET.SubElement(teacher_node, 'first_name').text = teacher.first_name

                    ET.indent(root)
                    output.write(ET.tostring(root, encoding='unicode', xml_declaration=True))

            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

        self.dirty = False


HELP = """Команди пошуку (регістр має значення):
  S[tudent]: <lastname>
  S[tudent]: <lastname> B[us]
  T[eacher]: <lastname>
  C[lassroom]: <number>
  B[us]: <number>
  G[rade]: <number>
  Q[uit]

Інші функції, передбачені завданням:
  AddStudent: StLastName,StFirstName,Grade,Classroom,Bus,TLastName,TFirstName
  AddTeacher: TLastName,TFirstName
  Stats
  Update: ID; StLastName,StFirstName,Grade,Classroom,Bus,TLastName,TFirstName
  Delete: ID
  Save: JSON <filename.json>
  Save: XML <filename.xml>
  Help

Для початкових записів ID дорівнює номеру рядка у students.txt.
Для нового студента ID друкується після AddStudent.
"""


def parse_nonnegative_number(text: str) -> int:
    value = text.strip()
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError('Очікується невід’ємне ціле число.')
    return int(value)


def execute_command(school: SchoolSearch, command: str) -> bool:
    """Виконує одну команду. False означає завершення програми."""

    # R3: команди чутливі до регістру.
    if command in {'Q', 'Quit'}:
        if school.dirty:
            print('Увага: поточні зміни ще не були збережені через Save.')
        return False

    if command == 'Help':
        print(HELP)
        return True

    if command == 'Stats':
        print(f'Студентів: {len(school.students)}')
        print(f'Викладачів: {len(school.teachers())}')
        return True

    search_match = re.fullmatch(
        r'(S|Student|T|Teacher|C|Classroom|B|Bus|G|Grade):\s*(.+)',
        command,
    )

    if search_match:
        command_name, raw_value = search_match.groups()
        kind = command_name[0]
        bus_option = False
        value: str | int

        if kind == 'S':
            bus_match = re.fullmatch(r'(.+?)\s+(B|Bus)', raw_value)
            if bus_match:
                raw_value = bus_match.group(1)
                bus_option = True

        raw_value = raw_value.strip()
        if kind in {'C', 'B', 'G'}:
            value = parse_nonnegative_number(raw_value)
        else:
            if not raw_value or any(ch.isspace() for ch in raw_value):
                raise ValueError('Прізвище має бути одним непорожнім словом.')
            value = raw_value

        records, elapsed_ms = school.search(kind, value)

        # R4–R8: спочатку результати, потім окремим рядком час пошуку.
        for student in records:
            if kind == 'S' and not bus_option:
                print(
                    f'{student.last_name} {student.first_name}; '
                    f'Grade={student.grade}; Classroom={student.classroom}; '
                    f'Teacher={student.teacher.last_name} {student.teacher.first_name}'
                )
            elif kind == 'S' and bus_option:
                print(f'{student.last_name} {student.first_name}; Bus={student.bus}')
            elif kind == 'B':
                print(
                    f'{student.last_name} {student.first_name}; '
                    f'Grade={student.grade}; Classroom={student.classroom}'
                )
            else:
                print(f'{student.last_name} {student.first_name}')

        print(f'Знайдено записів: {len(records)}')
        print(f'Час пошуку: {elapsed_ms:.3f} мс')
        return True

    name, separator, value = command.partition(':')
    if not separator:
        raise ValueError('Невідома команда. Введіть Help.')

    value = value.strip()

    if name == 'AddStudent':
        start = perf_counter()
        record_id = school.add_student(value)
        elapsed_ms = (perf_counter() - start) * 1000
        print(f'Студента додано. ID={record_id}')
        print(f'Час операції: {elapsed_ms:.3f} мс')
        return True

    if name == 'AddTeacher':
        start = perf_counter()
        school.add_teacher(value)
        elapsed_ms = (perf_counter() - start) * 1000
        print('Викладача додано.')
        print(f'Час операції: {elapsed_ms:.3f} мс')
        return True

    if name == 'Update':
        id_text, separator, record_text = value.partition(';')
        if not separator:
            raise ValueError('Формат: Update: ID; сім полів студента через кому.')
        record_id = parse_nonnegative_number(id_text)
        start = perf_counter()
        school.update_student(record_id, record_text.strip())
        elapsed_ms = (perf_counter() - start) * 1000
        print(f'Запис ID={record_id} оновлено.')
        print(f'Час операції: {elapsed_ms:.3f} мс')
        return True

    if name == 'Delete':
        record_id = parse_nonnegative_number(value)
        start = perf_counter()
        school.delete_student(record_id)
        elapsed_ms = (perf_counter() - start) * 1000
        print(f'Запис ID={record_id} видалено.')
        print(f'Час операції: {elapsed_ms:.3f} мс')
        return True

    if name == 'Save':
        format_name, separator, filename = value.partition(' ')
        if not separator or not filename.strip():
            raise ValueError('Формат: Save: JSON filename.json або Save: XML filename.xml')
        start = perf_counter()
        school.save(format_name, filename.strip())
        elapsed_ms = (perf_counter() - start) * 1000
        print(f'Дані збережено у {filename.strip()}.')
        print(f'Час операції: {elapsed_ms:.3f} мс')
        return True

    raise ValueError('Невідома команда. Введіть Help.')


def main() -> int:
    # R2: жодних параметрів командного рядка.
    if len(sys.argv) != 1:
        print('Помилка: програму потрібно запускати без параметрів командного рядка.')
        return 1

    school = SchoolSearch()

    # R9/R11: students.txt береться саме з поточного каталогу.
    try:
        school.load('students.txt')
    except ValueError as exc:
        print(f'Помилка students.txt: {exc}')
        return 1

    print(f'Завантажено записів студентів: {len(school.students)}')
    print(f'Зчитування файлу: {school.load_read_ms:.3f} мс')
    print(f'Перевірка та створення об’єктів: {school.load_parse_ms:.3f} мс')
    print('Введіть Help для списку команд.')

    while True:
        try:
            command = input('schoolsearch> ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nЗавершення роботи.')
            if school.dirty:
                print('Увага: поточні зміни ще не були збережені через Save.')
            return 0

        if not command:
            continue

        try:
            if not execute_command(school, command):
                return 0
        except (ValueError, OSError, UnicodeError) as exc:
            # R10/R11: без traceback; після неправильної команди повертаємось до prompt.
            print(f'Помилка: {exc}')


if __name__ == '__main__':
    sys.exit(main())
