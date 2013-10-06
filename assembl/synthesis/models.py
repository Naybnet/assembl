from datetime import datetime

from sqlalchemy.orm import relationship, backref, aliased
from sqlalchemy.sql import func, cast, select, text
from pyramid.i18n import TranslationString as _

from sqlalchemy import (
    Table,
    Column, 
    Boolean,
    Integer, 
    String,
    Float,
    Unicode, 
    UnicodeText, 
    DateTime,
    ForeignKey,
    desc,
    event,
)

from assembl.lib.utils import slugify

from ..db import DBSession
from ..db.models import db_schema
from ..lib.sqla import Base as SQLAlchemyBaseModel
from ..source.models import (Source, Content, Post)

class Discussion(SQLAlchemyBaseModel):
    """
    A Discussion
    """
    __tablename__ = "discussion"

    id = Column(Integer, primary_key=True)

    topic = Column(UnicodeText, nullable=False)
    
    slug = Column(UnicodeText, nullable=False, unique=True, index=True)
    
    creation_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    table_of_contents_id = Column(
        Integer,
        ForeignKey('table_of_contents.id', ondelete="CASCADE"),
        nullable=False,
    )

    table_of_contents = relationship(
        'TableOfContents', 
        uselist=False,
    )

    synthesis = relationship('Synthesis', uselist=False)

    owner_id = Column(
        Integer,
        ForeignKey('user.id'),
        nullable=False
    )

    owner = relationship(
        'User',
        backref="discussions"
    )

    def posts(self, parent_id=None):
        """
        Returns an iterable query of posts whose content comes from a source
        that belongs to this discussion. The result is a list of posts sorted
        by their youngest descendent in descending order.
        """
        lower_post = aliased(Post, name="lower_post")
        lower_content = aliased(Content, name="lower_content")
        upper_post = aliased(Post, name="upper_post")
        upper_content = aliased(Content, name="upper_content")

        latest_update = select([
            func.coalesce(
                func.max(lower_content.creation_date),
                upper_content.creation_date
            )
        ], lower_post.content_id==lower_content.id).where(
            lower_post.ancestry.like(
                upper_post.ancestry + cast(upper_post.id, String) + ',%'
            )
        ).label("latest_update")

        query = DBSession.query(
            upper_post,
        ).join(
            upper_content,
        ).filter(
            upper_post.parent_id==parent_id
        ).order_by(
            desc(latest_update)
        )

        if not parent_id:
            query = query.join(
                Source
            ).filter(
                Source.discussion_id==self.id,
                upper_content.source_id==Source.id,
            )

        return query

    def total_posts(self):
        return DBSession.query(Post).join(
            Content,
            Source
        ).filter(
            Source.discussion_id==self.id,
            Content.source_id==Source.id,
        ).count()

    def import_from_sources(self, only_new=True):
        # refetch after calling
        for source in self.sources:
            session = DBSession()
            source = session.merge(source)
            source.import_content(only_new=only_new)

    def __init__(self, *args, **kwargs):
        super(Discussion, self).__init__(*args, **kwargs)
        self.table_of_contents = TableOfContents(discussion=self)
        self.synthesis = Synthesis(discussion=self)

    def serializable(self):
        return {
            "id": self.id, 
            "topic": self.topic,
            "slug": self.slug,
            "creation_date": self.creation_date.isoformat(),
            "table_of_contents_id": self.table_of_contents_id,
            "synthesis_id": self.synthesis.id,
            "owner_id": self.owner_id,
        }

    def __repr__(self):
        return "<Discussion %s>" % repr(self.topic)


def slugify_topic_if_slug_is_empty(discussion, topic, oldvalue, initiator):
    """
    if the target doesn't have a slug, slugify the topic and use that.
    """
    if not discussion.slug:
        discussion.slug = slugify(topic)


event.listen(Discussion.topic, 'set', slugify_topic_if_slug_is_empty)


