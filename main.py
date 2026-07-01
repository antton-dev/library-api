#####
# THIS API RESPECT THE CRUD SCHEME : 
# CREATE
# READ
# UPDATE
# DELETE
#####

########## IMPORT ##########
from fastapi import FastAPI, HTTPException, Depends, Security, Query
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from sqlmodel import select, Session
import httpx
from pydantic import BaseModel
import os
from typing import List, Optional

from models import *
from database import *

########## SECRETS AND API KEY MANAGMENT ##########
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Security(api_key_header)):
    expected_key = os.getenv("APP_KEY")
    if not api_key or api_key != expected_key:
        raise HTTPException(status_code=403, detail="Accès refusé : Wrong or missing API Key")

    return api_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan, title="Library API")

def get_session():
    with Session(engine) as session:
        yield session

########## MODELS ##########
class BookCreate(BaseModel):
    isbn: str
    status: BookStatus = BookStatus.OWNED


class BookCreateManual(BaseModel):
    isbn: str
    title: str
    author: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    status: BookStatus = BookStatus.OWNED

class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    status: Optional[BookStatus] = None
    lend_to: Optional[str] = None
    borrowed_from: Optional[str] = None

class BookSearchResult(BaseModel):
    google_id: str
    isbn: str
    title: str
    author: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    already_in_library: bool = False


########## ROUTES ##########

