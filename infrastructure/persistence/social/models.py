from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from infrastructure.persistence.users.models import CustomUser

class Post(models.Model):
	VISIBILITY_WORKSPACE = 'workspace'
	VISIBILITY_TEAM = 'team'
	VISIBILITY_PUBLIC = 'public'
	VISIBILITY_CHOICES = (
		(VISIBILITY_WORKSPACE, 'Workspace'),
		(VISIBILITY_TEAM, 'Team'),
		(VISIBILITY_PUBLIC, 'Public'),
	)

	shared_body = models.TextField(blank=True, null=True)
	body = models.TextField()
	image = models.ManyToManyField('Image', blank=True)
	created_on = models.DateTimeField(default=timezone.now)
	shared_on = models.DateTimeField(blank=True, null=True)
	edited_on = models.DateTimeField(blank=True, null=True)
	author = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
	shared_user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	# Feed scoping. ``workspace`` is set for every post that belongs to a
	# workspace or teamspace feed. ``team`` is additionally set when the
	# post is scoped to a single team within that workspace. Legacy global
	# posts (pre-feed-feature) have both as NULL.
	workspace = models.ForeignKey(
		'workspaces.Workspace',
		on_delete=models.CASCADE,
		null=True,
		blank=True,
		related_name='posts',
	)
	team = models.ForeignKey(
		'team.Team',
		on_delete=models.CASCADE,
		null=True,
		blank=True,
		related_name='posts',
	)
	visibility = models.CharField(
		max_length=16,
		choices=VISIBILITY_CHOICES,
		default=VISIBILITY_WORKSPACE,
	)
	is_pinned = models.BooleanField(default=False)
	is_deleted = models.BooleanField(default=False)
	likes = models.ManyToManyField(CustomUser, blank=True, related_name='likes')
	dislikes = models.ManyToManyField(CustomUser, blank=True, related_name='dislikes')
	tags = models.ManyToManyField('Tag', blank=True)

	def create_tags(self):
		for word in self.body.split():
			if (word[0] == '#'):
				tag = Tag.objects.filter(name=word[1:]).first()
				if tag:
					self.tags.add(tag.pk)
				else:
					tag = Tag(name=word[1:])
					tag.save()
					self.tags.add(tag.pk)
				self.save()

		if self.shared_body:
			for word in self.shared_body.split():
				if (word[0] == '#'):
					tag = Tag.objects.filter(name=word[1:]).first()
					if tag:
						self.tags.add(tag.pk)
					else:
						tag = Tag(name=word[1:])
						tag.save()
						self.tags.add(tag.pk)
					self.save()

	class Meta:
		ordering = ['-created_on', '-shared_on']
		indexes = [
			models.Index(fields=['workspace', '-created_on']),
			models.Index(fields=['team', '-created_on']),
			models.Index(fields=['author', '-created_on']),
		]

class Comment(models.Model):
 	comment = models.TextField()
 	created_on = models.DateTimeField(default=timezone.now)
 	edited_on = models.DateTimeField(blank=True, null=True)
 	is_deleted = models.BooleanField(default=False)
 	author = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
 	# Either ``post`` (legacy social-feed scope) OR ``content_type`` +
 	# ``object_id`` (generic attachment, e.g. RecipientUpdate) must be set,
 	# not both. ``post`` is kept for backward compatibility with existing
 	# workspace feed comments.
 	post = models.ForeignKey('Post', on_delete=models.CASCADE, null=True, blank=True)
 	content_type = models.ForeignKey(
 		ContentType,
 		on_delete=models.CASCADE,
 		null=True,
 		blank=True,
 		related_name='social_comments',
 	)
 	# CharField (not PositiveIntegerField) so we can attach to UUID-keyed
 	# models like RecipientUpdate as well as integer-keyed legacy ones.
 	object_id = models.CharField(max_length=64, null=True, blank=True)
 	content_object = GenericForeignKey('content_type', 'object_id')
 	likes = models.ManyToManyField(CustomUser, blank=True, related_name='comment_likes')
 	dislikes = models.ManyToManyField(CustomUser, blank=True, related_name='comment_dislikes')
 	parent = models.ForeignKey('self', on_delete=models.CASCADE, blank=True, null=True, related_name='+')
 	tags = models.ManyToManyField('Tag', blank=True)

 	class Meta:
 		indexes = [
 			models.Index(fields=['content_type', 'object_id']),
 			models.Index(fields=['post', '-created_on']),
 			models.Index(fields=['parent', '-created_on']),
 		]

 	def create_tags(self):
 		for word in self.comment.split():
 			if (word[0] == '#'):
 				tag = Tag.objects.get(name=word[1:])
 				if tag:
 					self.tags.add(tag.pk)
 				else:
 					tag = Tag(name=word[1:])
 					tag.save()
 					self.tags.add(tag.pk)
 				self.save()

 	@property
 	def recipients(self):
 		return Comment.objects.filter(parent=self).order_by('-created_on').all()

 	@property
 	def is_parent(self):
 		if self.parent is None:
 			return True
 		return False

# UserProfile signals moved to components/identity/infrastructure/adapters/
# django_user_profile_signal_bridge.py (registered via apps/users/apps.py)

class ThreadModel(models.Model):
	user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='+')
	receiver = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='+')
	# Add workspace context for organization-based messaging
	workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, null=True, blank=True, related_name='message_threads')
	thread_type = models.CharField(max_length=20, choices=[
		('private', 'Private'),
		('workspaces', 'Workspace/Organization'),
	], default='private')
	created_at = models.DateTimeField(default=timezone.now)
	# Add conversation management fields
	is_archived = models.BooleanField(default=False)
	is_starred = models.BooleanField(default=False)
	archived_at = models.DateTimeField(null=True, blank=True)
	starred_at = models.DateTimeField(null=True, blank=True)
	
	class Meta:
		unique_together = ['user', 'receiver', 'workspace']  # Prevent duplicate threads
		ordering = ['-starred_at', '-created_at']  # Show starred threads first, then by creation date

class MessageModel(models.Model):
	thread = models.ForeignKey('ThreadModel', related_name='messages', on_delete=models.CASCADE, blank=True, null=True)
	sender_user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sent_messages')
	receiver_user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='received_messages')
	body = models.CharField(max_length=1000)
	image = models.ImageField(upload_to='uploads/message_photos', blank=True, null=True)
	date = models.DateTimeField(default=timezone.now)
	is_read = models.BooleanField(default=False)
	# Add workspace context
	workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, null=True, blank=True, related_name='messages')
	
	class Meta:
		ordering = ['-date']

class Image(models.Model):
	image = models.ImageField(upload_to='uploads/post_photos', blank=True, null=True)

class Tag(models.Model):
	name = models.CharField(max_length=255)
