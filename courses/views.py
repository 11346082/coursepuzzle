import calendar
import csv
from collections import Counter, defaultdict
from functools import wraps

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Q
from django.db.models.functions import Concat
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services, social
from .forms import ProfileForm, ReviewForm, SectionTeacherForm, TodoForm
from .models import (Announcement, CampusEvent, ClassTime, Course, Department, Enrollment,
                     EventSignup, Favorite, Notification, Profile, Review, Section, Todo, Waitlist)
from .services import StudentContext, base_sections, current_semester, role_of
from .timeutils import WEEKDAY_NAMES, time_range

ROLE_NAMES = {"student": "學生", "teacher": "老師", "staff": "教職員"}


def role_required(role):
    def deco(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if role_of(request.user) != role:
                return render(request, "forbidden.html", {"need": ROLE_NAMES[role]}, status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return deco


def go_back(request, default="course_list"):
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(nxt)
    return redirect(default)


def mark_status(request, sections):
    """替每個開課加上 state / reason / is_fav，讓模板決定按鈕長相。"""
    if role_of(request.user) == "student":
        return services.attach_status(request.user, current_semester(), sections)
    for s in sections:
        s.state, s.reason, s.is_fav = "anon", "", False
    return None


def stars(n):
    return "★" * n + "☆" * (5 - n)


# ---------- 登入 ----------

class CoursePuzzleLoginView(auth_views.LoginView):
    template_name = "login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["providers"] = social.provider_list()
        return ctx


# ---------- 首頁 ----------

def home(request):
    semester = current_semester()
    now = timezone.now()
    sections = Section.objects.filter(is_active=True, semester=semester)
    stats = {
        "sections": sections.count(),
        "teachers": Profile.objects.filter(role="teacher").count(),
        "departments": Department.objects.count(),
        "events": CampusEvent.objects.filter(start__gte=now).count(),
    }

    summary, today_classes, my_todos = None, [], []
    if role_of(request.user) == "student" and semester:
        ctx = StudentContext(request.user, semester)
        limit = semester.max_credits
        summary = {
            "count": len(ctx.enrolled), "credits": ctx.credits, "limit": limit,
            "pct": min(100, round(ctx.credits * 100 / limit)) if limit else 0,
        }
        weekday = timezone.localdate().isoweekday()
        for sec in ctx.enrolled:
            for t in sec.times.all():
                if t.weekday == weekday:
                    today_classes.append({
                        "start": t.start_period, "section": sec,
                        "time": time_range(t.start_period, t.end_period)})
        today_classes.sort(key=lambda c: c["start"])
        my_todos = list(Todo.objects.filter(user=request.user, is_done=False)
                        .order_by(F("due_date").asc(nulls_last=True), "-created_at")[:4])

    is_open, open_msg = semester.enrollment_state() if semester else (False, "尚未設定學期")
    return render(request, "home.html", {
        "stats": stats, "summary": summary, "is_open": is_open, "open_msg": open_msg,
        "today_classes": today_classes, "my_todos": my_todos,
        "today_name": WEEKDAY_NAMES.get(timezone.localdate().isoweekday(), "週末"),
        "is_weekend": timezone.localdate().isoweekday() > 5,
        "announcements": Announcement.objects.all()[:4],
        "upcoming": CampusEvent.objects.filter(start__gte=now)
                    .annotate(signup_n=Count("signups")).order_by("start")[:3],
        "popular": base_sections().filter(semester=semester).order_by("-enrolled_n", "course__code")[:4],
    })


# ---------- 找課 ----------

def course_list(request):
    semester = current_semester()
    qs = base_sections().filter(semester=semester).annotate(
        tname=Concat("teacher__last_name", "teacher__first_name"))

    q = request.GET.get("q", "").strip()
    dept = request.GET.get("dept", "")
    credits = request.GET.get("credits", "")
    category = request.GET.get("category", "")
    avoid = request.GET.get("avoid", "")
    no_early = bool(request.GET.get("no_early"))
    no_lunch = bool(request.GET.get("no_lunch"))
    has_seats = bool(request.GET.get("has_seats"))

    if q:
        qs = qs.filter(
            Q(course__name__icontains=q) | Q(course__code__icontains=q)
            | Q(tname__icontains=q) | Q(teacher__username__icontains=q))
    if dept.isdigit():
        qs = qs.filter(course__department_id=int(dept))
    if credits.isdigit():
        qs = qs.filter(course__credits=int(credits))
    if category in dict(Course.CATEGORIES):
        qs = qs.filter(course__category=category)
    if avoid.isdigit():  # 空堂導向：整天不想上課的星期
        qs = qs.exclude(times__weekday=int(avoid))
    if no_early:
        qs = qs.exclude(pk__in=ClassTime.objects.filter(start_period=1).values("section_id"))
    if no_lunch:
        qs = qs.exclude(pk__in=ClassTime.objects.filter(
            start_period__lte=5, end_period__gte=5).values("section_id"))
    if has_seats:
        qs = qs.filter(enrolled_n__lt=F("capacity"))

    sections = list(qs.order_by("course__code"))
    mark_status(request, sections)
    return render(request, "list.html", {
        "sections": sections,
        "departments": Department.objects.all(),
        "weekdays": WEEKDAY_NAMES.items(),
        "credit_options": [1, 2, 3, 4],
        "categories": Course.CATEGORIES,
        "q": q, "dept": dept, "credits": credits, "category": category, "avoid": avoid,
        "no_early": no_early, "no_lunch": no_lunch, "has_seats": has_seats,
    })


def course_detail(request, pk):
    course = get_object_or_404(Course.objects.select_related("department"), pk=pk)
    sections = list(base_sections().filter(course=course, semester=current_semester()))
    mark_status(request, sections)

    reviews = list(course.reviews.select_related("student")[:10])
    for r in reviews:
        r.stars = stars(r.rating)
        r.who = (r.student.last_name or "匿名") + "同學"
    agg = course.reviews.aggregate(avg=Avg("rating"), n=Count("id"))
    avg = round(agg["avg"], 1) if agg["avg"] else None

    student_ids = Enrollment.objects.filter(section__course=course).values("student_id")
    also_took = (Enrollment.objects.filter(student_id__in=student_ids).exclude(section__course=course)
                 .values("section__course_id", "section__course__name")
                 .annotate(n=Count("id")).order_by("-n")[:5])

    can_review, my_review, form = False, None, None
    if role_of(request.user) == "student":
        can_review = Enrollment.objects.filter(student=request.user, section__course=course).exists()
        my_review = Review.objects.filter(student=request.user, course=course).first()
        if can_review:
            form = ReviewForm(initial={"rating": my_review.rating, "comment": my_review.comment}
                              if my_review else None)
    return render(request, "detail.html", {
        "course": course, "sections": sections, "objectives": course.objective_lines(),
        "reviews": reviews, "review_avg": avg, "review_avg_stars": stars(round(avg)) if avg else "",
        "review_count": agg["n"], "also_took": also_took,
        "can_review": can_review, "my_review": my_review, "review_form": form,
    })


@role_required("student")
@require_POST
def review_view(request, pk):
    course = get_object_or_404(Course, pk=pk)
    if not Enrollment.objects.filter(student=request.user, section__course=course).exists():
        messages.error(request, "加選過這門課之後才能留下心得")
        return redirect("course_detail", pk=pk)
    form = ReviewForm(request.POST)
    if form.is_valid():
        Review.objects.update_or_create(
            student=request.user, course=course,
            defaults={"rating": int(form.cleaned_data["rating"]), "comment": form.cleaned_data["comment"],
                      "created_at": timezone.now()})
        messages.success(request, "謝謝你的心得，下一屆同學會看到")
    else:
        messages.error(request, "心得內容有誤，請再檢查一次")
    return redirect("course_detail", pk=pk)


# ---------- 學生：加退選、候補、收藏、課表 ----------

@role_required("student")
@require_POST
def enroll_view(request, pk):
    ok, msg = services.enroll(request.user, pk)
    (messages.success if ok else messages.error)(request, msg)
    return go_back(request)


@role_required("student")
@require_POST
def drop_view(request, pk):
    ok, msg = services.drop(request.user, pk)
    (messages.success if ok else messages.error)(request, msg)
    return go_back(request, "my_schedule")


@role_required("student")
@require_POST
def waitlist_view(request, pk):
    if Waitlist.objects.filter(student=request.user, section_id=pk).exists():
        ok, msg = services.leave_waitlist(request.user, pk)
    else:
        ok, msg = services.join_waitlist(request.user, pk)
    (messages.success if ok else messages.error)(request, msg)
    return go_back(request)


@role_required("student")
@require_POST
def favorite_view(request, pk):
    section = get_object_or_404(Section, pk=pk, is_active=True)
    fav, created = Favorite.objects.get_or_create(student=request.user, section=section)
    if not created:
        fav.delete()
    return go_back(request)


@role_required("student")
@require_POST
def enroll_many_view(request):
    """一鍵選課：收藏清單與智慧排課共用。"""
    ids = []
    for x in request.POST.getlist("section_ids"):
        if x.isdigit() and int(x) not in ids:
            ids.append(int(x))
    if not ids:
        messages.error(request, "沒有可以加選的課")
        return go_back(request, "my_schedule")
    done, failed = services.enroll_many(request.user, ids)
    if done:
        messages.success(request, f"一鍵選課完成，已加選 {len(done)} 門：{'、'.join(done)}")
    for msg in failed:
        messages.error(request, msg)
    return go_back(request, "my_schedule")


@role_required("student")
def my_schedule(request):
    semester = current_semester()
    ctx = StudentContext(request.user, semester)

    preview, preview_state, preview_reason = None, "", ""
    pid = request.GET.get("preview", "")
    if pid.isdigit():
        preview = base_sections().filter(pk=int(pid), semester=semester).first()
        if preview and preview.pk in ctx.enrolled_ids:
            preview = None
        if preview:
            preview_state, preview_reason = ctx.status(preview)

    limit = semester.max_credits if semester else 25
    per_day = Counter(day for day, _ in ctx.slot_owner)
    waiting = list(Section.objects.filter(waitlist_entries__student=request.user, semester=semester)
                   .select_related("course"))
    return render(request, "schedule.html", {
        "rows": services.build_grid(ctx.enrolled, preview),
        "enrolled": ctx.enrolled,
        "credits": ctx.credits,
        "credit_limit": limit,
        "credit_pct": min(100, round(ctx.credits * 100 / limit)) if limit else 0,
        "school_days": len(per_day),
        "max_daily": max(per_day.values(), default=0),
        "breakdown": services.category_breakdown(ctx.enrolled),
        "waiting": waiting,
        "preview": preview,
        "preview_state": preview_state,
        "preview_reason": preview_reason,
    })


@role_required("student")
def schedule_ics(request):
    semester = current_semester()
    response = HttpResponse(services.build_ics(request.user, semester),
                            content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="coursepuzzle-{semester.name}.ics"'
    return response


@role_required("student")
def favorites(request):
    sections = list(base_sections().filter(favorited_by__student=request.user)
                    .filter(semester=current_semester()).order_by("course__code"))
    mark_status(request, sections)
    available = [s for s in sections if s.state == "available"]
    return render(request, "favorites.html", {"sections": sections, "available": available})


@role_required("student")
def planner(request):
    """智慧排課：依條件產生最多三套不衝堂的方案，可一鍵套用。"""
    semester = current_semester()
    ctx = StudentContext(request.user, semester)
    limit = semester.max_credits

    try:
        target = int(request.GET.get("credits", min(18, limit)))
    except ValueError:
        target = min(18, limit)
    target = max(1, min(target, limit))
    avoid = request.GET.get("avoid", "")
    avoid_day = int(avoid) if avoid.isdigit() else None
    submitted = bool(request.GET)
    no_early = bool(request.GET.get("no_early")) if submitted else True
    no_lunch = bool(request.GET.get("no_lunch")) if submitted else False

    candidates = services.candidate_sections(ctx, avoid_day, no_early, no_lunch)
    plans = services.generate_plans(ctx, candidates, target) if ctx.credits < target else []
    return render(request, "planner.html", {
        "plans": plans,
        "target": target,
        "credits_now": ctx.credits,
        "credit_choices": range(6, limit + 1, 3) if limit >= 6 else [limit],
        "weekdays": WEEKDAY_NAMES.items(),
        "avoid": avoid, "no_early": no_early, "no_lunch": no_lunch,
        "already_enough": ctx.credits >= target,
    })


# ---------- 校園：公告、活動、日曆 ----------

def news(request):
    cat = request.GET.get("cat", "")
    items = Announcement.objects.all()
    if cat in dict(Announcement.CATEGORIES):
        items = items.filter(category=cat)
    return render(request, "news.html", {
        "items": items, "categories": Announcement.CATEGORIES, "cat": cat})


def events(request):
    cat = request.GET.get("cat", "")
    mine = bool(request.GET.get("mine")) and role_of(request.user) == "student"
    qs = (CampusEvent.objects.filter(start__date__gte=timezone.localdate())
          .annotate(signup_n=Count("signups")).order_by("start"))
    if cat in dict(CampusEvent.CATEGORIES):
        qs = qs.filter(category=cat)
    signed = set()
    if role_of(request.user) == "student":
        signed = set(EventSignup.objects.filter(student=request.user).values_list("event_id", flat=True))
    if mine:
        qs = qs.filter(pk__in=signed)
    items = list(qs)
    for e in items:
        e.signed = e.pk in signed
    return render(request, "events.html", {
        "items": items, "categories": CampusEvent.CATEGORIES, "cat": cat, "mine": mine})


@role_required("student")
@require_POST
def event_signup(request, pk):
    event = get_object_or_404(CampusEvent, pk=pk)
    existing = EventSignup.objects.filter(student=request.user, event=event).first()
    if existing:
        existing.delete()
        messages.success(request, f"已取消報名「{event.title}」")
    elif event.is_full():
        messages.error(request, f"「{event.title}」名額已滿")
    else:
        EventSignup.objects.create(student=request.user, event=event)
        when = timezone.localtime(event.start).strftime("%m/%d %H:%M")
        services.notify(request.user, f"已報名「{event.title}」，{when} 在 {event.location or '待公布'}",
                        reverse("events"))
        messages.success(request, f"報名成功：{event.title}")
    return go_back(request, "events")


def campus_calendar(request):
    today = timezone.localdate()
    year, month = today.year, today.month
    m = request.GET.get("m", "")
    if len(m) == 7 and m[4] == "-" and m[:4].isdigit() and m[5:].isdigit() and 1 <= int(m[5:]) <= 12:
        year, month = int(m[:4]), int(m[5:])

    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    first_day, last_day = weeks[0][0], weeks[-1][-1]
    items = defaultdict(list)

    for e in CampusEvent.objects.filter(start__date__gte=first_day, start__date__lte=last_day):
        local = timezone.localtime(e.start)
        items[local.date()].append({"kind": "event", "title": e.title, "time": local.strftime("%H:%M"),
                                    "url": f"{reverse('events')}#e{e.pk}"})
    semester = current_semester()
    if semester:
        marks = [(semester.start_date, "開學"), (semester.end_date, "學期結束")]
        if semester.enroll_open:
            marks.append((timezone.localtime(semester.enroll_open).date(), "選課開始"))
        if semester.enroll_close:
            marks.append((timezone.localtime(semester.enroll_close).date(), "選課截止"))
        for d, text in marks:
            if d:
                items[d].append({"kind": "milestone", "title": text, "time": "", "url": reverse("course_list")})
    if role_of(request.user) == "student":
        for t in Todo.objects.filter(user=request.user, is_done=False, due_date__range=(first_day, last_day)):
            items[t.due_date].append({"kind": "todo", "title": t.title, "time": "", "url": reverse("todos")})

    rows = [[{"date": d, "in_month": d.month == month, "is_today": d == today, "items": items.get(d, [])}
             for d in week] for week in weeks]
    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)
    return render(request, "calendar.html", {
        "rows": rows, "title": f"{year} 年 {month} 月",
        "prev": f"{prev_y}-{prev_m:02d}", "next": f"{next_y}-{next_m:02d}",
        "this_month": f"{today.year}-{today.month:02d}",
        "heads": ["日", "一", "二", "三", "四", "五", "六"],
    })


# ---------- 學生：待辦、通知、個人資料 ----------

@role_required("student")
def todos(request):
    form = TodoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        todo = form.save(commit=False)
        todo.user = request.user
        todo.save()
        messages.success(request, "已加入待辦")
        return redirect("todos")
    mine = Todo.objects.filter(user=request.user)
    return render(request, "todos.html", {
        "form": form,
        "open_items": mine.filter(is_done=False).order_by(F("due_date").asc(nulls_last=True), "-created_at"),
        "done_items": mine.filter(is_done=True).order_by("-created_at")[:10],
        "today": timezone.localdate(),
    })


@role_required("student")
@require_POST
def todo_toggle(request, pk):
    todo = get_object_or_404(Todo, pk=pk, user=request.user)
    todo.is_done = not todo.is_done
    todo.save(update_fields=["is_done"])
    return redirect("todos")


@role_required("student")
@require_POST
def todo_delete(request, pk):
    get_object_or_404(Todo, pk=pk, user=request.user).delete()
    return redirect("todos")


@login_required
def notifications(request):
    items = list(Notification.objects.filter(user=request.user)[:50])
    for n in items:
        n.is_new = not n.is_read
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return render(request, "notifications.html", {"items": items})


@login_required
def profile_view(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user, defaults={"role": role_of(user)})
    form = ProfileForm(request.POST or None, initial={
        "last_name": user.last_name, "first_name": user.first_name,
        "department": profile.department, "student_no": profile.student_no})
    if request.method == "POST" and form.is_valid():
        user.last_name = form.cleaned_data["last_name"]
        user.first_name = form.cleaned_data["first_name"]
        user.save(update_fields=["last_name", "first_name"])
        profile.department = form.cleaned_data["department"]
        profile.student_no = form.cleaned_data["student_no"]
        profile.save()
        messages.success(request, "個人資料已更新")
        return redirect("profile")
    return render(request, "profile.html", {
        "form": form, "profile": profile,
        "identities": user.social_identities.all(), "has_password": user.has_usable_password(),
    })


# ---------- 老師 ----------

@role_required("teacher")
def teacher_dashboard(request):
    sections = base_sections().filter(teacher=request.user)
    return render(request, "teacher/dashboard.html", {"sections": sections})


@role_required("teacher")
def teacher_section(request, pk):
    section = get_object_or_404(base_sections(), pk=pk, teacher=request.user)
    form = SectionTeacherForm(request.POST or None, instance=section)
    if request.method == "POST" and form.is_valid():
        form.save()
        promoted = services.promote_waitlist(section)  # 調高名額時，候補同學自動遞補
        msg = "已儲存課程資料"
        if promoted:
            msg += f"，候補同學 {len(promoted)} 人已自動加選"
        messages.success(request, msg)
        return redirect("teacher_section", pk=pk)
    roster = section.enrollments.select_related("student__profile").order_by("student__username")
    waiting = section.waitlist_entries.select_related("student").order_by("created_at")
    return render(request, "teacher/section.html", {
        "section": section, "form": form, "roster": roster, "waiting": waiting})


@role_required("teacher")
def teacher_export(request, pk):
    section = get_object_or_404(Section.objects.select_related("course"), pk=pk, teacher=request.user)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="roster-{section.course.code}.csv"'
    response.write("\ufeff")  # 讓 Excel 正確顯示中文
    writer = csv.writer(response)
    writer.writerow(["學號", "帳號", "姓名", "加選時間"])
    for e in section.enrollments.select_related("student__profile").order_by("student__username"):
        u = e.student
        profile = getattr(u, "profile", None)
        writer.writerow([
            profile.student_no if profile else "", u.get_username(),
            (u.last_name + u.first_name) or u.get_username(),
            e.created_at.strftime("%Y-%m-%d %H:%M"),
        ])
    return response
