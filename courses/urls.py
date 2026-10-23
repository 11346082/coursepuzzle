from django.urls import path

from . import social, views

urlpatterns = [
    path("", views.home, name="home"),
    # 選課
    path("courses/", views.course_list, name="course_list"),
    path("course/<int:pk>/", views.course_detail, name="course_detail"),
    path("course/<int:pk>/review/", views.review_view, name="review"),
    path("section/<int:pk>/enroll/", views.enroll_view, name="enroll"),
    path("section/<int:pk>/drop/", views.drop_view, name="drop"),
    path("section/<int:pk>/waitlist/", views.waitlist_view, name="waitlist"),
    path("section/<int:pk>/favorite/", views.favorite_view, name="favorite"),
    path("enroll-many/", views.enroll_many_view, name="enroll_many"),
    path("me/schedule/", views.my_schedule, name="my_schedule"),
    path("me/schedule.ics", views.schedule_ics, name="schedule_ics"),
    path("me/favorites/", views.favorites, name="favorites"),
    path("me/planner/", views.planner, name="planner"),
    # 校園
    path("news/", views.news, name="news"),
    path("events/", views.events, name="events"),
    path("events/<int:pk>/signup/", views.event_signup, name="event_signup"),
    path("calendar/", views.campus_calendar, name="calendar"),
    # 個人
    path("me/todos/", views.todos, name="todos"),
    path("me/todos/<int:pk>/toggle/", views.todo_toggle, name="todo_toggle"),
    path("me/todos/<int:pk>/delete/", views.todo_delete, name="todo_delete"),
    path("me/notifications/", views.notifications, name="notifications"),
    path("me/profile/", views.profile_view, name="profile"),
    # 雲端登入
    path("auth/<str:provider>/", social.start, name="social_start"),
    path("auth/<str:provider>/callback/", social.callback, name="social_callback"),
    # 老師
    path("teacher/", views.teacher_dashboard, name="teacher_dashboard"),
    path("teacher/section/<int:pk>/", views.teacher_section, name="teacher_section"),
    path("teacher/section/<int:pk>/export/", views.teacher_export, name="teacher_export"),
]
