"""課拼核心邏輯：衝堂檢查、狀態判斷、加退選、候補、智慧排課、課表匯出。
views 只負責收請求與回應。"""
from collections import Counter
from datetime import datetime, timedelta
from datetime import time as dtime
from datetime import timezone as dt_timezone

from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from .models import Course, Enrollment, Favorite, Notification, Section, Semester, Waitlist
from .timeutils import PERIOD_START, PERIODS, WEEKDAY_IDS, describe_slots


def role_of(user):
    if not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    if profile:
        return profile.role
    return "staff" if user.is_superuser else "student"


def current_semester():
    return Semester.objects.filter(is_current=True).first() or Semester.objects.order_by("-name").first()


def notify(user, text, url=""):
    Notification.objects.create(user=user, text=text[:200], url=url)


def base_sections():
    return (
        Section.objects.filter(is_active=True)
        .select_related("course__department", "teacher", "semester")
        .prefetch_related("times")
        .annotate(enrolled_n=Count("enrollments", distinct=True))
    )


def section_slots(section):
    slots = set()
    for t in section.times.all():
        slots |= t.slots()
    return slots


class StudentContext:
    """一次載入某位學生本學期的課表，用來快速判斷每門課的狀態。"""

    def __init__(self, student, semester):
        self.student = student
        self.semester = semester
        self.enrolled = list(
            Section.objects.filter(enrollments__student=student, semester=semester, is_active=True)
            .select_related("course", "teacher")
            .prefetch_related("times")
            .order_by("course__code")
        )
        self.enrolled_ids = {s.pk for s in self.enrolled}
        self.enrolled_course_ids = {s.course_id for s in self.enrolled}
        self.slot_owner = {}
        for s in self.enrolled:
            for slot in section_slots(s):
                self.slot_owner[slot] = s
        self.credits = sum(s.course.credits for s in self.enrolled)
        self.favorite_ids = set(
            Favorite.objects.filter(student=student).values_list("section_id", flat=True))
        self.waitlist_ids = set(
            Waitlist.objects.filter(student=student).values_list("section_id", flat=True))

    def conflict_with(self, section):
        owner, overlap = None, set()
        for slot in section_slots(section):
            hit = self.slot_owner.get(slot)
            if hit and hit.pk != section.pk:
                overlap.add(slot)
                owner = owner or hit
        return owner, overlap

    def status(self, section):
        """回傳 (狀態, 原因)。狀態：enrolled / conflict / full / waitlisted / available。"""
        if section.pk in self.enrolled_ids:
            return "enrolled", "已加選"
        if section.course_id in self.enrolled_course_ids:
            return "conflict", "你已加選這門課的其他班級"
        owner, overlap = self.conflict_with(section)
        if owner:
            return "conflict", f"與「{owner.course.name}」{describe_slots(overlap)}衝堂"
        if section.is_full():
            if section.pk in self.waitlist_ids:
                return "waitlisted", "已在候補名單，有人退選時會依序自動遞補"
            return "full", "人數已滿，可以加入候補"
        return "available", ""


def attach_status(student, semester, sections):
    ctx = StudentContext(student, semester)
    for s in sections:
        s.state, s.reason = ctx.status(s)
        s.is_fav = s.pk in ctx.favorite_ids
    return ctx


def build_grid(enrolled, preview=None, extra=()):
    """產生週課表格狀資料。
    preview：單一預覽的開課，衝堂的格子標為 clash。
    extra：方案裡要新增的多門課（已確定不衝堂），標為 preview。
    """
    cells = {}
    for sec in enrolled:
        for t in sec.times.all():
            for p in range(t.start_period, t.end_period + 1):
                cells[(t.weekday, p)] = {"kind": "enrolled", "section": sec, "first": p == t.start_period}
    for sec in list(extra) + ([preview] if preview else []):
        for t in sec.times.all():
            for p in range(t.start_period, t.end_period + 1):
                key = (t.weekday, p)
                kind = "clash" if key in cells else "preview"
                cells[key] = {"kind": kind, "section": sec, "first": p == t.start_period}
    return [
        {"period": p, "time": PERIOD_START[p], "cells": [cells.get((d, p)) for d in WEEKDAY_IDS]}
        for p in PERIODS
    ]


def category_breakdown(enrolled):
    totals = Counter()
    for s in enrolled:
        totals[s.course.category] += s.course.credits
    return [(label, totals[key]) for key, label in Course.CATEGORIES if totals[key]]


# ---------- 加退選 ----------

