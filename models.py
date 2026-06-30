from sqlmodel import SQLModel, Field
from typing import Optional
from enum import Enum
from sqlalchemy import Column, Text, String

class BookStatus(str, Enum):
    WISHLIST = "wishlist"
    OWNED    = "possédé"
    BORROWED = "emprunté"
    LENT     = "prêté"

class Book(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    isbn: str = Field(index=True, unique=True, max_length=20)
    title: str = Field(
        sa_column=Column(String(512), nullable=False)
    )
    author: Optional[str] = Field(
        default=None,
        sa_column=Column(String(512), nullable=True)
    )
    description: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True)
    )
    cover_url: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True)
    )
    status: BookStatus = Field(default=BookStatus.OWNED)
    lend_to: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True)
    )
    borrowed_from: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True)
    )