# CREATE ROUTES
@app.post("/books/manual", response_model=Book)
def create_book_manually(
    request: BookCreateManual,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    statement = select(Book).where(Book.isbn == request.isbn)
    existing_book = session.exec(statement).first()

    if existing_book:
        raise HTTPException(status_code=400, detail="Ce livre est déjà dans la base de données")

    new_book = Book(
        isbn = request.isbn,
        title = request.title,
        author = request.author,
        description = request.description,
        cover_url = request.cover_url,
        status = request.status
    )

    session.add(new_book)
    session.commit()
    session.refresh(new_book)

    return new_book


@app.post("/books/fromisbn", response_model=Book)
async def create_book(
    request: BookCreate,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    statement = select(Book).where(Book.isbn == request.isbn)
    existing_book = session.exec(statement).first()

    if existing_book:
        raise HTTPException(status_code=400, detail="Ce livre est déjà dans la base de données")

    title = ""
    author = ""
    description = ""
    cover_url = ""

    google_url = "https://www.googleapis.com/books/v1/volumes"
    params = {
        "q": f"isbn:{request.isbn}",
        "key": GOOGLE_API_KEY
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(google_url, params=params)
        data = response.json()

    # GOOGLE BOOKS CALL
    if "items" in data:
        volume_info = data["items"][0].get("volumeInfo", {})
        title = volume_info.get("title", "")
        
        authors = volume_info.get("authors", [])
        author = authors[0] if authors else ""
        
        description = volume_info.get("description", "")
        image_links = volume_info.get("imageLinks") or {}
        cover_url = image_links.get("thumbnail", "")

    # 2. ISBN FALLBACK WITH OPENLIBRARY 
    else:
        openlib_url = "https://openlibrary.org/api/books"
        openlib_key = f"ISBN:{request.isbn}"
        openlib_params = {
            "bibkeys": openlib_key,
            "format": "json",
            "jscmd": "data"
        }

        async with httpx.AsyncClient() as client: 
            response = await client.get(openlib_url, params=openlib_params)
            openlib_data = response.json()

        if openlib_key not in openlib_data:
            raise HTTPException(status_code=404, detail="Livre introuvable, ajoutez-le manuellement")

        book_data = openlib_data[openlib_key]
        title = book_data.get("title", "")
        
        authors = book_data.get("authors", [])
        author = authors[0].get("name", "") if authors else ""
        
        
        cover = book_data.get("cover", {})
        cover_url = cover.get("medium", cover.get("large", ""))

    # SECONDARY FALLBACK
    if title and author and (not description or not cover_url):
        fallback_params = {
            "q": f'intitle:"{title}"+inauthor:"{author}"',
            "key": GOOGLE_API_KEY
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(google_url, params=fallback_params)
            fallback_data = response.json()

            for item in fallback_data.get("items", []):
                alt_info = item.get("volumeInfo", {})
                
                if not description and "description" in alt_info:
                    description = alt_info["description"]
                
                if not cover_url and "imageLinks" in alt_info and "thumbnail" in alt_info["imageLinks"]:
                    cover_url = alt_info["imageLinks"]["thumbnail"]
                    
                if description and cover_url:
                    break


    if not title:
        raise HTTPException(status_code=404, detail="Impossible de récupérer le titre du livre.")

    new_book = Book(
        isbn=request.isbn,
        title=title,
        author=author,
        description=description or "",  
        cover_url=cover_url or "",
        status=request.status
    )

    session.add(new_book)
    session.commit()
    session.refresh(new_book)

    return new_book

# READ ROUTES
@app.get("/books", response_model=List[Book])
def get_books(
    status: Optional[BookStatus] = None,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    statement = select(Book)

    if status:
        statement = statement.where(Book.status == status)

    books = session.exec(statement).all()
    return books


@app.get("/books/searchexternal", response_model=List[BookSearchResult])
async def search_books_by_title(
    query: str = Query(..., min_length=2),
    max_results: int = Query(default=10, ge=1, le=20),
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
) :
    google_params = {
        "q": f"intitle:{query}",
        "maxResults": str(max_results),
    }

    if GOOGLE_API_KEY:
        google_params["key"] = GOOGLE_API_KEY

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            "https://www.googleapis.com/books/v1/volumes",
            params=google_params,
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="Erreur lors de la recherche Google Books",
        )

    data = response.json()
    results: List[BookSearchResult] = []
    seen_isbns = set()

    for item in data.get("items", []):
        volume_info = item.get("volumeInfo", {})

        title = volume_info.get("title")
        if not title:
            continue

        identifiers = volume_info.get("industryIdentifiers", [])

        isbn_13 = None
        isbn_10 = None

        for identifier in identifiers:
            identifier_type = identifier.get("type")
            identifier_value = identifier.get("identifier")

            if identifier_type == "ISBN_13":
                isbn_13 = identifier_value
            elif identifier_type == "ISBN_10":
                isbn_10 = identifier_value

        isbn = isbn_13 or isbn_10

        if not isbn:
            continue

        if isbn in seen_isbns:
            continue

        seen_isbns.add(isbn)

        authors = volume_info.get("authors", [])
        author = authors[0] if authors else None

        description = volume_info.get("description", "")

        image_links = volume_info.get("imageLinks", {})
        cover_url = image_links.get("thumbnail")

        existing_book = session.exec(
            select(Book).where(Book.isbn == isbn)
        ).first()

        results.append(
            BookSearchResult(
                google_id=item.get("id", ""),
                isbn=isbn,
                title=title,
                author=author,
                description=description,
                cover_url=cover_url,
                already_in_library=existing_book is not None,
            )
        )

    return results


@app.get("/books/{book_id}", response_model=Book)
def get_book(
    book_id: int,
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    book = session.get(Book, book_id)

    if not book:
        raise HTTPException(status_code=404, detail="Livre inconnu")

    return book





# UPDATE ROUTES
@app.patch("/books/{book_id}", response_model=Book)
def update_book(
    book_id: int,
    request: BookUpdate, 
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    db_book = session.get(Book, book_id)

    if not db_book:
        raise HTTPException(status_code=404, detail="Livre introuvable")

    updated_data = request.model_dump(exclude_unset=True)

    for key, value in updated_data.items():
        setattr(db_book, key, value)

    session.add(db_book)
    session.commit()
    session.refresh(db_book)

    return db_book


# DELETE ROUTES
@app.delete("/books/{book_id}")
def delete_book(
    book_id: int, 
    session: Session = Depends(get_session),
    api_key: str = Depends(verify_api_key)
):
    db_book = session.get(Book, book_id)

    if not db_book:
        raise HTTPException(status_code=404, detail="Livre introuvable")
    
    session.delete(db_book)
    session.commit()

    return {"message": f"Le livre {db_book.title} de {db_book.author} a bien été supprimé"}