from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.news.models import News, Comment, Rating, Category
from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry


@registry.register_document
class UserDocument(Document):
    class Index:
        name = 'users'
        settings = {
            'number_of_shards': 1,
            'number_of_replicas': 0,
        }

    class Django:
        model = CustomUser
        fields = [
            'id',
            'first_name',
            'last_name',
            'username',
            'email',
        ]

    profile = fields.ObjectField(properties={
        'title': fields.TextField(),
        'address': fields.TextField(),
        'about': fields.TextField(),
        'country': fields.TextField(),
        'city': fields.TextField(),
    })


@registry.register_document
class NewsDocument(Document):
    author = fields.ObjectField(properties={
        "id": fields.KeywordField(),
        "first_name": fields.TextField(),
        "last_name": fields.TextField(),
        "username": fields.TextField(),
    })

    category = fields.ObjectField(properties={
        "id": fields.IntegerField(),
        "name": fields.TextField(),
    })

    tags = fields.NestedField(properties={
        "name": fields.TextField(),
    })

    ratings = fields.NestedField(properties={
        "user": fields.ObjectField(properties={
            "id": fields.KeywordField(),
            "username": fields.TextField(),
        }),
        "rating": fields.IntegerField(),
    })

    likes = fields.NestedField(properties={
        "user": fields.ObjectField(properties={
            "id": fields.KeywordField(),
            "username": fields.TextField(),
        }),
    })

    dislikes = fields.NestedField(properties={
        "user": fields.ObjectField(properties={
            "id": fields.KeywordField(),
            "username": fields.TextField(),
        }),
    })

    shared_user = fields.ObjectField(properties={
        "id": fields.KeywordField(),
        "username": fields.TextField(),
    })

    class Index:
        name = "news"
        settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        }

    class Django:
        model = News
        fields = [
            "id", "title", "body", "excerpt", "pub_date", "status", "featured", "slug", 
            "image", "created_on", "updated_at", "shared_body", "shared_on"
        ]


@registry.register_document
class CommentDocument(Document):
    author = fields.ObjectField(properties={
        "id": fields.KeywordField(),
        "first_name": fields.TextField(),
        "last_name": fields.TextField(),
        "username": fields.TextField(),
    })

    parent = fields.ObjectField(properties={
        "id": fields.IntegerField(),
        "content": fields.TextField(),
    })

    news = fields.ObjectField(properties={
        "id": fields.IntegerField(),
        "title": fields.TextField(),
    })

    tags = fields.NestedField(properties={
        "name": fields.TextField(),
    })

    class Index:
        name = "comments"
        settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        }

    class Django:
        model = Comment
        fields = [
            "content", "date_posted"
        ]


@registry.register_document
class RatingDocument(Document):
    news = fields.ObjectField(properties={
        "id": fields.IntegerField(),
        "title": fields.TextField(),
    })

    user = fields.ObjectField(properties={
        "id": fields.KeywordField(),
        "username": fields.TextField(),
    })

    class Index:
        name = "ratings"
        settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        }

    class Django:
        model = Rating
        fields = [
            "rating", "date_created"
        ]


@registry.register_document
class CategoryDocument(Document):
    class Index:
        name = "categories"
        settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        }

    class Django:
        model = Category
        fields = [
            "name",
        ]