@transaction.atomic
def enroll(student, section_id):
    """加選。回傳 (成功與否, 給使用者看的訊息)。"""
    try:
        section = (
            Section.objects.select_for_update()
            .select_related("course", "semester")
            .get(pk=section_id, is_active=True)
        )
    except Section.DoesNotExist:
        return False, "找不到這門課，可能已下架"

    is_open, why = section.semester.enrollment_state()
    if not is_open:
        return False, why

    ctx = StudentContext(student, section.semester)
    name = section.course.name
    if section.pk in ctx.enrolled_ids:
        return False, f"你已經加選「{name}」了"
    if section.course_id in ctx.enrolled_course_ids:
        return False, f"你已加選「{name}」的其他班級"
    owner, overlap = ctx.conflict_with(section)
    if owner:
        return False, f"加選失敗：「{name}」與「{owner.course.name}」{describe_slots(overlap)}衝堂"
    if section.enrollments.count() >= section.capacity:
        return False, f"加選失敗：「{name}」人數已滿（上限 {section.capacity} 人），可以改為加入候補"
    limit = section.semester.max_credits
    if ctx.credits + section.course.credits > limit:
        return False, f"加選失敗：加選後會有 {ctx.credits + section.course.credits} 學分，超過上限 {limit} 學分"

    Enrollment.objects.create(student=student, section=section)
    Waitlist.objects.filter(student=student, section=section).delete()
    notify(student, f"已加選「{name}」，目前 {ctx.credits + section.course.credits} 學分", reverse("my_schedule"))
    return True, f"已加選「{name}」"


@transaction.atomic
def drop(student, section_id):
    deleted, _ = Enrollment.objects.filter(student=student, section_id=section_id).delete()
    if not deleted:
        return False, "你沒有加選這門課"
    section = Section.objects.select_related("course").get(pk=section_id)
    notify(student, f"已退選「{section.course.name}」", reverse("my_schedule"))
    promote_waitlist(section)
    return True, f"已退選「{section.course.name}」"


def promote_waitlist(section):
    """名額釋出時，依登記順序把候補同學自動加選。回傳成功遞補的學生。"""
    promoted = []
    for entry in Waitlist.objects.filter(section=section).select_related("student").order_by("created_at"):
        if section.enrollments.count() >= section.capacity:
            break
        ok, _ = enroll(entry.student, section.pk)
        if ok:
            promoted.append(entry.student)
            notify(entry.student, f"候補成功！「{section.course.name}」釋出名額，已自動為你加選",
                   reverse("my_schedule"))
    return promoted


@transaction.atomic
def join_waitlist(student, section_id):
    try:
        section = Section.objects.select_related("course", "semester").get(pk=section_id, is_active=True)
    except Section.DoesNotExist:
        return False, "找不到這門課，可能已下架"
    is_open, why = section.semester.enrollment_state()
    if not is_open:
        return False, why
    ctx = StudentContext(student, section.semester)
    state, reason = ctx.status(section)
    if state == "waitlisted":
        return False, "你已經在這門課的候補名單裡了"
    if state == "available":
        return False, "這門課還有名額，直接加選就可以"
    if state != "full":
        return False, reason
    Waitlist.objects.create(student=student, section=section)
    position = Waitlist.objects.filter(section=section).count()
    notify(student, f"已加入「{section.course.name}」候補，目前第 {position} 位", reverse("course_detail", args=[section.course_id]))
    return True, f"已加入「{section.course.name}」候補，目前第 {position} 位"


def leave_waitlist(student, section_id):
    deleted, _ = Waitlist.objects.filter(student=student, section_id=section_id).delete()
    return (True, "已取消候補") if deleted else (False, "你不在這門課的候補名單裡")


def enroll_many(student, section_ids):
    """一鍵加選：依序加選，衝堂、額滿、超過學分的會被擋下。回傳 (成功課名, 失敗訊息)。"""
    names = {s.pk: s.course.name
             for s in Section.objects.filter(pk__in=section_ids).select_related("course")}
    done, failed = [], []
    for sid in section_ids:
        ok, msg = enroll(student, sid)
        if ok:
            done.append(names.get(sid, ""))
        else:
            failed.append(msg)
    return done, failed


# ---------- 智慧排課 ----------

def candidate_sections(ctx, avoid_day=None, no_early=False, no_lunch=False):
    """符合條件、還能加選的開課。"""
    out = []
    for s in base_sections().filter(semester=ctx.semester):
        if s.pk in ctx.enrolled_ids or s.course_id in ctx.enrolled_course_ids or s.is_full():
            continue
        times = list(s.times.all())
        if avoid_day and any(t.weekday == avoid_day for t in times):
            continue
        if no_early and any(t.start_period == 1 for t in times):
            continue
        if no_lunch and any(t.start_period <= 5 <= t.end_period for t in times):
            continue
        out.append(s)
    return out


