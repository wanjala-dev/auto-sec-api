import os
import time
from datetime import datetime

from django.db import models
from django.conf import settings
from components.shared_platform.infrastructure.services.core_utils import build_absolute_media_url


def _upload_to(instance, filename):
    epoch_time = int(round(time.time() * 1000))
    name, extension = os.path.splitext(filename)
    file = "{}_{}{}".format(name, epoch_time, extension)
    return "{}/{}".format(instance.__class__.__name__, file)

def upload_location(instance, filename):
    ext = filename.split(".")[-1]
    return "%s/%s.%s" % ("img",datetime.now(),ext)

class File(models.Model):
    # File processing status choices. Indexing (embed + AI insights) is
    # OPT-IN: uploads land as not_indexed and only enter the pipeline when
    # a user explicitly requests indexing (or uploads with index intent,
    # e.g. the AI-grounding uploader). 'pending' therefore means "index
    # requested, queued" — never "freshly uploaded".
    PROCESSING_STATUS_CHOICES = [
        ('not_indexed', 'Not indexed'),
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    # File type choices
    FILE_TYPE_CHOICES = [
        ('image', 'Image'),
        ('pdf', 'PDF'),
        ('document', 'Document'),
        ('other', 'Other'),
    ]

    # Source — where this file was uploaded from
    SOURCE_CHOICES = [
        ('ai_chat', 'AI Chat'),
        ('expense_import', 'Expense Import'),
        ('income_import', 'Income Import'),
        ('budget_import', 'Budget Import'),
        ('knowledge_base', 'Knowledge Base'),
        ('manual_upload', 'Manual Upload'),
        ('other', 'Other'),
    ]

    created = models.DateTimeField(auto_now_add=True)
    file = models.FileField(blank=False, null=False, upload_to=_upload_to)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, to_field='id', on_delete=models.CASCADE)
    workspace_id = models.CharField(max_length=36, blank=True, null=True, help_text="ID of the workspace/organization this file belongs to")

    # New fields for file processing
    file_type = models.CharField(max_length=20, choices=FILE_TYPE_CHOICES, default='other')
    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, default='not_indexed')
    processing_error = models.TextField(blank=True, null=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    # When indexing was last explicitly requested — the accounting basis for
    # the per-workspace daily quota and the failure circuit-breaker.
    index_requested_at = models.DateTimeField(blank=True, null=True)

    # PDF specific fields
    pdf_text = models.TextField(blank=True, null=True)
    pdf_page_count = models.IntegerField(blank=True, null=True)

    # Source tracking and AI insights
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, default='manual_upload')
    ai_insights = models.JSONField(default=dict, blank=True, help_text="AI-extracted insights about this document.")
    
    class Meta:
        ordering = ['-created']  # Order by creation date, newest first
    
    def __str__(self):
        return self.file.name
    
    @property
    def is_pdf(self):
        """Check if file is a PDF"""
        return self.file_type == 'pdf'

    @property
    def is_document(self):
        """Check if file is a document that should be processed for embeddings"""
        return self.file_type == 'document'
    
    @property
    def is_processed(self):
        """Check if file has been processed"""
        return self.processing_status == 'completed'
    
    @property
    def needs_processing(self):
        """Check if file needs processing (documents that haven't been processed)"""
        return (self.is_pdf or self.is_document) and self.processing_status in ['not_indexed', 'pending', 'failed']

    def get_absolute_file_url(self, request=None, default_scheme=None):
        """Proxy to shared utility so other modules can reuse the same logic."""
        return build_absolute_media_url(self.file, request=request, default_scheme=default_scheme)




# import uuid
# from io import BytesIO
# from django.db import models
# from infrastructure.persistence.users.models import CustomUser
# from datetime import datetime
# from django.core.exceptions import ValidationError
# from django.core.validators import MaxValueValidator
# from django.core.files import File
# from PIL import Image
# from django.utils.translation import ugettext as _

# class MaxSizeValidator(MaxValueValidator):
#     message = _('The file exceed the maximum size of %(limit_value)s MB.')

#     def __call__(self, value):
#         # get the file size as cleaned value
#         cleaned = self.clean(value.size)
#         params = {'limit_value': self.limit_value, 'show_value': cleaned, 'value': value}
#         if self.compare(cleaned, self.limit_value * 1024 * 1024): # convert limit_value from MB to Bytes
#             raise ValidationError(self.message, code=self.code, params=params)


# def _upload_to(instance, filename):
#     epoch_time = epoch_milliseconds()
#     name, extension = os.path.splitext(filename)
#     file = "{}_{}{}".format(name, epoch_time, extension)
#     return "{}/{}".format(instance.__class__.__name__, file)


# class File(models.Model):
#     created = models.DateTimeField(auto_now_add=True)
#     owner = models.ForeignKey(CustomUser, to_field='id', on_delete=models.CASCADE)
#     thumbnail = models.ImageField(blank=False, null=False, upload_to=_upload_to, validators=[MaxSizeValidator(10)])
#     high_res_image = models.ImageField(blank=False, null=False, upload_to=_upload_to, validators=[MaxSizeValidator(10)])
    

#     def save(self, *args, **kwargs):
#         """
#         Custom save function that overrides the model default. This ensures image saved to the
#         database have smaller filesizes since the max upload is about 10MB.
#         """
#         thumbnail_compressed = self.reduce_image_size(self.thumbnail, thumbnail=True)
#         high_res_image_compressed = self.reduce_image_size(self.high_res_image)
#         self.thumbnail = thumbnail_compressed
#         self.high_res_image = high_res_image_compressed
#         super().save(*args, **kwargs)


#     def reduce_image_size(self, image, thumbnail=False):
#         """
#         Reduces image filesize.
#         :param image: byte stream (I think?); the uploaded image.
#         :param thumbnail: bool; make a thumbnail sized image.
#         :return: Django File object.
#         """

#         pil_image_object = Image.open(image)
#         if thumbnail:
#             maximum_size = (500, 500)
#             pil_image_object.thumbnail(maximum_size)

#         # Strip metadata
#         data = list(pil_image_object.getdata())
#         image_without_metadata = Image.new(pil_image_object.mode, pil_image_object.size)
#         image_without_metadata.putdata(data)
#         small_image_io = BytesIO()
#         image_without_metadata.save(small_image_io, "jpeg", quality=85, optimize=True)
#         new_image = File(small_image_io, name=image.name)
#         return new_image

#     def __str__(self):
#         return self.file.name
