"""Declarative base shared by all database models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for AgentLoom SQLAlchemy models."""