def _build_plan(ctx, candidates, target, key=None, compact=False):
    used = set(ctx.slot_owner)
    days = {d for d, _ in used}
    credits = ctx.credits
    chosen, course_ids = [], set()
    pool = sorted(candidates, key=key or (lambda s: s.course.code))
    while credits < target:
        feasible = [
            s for s in pool
            if s not in chosen and s.course_id not in course_ids
            and credits + s.course.credits <= target
            and not (section_slots(s) & used)
        ]
        if not feasible:
            break
        if compact:  # 盡量不增加到校天數
            pick = min(feasible, key=lambda s: (len({d for d, _ in section_slots(s)} - days), s.course.code))
        else:
            pick = feasible[0]
        chosen.append(pick)
        course_ids.add(pick.course_id)
        slots = section_slots(pick)
        used |= slots
        days |= {d for d, _ in slots}
        credits += pick.course.credits
    return chosen


def generate_plans(ctx, candidates, target):
    """最多產生三套不重複的方案。"""
    strategies = [
        ("收藏優先", dict(key=lambda s: (s.pk not in ctx.favorite_ids, s.course.code))),
        ("集中上課日", dict(compact=True)),
        ("學分優先", dict(key=lambda s: (-s.course.credits, s.course.code))),
    ]
    plans, seen = [], set()
    for name, kwargs in strategies:
        chosen = _build_plan(ctx, candidates, target, **kwargs)
        ids = frozenset(s.pk for s in chosen)
        if not chosen or ids in seen:
            continue
        seen.add(ids)
        slots = set(ctx.slot_owner)
        for s in chosen:
            slots |= section_slots(s)
        plans.append({
            "name": name,
            "sections": chosen,
            "ids": [s.pk for s in chosen],
            "added_credits": sum(s.course.credits for s in chosen),
            "total_credits": ctx.credits + sum(s.course.credits for s in chosen),
            "days": len({d for d, _ in slots}),
            "rows": build_grid(ctx.enrolled, extra=chosen),
        })
    return plans


# ---------- 課表匯出（iCalendar，可匯入 Google 日曆、Apple 行事曆）----------

def _esc(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """iCalendar 每行不超過 75 位元組，超過的換行並以空白開頭。"""
    out, cur, size = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if size + b > 73:
            out.append(cur)
            cur, size = " " + ch, 1 + b
        else:
            cur += ch
            size += b
    out.append(cur)
    return "\r\n".join(out)


def build_ics(student, semester):
    tz = timezone.get_default_timezone()
    ctx = StudentContext(student, semester)
    start = semester.start_date or timezone.localdate()
    end = semester.end_date or (start + timedelta(weeks=18))
    first_monday = start - timedelta(days=start.weekday())
    until = datetime.combine(end, dtime(23, 59, 59), tzinfo=tz).astimezone(dt_timezone.utc)
    stamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fmt = "%Y%m%dT%H%M%SZ"

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CoursePuzzle//課拼//ZH-TW",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{_esc('課拼課表 ' + semester.name)}"]
    for sec in ctx.enrolled:
        for t in sec.times.all():
            day = first_monday + timedelta(days=t.weekday - 1)
            if day < start:
                day += timedelta(days=7)
            sh, sm = map(int, PERIOD_START[t.start_period].split(":"))
            eh, em = map(int, PERIOD_START[t.end_period].split(":"))
            begin = datetime.combine(day, dtime(sh, sm), tzinfo=tz)
            finish = datetime.combine(day, dtime(eh, em), tzinfo=tz) + timedelta(minutes=50)
            lines += [
                "BEGIN:VEVENT",
                f"UID:cp-{sec.pk}-{t.weekday}-{t.start_period}@coursepuzzle",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{begin.astimezone(dt_timezone.utc).strftime(fmt)}",
                f"DTEND:{finish.astimezone(dt_timezone.utc).strftime(fmt)}",
                f"RRULE:FREQ=WEEKLY;UNTIL={until.strftime(fmt)}",
                f"SUMMARY:{_esc(sec.course.name)}",
                f"LOCATION:{_esc(sec.classroom)}",
                f"DESCRIPTION:{_esc('授課老師 ' + sec.teacher_name + '（來自課拼 CoursePuzzle）')}",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"
