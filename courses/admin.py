from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import (Announcement, CampusEvent, ClassTime, Course, Department, Enrollment,
                     EventSignup, Notification, Profile, Review, Section, Semester,
                     SocialIdentity, Todo, Waitlist)

admin.site.site_header = "課拼 CoursePuzzle 教務後台"
admin.site.site_title = "課拼後台"
admin.site.index_title = "課程、公告、活動與使用者管理"


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


class UserAdminWithProfile(UserAdmin):
    inlines = [ProfileInline]


admin.site.unregister(User)
admin.site.register(User, UserAdminWithProfile)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "college"]
    search_fields = ["name"]


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ["name", "is_current", "start_date", "enroll_open", "enroll_close", "max_credits"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "department", "category", "credits"]
    list_filter = ["department", "category", "credits"]
    search_fields = ["code", "name"]


class ClassTimeInline(admin.TabularInline):
    model = ClassTime
    extra = 1


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ["course", "semester", "teacher", "classroom", "capacity", "taken", "is_active"]
    list_filter = ["semester", "is_active", "course__department"]
    search_fields = ["course__name", "course__code"]
    inlines = [ClassTimeInline]

    @admin.display(description="已選人數")
    def taken(self, obj):
        return obj.enrollments.count()


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["student", "section", "created_at"]
    list_filter = ["section__semester"]
    search_fields = ["student__username", "section__course__name"]


@admin.register(Waitlist)
class WaitlistAdmin(admin.ModelAdmin):
    list_display = ["student", "section", "created_at"]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["course", "student", "rating", "created_at"]
    list_filter = ["rating"]


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "is_pinned", "created_at"]
    list_filter = ["category", "is_pinned"]


@admin.register(CampusEvent)
class CampusEventAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "start", "location", "capacity"]
    list_filter = ["category"]


@admin.register(EventSignup)
class EventSignupAdmin(admin.ModelAdmin):
    list_display = ["event", "student", "created_at"]


@admin.register(SocialIdentity)
class SocialIdentityAdmin(admin.ModelAdmin):
    list_display = ["user", "provider", "email", "created_at"]


admin.site.register(Todo)
admin.site.register(Notification)
