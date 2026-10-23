#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate



#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py shell -c "from django.db import connection; from courses.models import Course, Section, Announcement, CampusEvent; print('DATABASE_VENDOR:', connection.vendor); print('DATA_COUNTS:', {'courses': Course.objects.count(), 'sections': Section.objects.count(), 'announcements': Announcement.objects.count(), 'events': CampusEvent.objects.count()})"
python manage.py shell -c "from django.contrib.auth.models import User; print('USER_COUNTS:', {'users': User.objects.count(), 'admins': User.objects.filter(is_superuser=True).count()})"