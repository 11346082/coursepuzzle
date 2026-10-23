from .models import Notification
from .services import current_semester, role_of
from .timeutils import WEEKDAY_IDS, WEEKDAY_NAMES


def site(request):
    user = request.user
    name, unread = "", 0
    if user.is_authenticated:
        name = (user.last_name + user.first_name) or user.get_username()
        unread = Notification.objects.filter(user=user, is_read=False).count()
    return {
        "role": role_of(user),
        "semester": current_semester(),
        "display_name": name,
        "avatar_initial": name[:1],
        "unread_count": unread,
        "weekday_names": [WEEKDAY_NAMES[d] for d in WEEKDAY_IDS],
    }
