"""Declarative base and shared database value helpers."""

from datetime import UTC, datetime
from enum import Enum
from typing import TypeAlias

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

JsonObject: TypeAlias = dict[str, object]


def enum_values(enum_type: type[Enum]) -> list[str]:
    """Return persisted string values for a Python enumeration."""

    return [str(member.value) for member in enum_type]


def utc_now() -> datetime:
    """Return an aware UTC timestamp for ORM defaults."""

    return datetime.now(UTC)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for AgentLoom SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
