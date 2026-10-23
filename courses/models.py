from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .timeutils import PERIODS, WEEKDAY_NAMES, expand, label

User = settings.AUTH_USER_MODEL


class Department(models.Model):
    name = models.CharField("系所", max_length=50, unique=True)
    college = models.CharField("所屬學院", max_length=50, blank=True)

    class Meta:
        verbose_name = "系所"
        verbose_name_plural = "系所"

    def __str__(self):
        return self.name


class Profile(models.Model):
    ROLES = [("student", "學生"), ("teacher", "老師"), ("staff", "教職員")]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField("身分", max_length=10, choices=ROLES, default="student")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="系所")
    student_no = models.CharField("學號", max_length=20, blank=True)

    class Meta:
        verbose_name = "身分資料"
        verbose_name_plural = "身分資料"

    def __str__(self):
        return f"{self.user} ({self.get_role_display()})"


class SocialIdentity(models.Model):
    """雲端帳號（Google、Microsoft）與本系統使用者的對應。"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="social_identities")
    provider = models.CharField("登入服務", max_length=20)
    uid = models.CharField("服務端使用者代號", max_length=255)
    email = models.EmailField("信箱", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "雲端登入綁定"
        verbose_name_plural = "雲端登入綁定"
        unique_together = [("provider", "uid")]

    def __str__(self):
        return f"{self.provider}:{self.email or self.uid}"


class Semester(models.Model):
    name = models.CharField("學期", max_length=20, unique=True)  # 例如 115-1
    is_current = models.BooleanField("目前學期", default=False)
    start_date = models.DateField("開學日", null=True, blank=True)
    end_date = models.DateField("學期結束日", null=True, blank=True)
    enroll_open = models.DateTimeField("選課開始", null=True, blank=True)
    enroll_close = models.DateTimeField("選課截止", null=True, blank=True)
    max_credits = models.PositiveSmallIntegerField("學分上限", default=25)

    class Meta:
        verbose_name = "學期"
        verbose_name_plural = "學期"
        ordering = ["-name"]

    def __str__(self):
        return self.name

    def enrollment_state(self):
        """回傳 (是否開放, 說明文字)。"""
        now = timezone.now()
        if self.enroll_open and now < self.enroll_open:
            return False, "選課尚未開放"
        if self.enroll_close and now > self.enroll_close:
            return False, "選課已截止"
        return True, ""


class Course(models.Model):
    CATEGORIES = [("required", "必修"), ("elective", "選修"), ("general", "通識"), ("pe", "體育")]

    code = models.CharField("課號", max_length=20, unique=True)
    name = models.CharField("課名", max_length=100)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, verbose_name="開課系所")
    credits = models.PositiveSmallIntegerField("學分", default=3)
    category = models.CharField("課別", max_length=10, choices=CATEGORIES, default="required")
    description = models.TextField("課程簡介", blank=True)
    objectives = models.TextField("學習目標（一行一項）", blank=True)
    grading = models.TextField("評量方式", blank=True)
    textbook = models.TextField("教材與參考書", blank=True)

    class Meta:
        verbose_name = "課程"
        verbose_name_plural = "課程"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def objective_lines(self):
        return [ln.strip() for ln in self.objectives.splitlines() if ln.strip()]


class Section(models.Model):
    """開課資料：某門課在某學期由誰教、在哪上、幾個人。"""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="sections", verbose_name="課程")
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="sections", verbose_name="學期")
    teacher = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="teaching_sections", verbose_name="授課老師",
        limit_choices_to={"profile__role": "teacher"},
    )
    classroom = models.CharField("教室", max_length=50, blank=True)
    capacity = models.PositiveSmallIntegerField("人數上限", default=40)
    outline = models.TextField("每週進度大綱", blank=True)
    announcement = models.TextField("老師公告", blank=True)
    is_active = models.BooleanField("開放（取消勾選即下架）", default=True)

    class Meta:
        verbose_name = "開課"
        verbose_name_plural = "開課"
        unique_together = [("course", "semester")]

    def __str__(self):
        return f"{self.semester} {self.course.name}"

    @property
    def teacher_name(self):
        t = self.teacher
        if not t:
            return "未指派"
        return (t.last_name + t.first_name) or t.get_username()

    def seats_taken(self):
        n = getattr(self, "enrolled_n", None)
        return n if n is not None else self.enrollments.count()

    def is_full(self):
        return self.seats_taken() >= self.capacity


class ClassTime(models.Model):
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="times")
    weekday = models.PositiveSmallIntegerField("星期", choices=list(WEEKDAY_NAMES.items()))
    start_period = models.PositiveSmallIntegerField(
        "開始節次", validators=[MinValueValidator(PERIODS[0]), MaxValueValidator(PERIODS[-1])])
    end_period = models.PositiveSmallIntegerField(
        "結束節次", validators=[MinValueValidator(PERIODS[0]), MaxValueValidator(PERIODS[-1])])

    class Meta:
        verbose_name = "上課時段"
        verbose_name_plural = "上課時段"
        ordering = ["weekday", "start_period"]

    def clean(self):
        if self.start_period and self.end_period and self.end_period < self.start_period:
            raise ValidationError("結束節次不能早於開始節次")

    def slots(self):
        return expand(self.weekday, self.start_period, self.end_period)

    def label(self):
        return label(self.weekday, self.start_period, self.end_period)

    def __str__(self):
        return self.label()


class Enrollment(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrollments", verbose_name="學生")
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="enrollments", verbose_name="開課")
    created_at = models.DateTimeField("加選時間", auto_now_add=True)

    class Meta:
        verbose_name = "選課紀錄"
        verbose_name_plural = "選課紀錄"
        unique_together = [("student", "section")]

    def __str__(self):
        return f"{self.student} → {self.section}"


class Favorite(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="favorites")
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="favorited_by")

    class Meta:
        unique_together = [("student", "section")]


class Waitlist(models.Model):
    """額滿後的候補名單，有人退選時依登記順序自動遞補。"""

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="waitlists", verbose_name="學生")
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="waitlist_entries", verbose_name="開課")
    created_at = models.DateTimeField("登記時間", auto_now_add=True)

    class Meta:
        verbose_name = "候補名單"
        verbose_name_plural = "候補名單"
        unique_together = [("student", "section")]
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.student} 候補 {self.section}"


class Review(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reviews")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField("評分", validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField("心得", blank=True, max_length=500)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "課程心得"
        verbose_name_plural = "課程心得"
        unique_together = [("student", "course")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.course.name} {self.rating} 星"


class Announcement(models.Model):
    CATEGORIES = [("academic", "教務"), ("student", "學務"), ("activity", "活動"),
                  ("scholarship", "獎助"), ("system", "系統")]

    title = models.CharField("標題", max_length=120)
    content = models.TextField("內容")
    category = models.CharField("分類", max_length=12, choices=CATEGORIES, default="academic")
    is_pinned = models.BooleanField("置頂", default=False)
    created_at = models.DateTimeField("發布時間", default=timezone.now)

    class Meta:
        verbose_name = "公告"
        verbose_name_plural = "公告"
        ordering = ["-is_pinned", "-created_at"]

    def __str__(self):
        return self.title


class CampusEvent(models.Model):
    CATEGORIES = [("lecture", "講座"), ("club", "社團"), ("contest", "競賽"), ("career", "就業"),
                  ("sports", "體育"), ("service", "服務學習"), ("academic", "教務")]

    title = models.CharField("活動名稱", max_length=120)
    description = models.TextField("活動說明", blank=True)
    category = models.CharField("分類", max_length=10, choices=CATEGORIES, default="lecture")
    location = models.CharField("地點", max_length=80, blank=True)
    organizer = models.CharField("主辦單位", max_length=60, blank=True)
    start = models.DateTimeField("開始時間")
    end = models.DateTimeField("結束時間", null=True, blank=True)
    capacity = models.PositiveIntegerField("名額（0 代表不限）", default=0)

    class Meta:
        verbose_name = "校園活動"
        verbose_name_plural = "校園活動"
        ordering = ["start"]

    def __str__(self):
        return self.title

    def signup_count(self):
        n = getattr(self, "signup_n", None)
        return n if n is not None else self.signups.count()

    def is_full(self):
        return bool(self.capacity) and self.signup_count() >= self.capacity


class EventSignup(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="event_signups")
    event = models.ForeignKey(CampusEvent, on_delete=models.CASCADE, related_name="signups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "活動報名"
        verbose_name_plural = "活動報名"
        unique_together = [("student", "event")]


class Todo(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="todos")
    title = models.CharField("待辦事項", max_length=120)
    due_date = models.DateField("期限", null=True, blank=True)
    is_done = models.BooleanField("完成", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "待辦事項"
        verbose_name_plural = "待辦事項"

    def __str__(self):
        return self.title


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    text = models.CharField("內容", max_length=200)
    url = models.CharField("連結", max_length=200, blank=True)
    is_read = models.BooleanField("已讀", default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "通知"
        verbose_name_plural = "通知"
        ordering = ["-created_at"]

    def __str__(self):
        return self.text
