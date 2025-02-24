"""
Classes that signifies parts of a forum.
"""
from .session import Session, UsesSession
from .protocols.forum import Indexed, UserGroup, Paged, PostIcons, UserData
# from .protocols.forum import
from .exceptions import RequestError, IncompleteError
from . import api
from .parsers import forum as forum_parser
from dataclasses import dataclass, InitVar, fields
from typing import TypeVar, Generic, TypedDict, Self
from warnings import warn

T = TypeVar("T")


def check_fields(self: Self, *fields) -> Self:
    """Checks the field for this instance."""
    missing = []
    for field in fields:
        if getattr(self, field) is None:
            missing.append(field)
    if missing != []:
        raise IncompleteError(missing)


class _Indexed(Indexed):
    """An altered version of Indexed."""
    default_update_method = "get"
    default_submit_method = "post"

    def update(self: Self, method: str = None, **kwargs) -> Self:
        """See :py:class:`Indexed`.

        :param method: The method to use.
        :raise IncompleteError: Some necessary fields are not defined.
        """
        if method is None:
            method = self.default_update_method
        attrs = dir(self)
        my_fields = {field.name for field in fields(self)}
        method_name = "update_" + method

        excess_kwargs = {}
        for k, v in kwargs.items():
            if k in my_fields:
                setattr(self, k, v)
            else:
                excess_kwargs[k] = v

        if method_name in attrs:
            return getattr(self, method_name, **excess_kwargs)(self)
        else:
            raise NotImplementedError(f"method {method} not implemented")

    def submit(self: Self, method: str = None, **kwargs) -> Self:
        """See :py:class:`Indexed`.

        :param method: The method to use.
        :raise IncompleteError: Some necessary fields are not defined."""
        if method is None:
            method = self.default_submit_method
        attrs = dir(self)
        my_fields = {field.name for field in fields(self)}
        method_name = "submit_" + method

        excess_kwargs = {}
        for k, v in kwargs.items():
            if k in my_fields:
                setattr(self, k, v)
            else:
                excess_kwargs[k] = v

        if method_name in attrs:
            return getattr(self, method_name, **excess_kwargs)(self)
        else:
            raise NotImplementedError(f"method {method} not implemented")


@dataclass
class Page(Generic[T]):
    """A class representing a page.

    This object is polymorphic; it can support pages of different content
    types.

    :ivar hierarchy: The forum ID.
    :ivar current_page: The current page number.
    :ivar total_pages: The total pages.
    :ivar contents: The contents of the page."""
    hierarchy: list[tuple[str, str]]
    current_page: int
    total_pages: int
    contents: list[TypedDict]
    content_type: InitVar[T]
    session: InitVar[Session]

    def __post_init__(self: Self, content_type: T, session: Session) -> None:
        # cast self.contents with content_type
        self.contents = [
            content_type(**x) for x in self.contents
        ]


@dataclass
class User(UsesSession, _Indexed):
    """Class that represents a user."""
    uid: int = None
    name: str = None
    avatar: str = None
    group: str | UserGroup = None
    posts: int = None
    signature: str = None
    email: str = None
    blurb: str = None
    location: str = None
    real_name: str = None
    social: dict[str, str] = None
    website: str = None
    gender: str = None


@dataclass
class Topic(Paged, UsesSession, _Indexed):
    """A type that contains information about a topic.

    :ivar tid: The topic ID.
    :ivar topic_name: The topic name.
    :ivar pages: The amount of pages the topic has.
    """
    tid: int = None
    topic_name: str = None
    pages: int = None

    def __post_init__(self: Self) -> None:
        self.total_pages = 0

    def update_get(self: Self) -> Self:
        """GET this topic on the specified :py:ivar:`tid`."""
        check_fields(self, "tid")
        res = api.get_topic_page(self.session, self.tid, 0)
        parsed = forum_parser.parse_page(
            res.text,
            forum_parser.parse_topic_content
        )
        last_item = parsed["hierarchy"][-1]
        last_name, _last_url = last_item
        self.topic_name = last_name
        self.pages = parsed["total_pages"]
        return self

    def get_page(self: Self, page: int = 1) -> list["Message"]:
        """Gets a page of posts."""
        check_fields(self, "tid")
        res = api.get_topic_page(
            self.session, self.tid, (page - 1) * api.TOPIC_PER_PAGE
        )
        parsed = forum_parser.parse_page(
            res.text,
            forum_parser.parse_topic_content
        )
        if page != parsed["current_page"]:
            warn(f"Expected page {page}, got page {parsed["current_page"]}")
        # just in case update_get() hasn't been called
        last_item = parsed["hierarchy"][-1]
        last_name, _last_url = last_item
        self.name = last_name
        self.pages = parsed["total_pages"]
        return [Message(**msg) for msg in parsed["contents"]]

    def get_size(self: Self) -> int:
        return self.pages


@dataclass
class Message(UsesSession, _Indexed):
    """Class that represents a message.

    A message (usually called a post) is the smallest unit of a forum. It
    carries a string of text as the content of the message, consisting of
    text, images, links, etc. It also carries other metadata like date of
    post and the user that  posted this post.
    """
    tid: int = None
    mid: int = None
    subject: str = None
    date: str = None
    edited: str | None = None
    content: str = None
    user: User | UserData = None
    icon: str | PostIcons = None

    def __post_init__(self: Self) -> None:
        if type(self.user) is dict:
            self.user = User(**self.user)
        if type(self.icon) is str:
            self.icon = PostIcons(self.icon)

    def submit_post(self: Self) -> Self:
        """POST this message on the specified :py:ivar:`tid`."""
        check_fields(self, "tid")
        res = api.post_message(
            self.session, self.tid, self.content, self.subject, self.icon
        )
        forum_parser.check_errors(res.text, res)
        return self

    def update_get(self: Self) -> Self:
        """GET this message on the specified :py:ivar:`mid`."""
        check_fields(self, "mid")
        res = api.get_message_page(
            self.session, self.mid
        )
        forum_parser.check_errors(res.text, res)
        parsed = forum_parser.parse_page(
            res.text,
            forum_parser.parse_topic_content
        )
        post = filter(lambda x: x["mid"] == self.mid, parsed["contents"])
        try:
            post = next(post)
            self.__init__(**post)
        except StopIteration:
            raise RequestError("Requested post doesn't exist in page",
                               response=res)
        return self

    def submit_edit(self: Self, reason: str = "") -> Self:
        """POST an edit with a specified reason."""
        check_fields(self, "mid", "tid")
        res = api.edit_message(
            self.session, self.mid, self.tid, self.content, self.subject,
            self.icon, reason
        )
        forum_parser.check_errors(res.text, res)
        return self

    def update_quotefast(self: Self) -> Self:
        """GETs the BBC of message on the specified :py:ivar:`mid`.
        This uses the `quotefast` action."""
        check_fields(self, "mid")
        params = {
            "quote": str(self.mid),
            "xml": None,
            "modify": None,  # allows posts from closed topics
        }
        res = api.do_action(
            self.session, "quotefast", params=params,
            no_percents=True
        )
        if "<html" in res.text:  # this is not XML!
            forum_parser.check_errors(res.text, res)
        post = forum_parser.parse_quotefast(res.text)
        self.__init__(**post)
        return self
