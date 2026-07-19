from django.contrib import admin
from infrastructure.persistence.users.models import UserProfile 
from .models import Post, Comment, ThreadModel, MessageModel

admin.site.register(Post)
admin.site.register(UserProfile)
admin.site.register(Comment)
admin.site.register(ThreadModel)
admin.site.register(MessageModel)