class TableOfContents(SQLAlchemyBaseModel):
    """
    Represents a Table of Contents.

    A ToC in Assembl is used to organize the core ideas of a discussion in a
    threaded hierarchy.
    """
    __tablename__ = "table_of_contents"

    id = Column(Integer, primary_key=True)
    creation_date = Column(DateTime, nullable=False, default=datetime.utcnow)

    discussion = relationship(
        'Discussion',
        uselist=False
    )

    def serializable(self):
        return {
            "topic": self.topic,
            "slug": self.slug,
            "id": self.id,
            "table_of_contents_id": self.table_of_contents_id,
            "synthesis_id": self.synthesis_id
        }

    def __repr__(self):
        return "<TableOfContents %s>" % repr(self.discussion.topic)


class Synthesis(SQLAlchemyBaseModel):
    """
    A synthesis of the discussion.
    """
    __tablename__ = "synthesis"

    id = Column(Integer, primary_key=True)
    creation_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    publication_date = Column(DateTime, default=datetime.now)

    subject = Column(UnicodeText)
    introduction = Column(UnicodeText)
    conclusion = Column(UnicodeText)

    discussion_id = Column(
        Integer,
        ForeignKey('discussion.id', ondelete="CASCADE"),
        nullable=False
    )

    discussion = relationship('Discussion')

    def serializable(self):
        return {
            "id": self.id,
            "creation_date": self.creation_date.isoformat(),
            "publication_date": self.publication_date.isoformat() \
                if self.publication_date \
                else None,
            "subject": self.subject,
            "introduction": self.introduction,
            "conclusion": self.conclusion,
            "discussion_id": self.discussion.id,
        }

    def __repr__(self):
        return "<Synthesis %s>" % repr(self.subject)


idea_association_table = Table(
    'idea_association',
    SQLAlchemyBaseModel.metadata,
    Column('parent_id', Integer, ForeignKey('idea.id')),
    Column('child_id', Integer, ForeignKey('idea.id')),
    schema = db_schema
)

