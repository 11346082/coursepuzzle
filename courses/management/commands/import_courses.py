"""從 CSV 匯入真實的課程與開課資料。

CSV 欄位（第一列為標題）：
  code, name, department, credits, category, teacher_username, classroom, capacity,
  times, description, objectives, grading, textbook, outline
times 格式：「星期:開始節-結束節」，多個時段用分號分隔，例如 1:2-4;3:6-7
objectives、outline 內若要換行請寫成 \\n
category 可填 required/elective/general/pe 或 必修/選修/通識/體育
範例檔：data/courses_sample.csv
"""
import csv

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from courses.models import ClassTime, Course, Department, Section, Semester
from courses.services import current_semester

CATEGORY_MAP = {"必修": "required", "選修": "elective", "通識": "general", "體育": "pe"}


class Command(BaseCommand):
    help = "從 CSV 匯入課程與開課資料"

    def add_arguments(self, parser):
        parser.add_argument("path", help="CSV 檔案路徑")
        parser.add_argument("--semester", default=None, help="學期名稱，例如 115-1；預設為目前學期")

    def handle(self, *args, **options):
        semester = (Semester.objects.filter(name=options["semester"]).first()
                    if options["semester"] else current_semester())
        if not semester:
            raise CommandError("找不到學期，請先在後台建立學期。")

        count = 0
        with open(options["path"], newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                code = (row.get("code") or "").strip()
                if not code:
                    continue
                dept, _ = Department.objects.get_or_create(name=(row.get("department") or "未分類").strip())
                cat = (row.get("category") or "elective").strip()
                cat = CATEGORY_MAP.get(cat, cat)
                if cat not in dict(Course.CATEGORIES):
                    cat = "elective"
                nl = lambda key: (row.get(key) or "").replace("\\n", "\n")
                course, _ = Course.objects.update_or_create(code=code, defaults=dict(
                    name=(row.get("name") or code).strip(), department=dept,
                    credits=int(row.get("credits") or 3), category=cat,
                    description=nl("description"), objectives=nl("objectives"),
                    grading=nl("grading"), textbook=nl("textbook")))
                teacher = User.objects.filter(username=(row.get("teacher_username") or "").strip()).first()
                section, _ = Section.objects.update_or_create(course=course, semester=semester, defaults=dict(
                    teacher=teacher, classroom=(row.get("classroom") or "").strip(),
                    capacity=int(row.get("capacity") or 40), outline=nl("outline"), is_active=True))
                times = (row.get("times") or "").strip()
                if times:
                    section.times.all().delete()
                    for part in times.split(";"):
                        weekday, rng = part.strip().split(":")
                        start, end = rng.split("-")
                        ClassTime.objects.create(section=section, weekday=int(weekday),
                                                 start_period=int(start), end_period=int(end))
                count += 1
        self.stdout.write(self.style.SUCCESS(f"已匯入 {count} 筆開課資料到 {semester.name}"))
