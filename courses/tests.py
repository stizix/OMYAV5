from django.contrib.auth import get_user_model
from courses.models import Course

User = get_user_model()
c = Course.objects.get(pk=2)          # <- l'ID de l'URL admin
print("course.id =", c.id, "user_id =", c.user_id)
print("user_exists =", User.objects.filter(id=c.user_id).exists())