class Idea(SQLAlchemyBaseModel):
    """
    A core concept taken from the associated discussion
    """
    __tablename__ = "idea"
    ORPHAN_POSTS_IDEA_ID = 'orphan_posts'

    long_title = Column(UnicodeText)
    short_title = Column(UnicodeText)

    id = Column(Integer, primary_key=True)
    creation_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    order = Column(Float, nullable=False, default=0.0)

    table_of_contents_id = Column(
        Integer,
        ForeignKey('table_of_contents.id'),
        nullable=False
    )

    table_of_contents = relationship(
        'TableOfContents',
        backref='ideas',
    )

    children = relationship(
        "Idea",
        secondary=idea_association_table,
        backref="parents",
        primaryjoin=id==idea_association_table.c.parent_id,
        secondaryjoin=id==idea_association_table.c.child_id,
    )

    synthesis_id = Column(
        Integer,
        ForeignKey('synthesis.id'),
    )

    synthesis = relationship('Synthesis', backref='ideas')

    def serializable(self):
        return {
            'id': self.id,
            'shortTitle': self.short_title,
            'longTitle': self.long_title,
            'creationDate': self.creation_date.isoformat(),
            'order': self.order,
            'active': False,
            'featured': False,
            'parentId': self.parents[0].id if self.parents else None,
            'inSynthesis': True if self.synthesis_id else False,
            'total': len(self.children),
            'num_posts': self.num_posts,
        }
    @staticmethod
    def serializable_unsorded_posts_pseudo_idea(discussion):
        """
        Returns a "fake" idea linking the posts unreacheable by navigating
        post threads linked to any other idea
        """
        return {
            'id': Idea.ORPHAN_POSTS_IDEA_ID,
            'shortTitle': _('Unsorted posts'),
            'longTitle': '',
            'creationDate': None,
            'order': 1000000000,
            'active': False,
            'featured': False,
            'parentId': None,
            'inSynthesis': False,
            'total': 0,
            'num_posts': Idea.get_num_orphan_posts(discussion),
        }
    @staticmethod
    def _get_idea_dag_statement(skip_where=False):
        return """SELECT child_id as idea_id FROM (
            SELECT transitive t_in (1) t_out (2) t_distinct T_NO_CYCLES parent_id, child_id from idea_association
                UNION SELECT id as parent_id, id as child_id FROM idea
            ) ia where ia.parent_id = :root_idea_id"""

    @staticmethod
    def _get_related_posts_statement_no_select(select, skip_where):
        return select + " FROM (" + Idea._get_idea_dag_statement(skip_where) + """)
AS idea_dag 
JOIN extract ON (extract.idea_id = idea_dag.idea_id) 
JOIN content ON (extract.source_id = content.id) 
JOIN post AS root_posts ON (root_posts.content_id = content.id)
JOIN post ON (
    (post.ancestry <> '' 
    AND post.ancestry LIKE root_posts.ancestry || root_posts.id || ',' || '%'
    )
    OR post.id = root_posts.id
)
"""
    @staticmethod
    def _get_related_posts_statement(skip_where=False):
        return Idea._get_related_posts_statement_no_select("SELECT DISTINCT post.id", skip_where)

    @staticmethod
    def _get_count_related_posts_statement():
        return Idea._get_related_posts_statement_no_select("SELECT COUNT(DISTINCT post.id) as total_count", False)

    @staticmethod
    def _get_orphan_posts_statement_no_select(select):
        """ Requires discussion_id bind parameters """
        return select + """
FROM post
JOIN content ON (post.content_id = content.id)
JOIN source ON (content.source_id = source.id)
JOIN discussion ON (source.discussion_id = discussion.id)
WHERE post.id NOT IN (
""" + Idea._get_related_posts_statement(True) + """
)
AND discussion.id=:discussion_id
"""

    @staticmethod
    def _get_count_orphan_posts_statement():
        """ Requires discussion_id bind parameters """
        return Idea._get_orphan_posts_statement_no_select("SELECT COUNT(post.id) as total_count")
 
    @staticmethod
    def _get_orphan_posts_statement():
        """ Requires discussion_id bind parameters """
        return Idea._get_orphan_posts_statement_no_select("SELECT post.id")
    
    @property
    def num_posts(self):
        """ This is extremely naive and slow, but as this is all temp code 
        until we move to a graph database, it will probably do for now """ 
        result = DBSession.execute(text(Idea._get_count_related_posts_statement()),
                                   {"root_idea_id":self.id})
        return result.first()['total_count']

    @staticmethod
    def get_num_orphan_posts(discussion):
        """ The number of posts unrelated to any idea in the current discussion """ 
        result = DBSession.execute(text(Idea._get_count_orphan_posts_statement()) \
                                   .params(discussion_id=discussion.id))
        return result.first()['total_count']

    def __repr__(self):
        if self.short_title:
            return "<Idea %d %s>" % (self.id, repr(self.short_title))

        return "<Idea %d>" % self.id


class Extract(SQLAlchemyBaseModel):
    """
    An extracted part. A quotation to be referenced by an `Idea`.
    """
    __tablename__ = 'extract'

    id = Column(Integer, primary_key=True)
    creation_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    order = Column(Float, nullable=False, default=0.0)
    body = Column(UnicodeText, nullable=False)

    source_id = Column(Integer, ForeignKey('content.id'), nullable=False)
    source = relationship(Content, backref='extracts')

    idea_id = Column(Integer, ForeignKey('idea.id'), nullable=True)
    idea = relationship('Idea', backref='extracts')

    creator_id = Column(
        Integer,
        ForeignKey('user.id'),
        nullable=False,
    )

    creator = relationship(
        'User', foreign_keys=[creator_id], backref='extracts_created')

    owner_id = Column(
        Integer,
        ForeignKey('user.id'),
        nullable=False,
    )

    owner = relationship(
        'User', foreign_keys=[owner_id], backref='extracts_owned')

    def serializable(self):
        return {
            'id': self.id,
            'text': self.body,
            'idPost': self.source.post.id,
            'idIdea': self.idea_id,
            'creationDate': self.creation_date.isoformat(),
            'creator': self.creator.serializable(),
            'source_creator': self.source.post.creator.serializable()
        }

    def __repr__(self):
        return "<Extract %d %s>" % (self.id, repr(self.body[:20]))
