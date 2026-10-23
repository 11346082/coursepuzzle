from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from courses import demo_data as D
from courses.models import (Announcement, CampusEvent, ClassTime, Course, Department, Enrollment,
                            Notification, Profile, Review, Section, Semester, Todo)


def _spread(items, start, end):
    weeks = list(range(start, end + 1))
    base, extra = divmod(len(weeks), len(items))
    out, i = [], 0
    for k, item in enumerate(items):
        size = base + (1 if k < extra else 0)
        chunk = weeks[i:i + size]
        i += size
        rng = f"第 {chunk[0]} 週" if len(chunk) == 1 else f"第 {chunk[0]}–{chunk[-1]} 週"
        out.append(f"{rng}　{item}")
    return out


def week_plan(topics):
    """把主題分配到第 1–8 週與第 10–17 週，第 9 週期中考、第 18 週期末考。"""
    k = (len(topics) + 1) // 2
    lines = _spread(topics[:k], 1, 8) + ["第 9 週　期中考"]
    if topics[k:]:
        lines += _spread(topics[k:], 10, 17)
    return "\n".join(lines + ["第 18 週　期末考與課程回顧"])


def make_user(username, password, last, first, role, dept=None, student_no="", superuser=False):
    user, created = User.objects.get_or_create(
        username=username,
        defaults=dict(last_name=last, first_name=first, is_staff=superuser, is_superuser=superuser,
                      email=f"{username}@example.com"),
    )
    if created:
        user.set_password(password)
        user.save()
    Profile.objects.update_or_create(
        user=user, defaults=dict(role=role, department=dept, student_no=student_no))
    return user


class Command(BaseCommand):
    help = "建立課拼 CoursePuzzle 的示範資料（可重複執行）"

    def handle(self, *args, **options):
        now = timezone.now()
        local_now = timezone.localtime(now)

        semester, _ = Semester.objects.update_or_create(
            name="115-1",
            defaults=dict(is_current=True, start_date=date(2026, 9, 14), end_date=date(2027, 1, 17),
                          enroll_open=now - timedelta(days=2), enroll_close=now + timedelta(days=45),
                          max_credits=25),
        )
        depts = {}
        for name, college in D.DEPARTMENTS:
            depts[name], _ = Department.objects.update_or_create(name=name, defaults=dict(college=college))

        make_user("admin", "admin1234", "教務", "處", "staff", superuser=True)
        teachers = {u: make_user(u, "demo1234", last, first, "teacher", depts[d])
                    for u, last, first, d in D.TEACHERS}
        students = {u: make_user(u, "demo1234", last, first, "student", depts[d], no)
                    for u, last, first, d, no in D.STUDENTS}

        sections = {}
        for c in D.COURSES:
            course, _ = Course.objects.update_or_create(
                code=c["code"],
                defaults=dict(name=c["name"], department=depts[c["dept"]], credits=c["credits"],
                              category=c["cat"], description=c["desc"],
                              objectives="\n".join(c["obj"]), grading=c["grading"], textbook=c["book"]),
            )
            section, _ = Section.objects.update_or_create(
                course=course, semester=semester,
                defaults=dict(teacher=teachers[c["teacher"]], classroom=c["room"], capacity=c["cap"],
                              is_active=True, outline=week_plan(c["topics"]), announcement=c["notice"]),
            )
            section.times.all().delete()
            for weekday, start, end in c["times"]:
                ClassTime.objects.create(section=section, weekday=weekday, start_period=start, end_period=end)
            sections[c["code"]] = section

        for username, code in D.ENROLLMENTS:
            Enrollment.objects.get_or_create(student=students[username], section=sections[code])

        for username, code, rating, comment in D.REVIEWS:
            Review.objects.update_or_create(
                student=students[username], course=sections[code].course,
                defaults=dict(rating=rating, comment=comment))

        for title, cat, pinned, content, days_ago in D.ANNOUNCEMENTS:
            Announcement.objects.update_or_create(
                title=title,
                defaults=dict(content=content, category=cat, is_pinned=pinned,
                              created_at=now - timedelta(days=days_ago)),
            )

        for title, desc, cat, loc, org, days, hour, minute, hours, cap in D.EVENTS:
            start = (local_now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            CampusEvent.objects.update_or_create(
                title=title,
                defaults=dict(description=desc, category=cat, location=loc, organizer=org, start=start,
                              end=start + timedelta(hours=hours), capacity=cap),
            )

        me = students["s1001"]
        if not Todo.objects.filter(user=me).exists():
            today = local_now.date()
            for title, days, done in D.REVIEW_TODOS:
                Todo.objects.create(user=me, title=title, due_date=today + timedelta(days=days), is_done=done)
        if not Notification.objects.filter(user=me).exists():
            Notification.objects.create(user=me, text="歡迎使用課拼！到「智慧排課」試試一鍵排課。", url="/me/planner/")
            Notification.objects.create(user=me, text="資料庫管理已額滿，可以先加入候補。", url="/courses/?q=資料庫")

        self.stdout.write(self.style.SUCCESS("課拼示範資料建立完成。"))
        self.stdout.write("教職員：admin / admin1234（後台 /admin/）")
        self.stdout.write("老師：t_lin、t_chang、t_wu、t_huang、t_cheng ... / demo1234")
        self.stdout.write("學生：s1001 ~ s1006 / demo1234")
        self.stdout.write("註：課程、老師、學生皆為虛構的示範資料。")
