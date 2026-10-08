"""Students Database CRUD API (FastAPI + SQLite) with optional local Ollama Q&A."""
import json
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, root_validator, validator

DB_PATH = "students.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.2:1b"

EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
PHONE_RE = r"^\+?[0-9\- ]{7,15}$"

app = FastAPI(title="Students CRUD API", version="1.0.0")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                date_of_birth TEXT NOT NULL,
                email TEXT UNIQUE,
                phone TEXT,
                course TEXT,
                address TEXT,
                enrollment_date TEXT
            )"""
        )


init_db()


class StudentBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    date_of_birth: date
    email: Optional[str] = Field(default=None, regex=EMAIL_RE)
    phone: Optional[str] = Field(default=None, regex=PHONE_RE)
    course: Optional[str] = None
    address: Optional[str] = None
    enrollment_date: Optional[date] = None

    @validator("date_of_birth")
    def dob_not_future(cls, v):
        if v >= date.today():
            raise ValueError("date_of_birth must be in the past")
        return v


class StudentCreate(StudentBase):
    @root_validator(skip_on_failure=True)
    def need_contact(cls, values):
        if not values.get("email") and not values.get("phone"):
            raise ValueError("Provide at least one of email or phone")
        return values


class StudentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    date_of_birth: Optional[date] = None
    email: Optional[str] = Field(default=None, regex=EMAIL_RE)
    phone: Optional[str] = Field(default=None, regex=PHONE_RE)
    course: Optional[str] = None
    address: Optional[str] = None
    enrollment_date: Optional[date] = None

    @validator("date_of_birth")
    def dob_not_future(cls, v):
        if v is not None and v >= date.today():
            raise ValueError("date_of_birth must be in the past")
        return v


class Student(StudentBase):
    id: int


class Question(BaseModel):
    question: str = Field(min_length=3)


def _row(student_id: int, db) -> sqlite3.Row:
    row = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Student {student_id} not found")
    return row


def _values(data: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in data.items()}


@app.post("/students", response_model=Student, status_code=201)
def create_student(student: StudentCreate):
    data = _values(student.dict())
    try:
        with get_db() as db:
            cur = db.execute(
                """INSERT INTO students
                (name, date_of_birth, email, phone, course, address, enrollment_date)
                VALUES (:name, :date_of_birth, :email, :phone, :course, :address, :enrollment_date)""",
                data,
            )
            return dict(_row(cur.lastrowid, db))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A student with this email already exists")


@app.get("/students", response_model=list[Student])
def list_students(
    name: Optional[str] = Query(None, description="Partial name match"),
    course: Optional[str] = None,
    born_after: Optional[int] = Query(None, description="Year, e.g. 2005"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    sql, params = "SELECT * FROM students WHERE 1=1", []
    if name:
        sql += " AND name LIKE ?"
        params.append(f"%{name}%")
    if course:
        sql += " AND course = ?"
        params.append(course)
    if born_after:
        sql += " AND CAST(substr(date_of_birth, 1, 4) AS INTEGER) > ?"
        params.append(born_after)
    sql += " ORDER BY id LIMIT ? OFFSET ?"
    params += [limit, offset]
    with get_db() as db:
        return [dict(r) for r in db.execute(sql, params).fetchall()]


@app.get("/students/{student_id}", response_model=Student)
def get_student(student_id: int):
    with get_db() as db:
        return dict(_row(student_id, db))


@app.put("/students/{student_id}", response_model=Student)
def replace_student(student_id: int, student: StudentCreate):
    data = _values(student.dict()) | {"id": student_id}
    try:
        with get_db() as db:
            _row(student_id, db)
            db.execute(
                """UPDATE students SET name=:name, date_of_birth=:date_of_birth,
                email=:email, phone=:phone, course=:course, address=:address,
                enrollment_date=:enrollment_date WHERE id=:id""",
                data,
            )
            return dict(_row(student_id, db))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A student with this email already exists")


@app.patch("/students/{student_id}", response_model=Student)
def update_student(student_id: int, changes: StudentUpdate):
    data = _values(changes.dict(exclude_unset=True))
    if not data:
        raise HTTPException(400, "No fields provided to update")
    sets = ", ".join(f"{k} = ?" for k in data)
    try:
        with get_db() as db:
            _row(student_id, db)
            db.execute(f"UPDATE students SET {sets} WHERE id = ?", [*data.values(), student_id])
            return dict(_row(student_id, db))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A student with this email already exists")


@app.delete("/students/{student_id}")
def delete_student(student_id: int):
    with get_db() as db:
        _row(student_id, db)
        db.execute("DELETE FROM students WHERE id = ?", (student_id,))
    return {"detail": f"Student {student_id} deleted"}


@app.post("/ask")
def ask(q: Question):
    """Backend fetches records and passes them as context. The model never runs SQL."""
    with get_db() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM students ORDER BY id LIMIT 200")]
        total = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]

    context = json.dumps(rows, indent=1)
    messages = [
        {
            "role": "system",
            "content": (
                "You answer questions about a student database. Use ONLY the records "
                "provided. If the answer is not in them, say you don't know. "
                f"Total students in database: {total}."
            ),
        },
        {"role": "user", "content": f"Records:\n{context}\n\nQuestion: {q.question}"},
    ]
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps({"model": OLLAMA_MODEL, "messages": messages, "stream": False}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            answer = json.load(resp)["message"]["content"]
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(503, "Ollama is not reachable. Run `ollama serve` and pull the model.")
    return {"question": q.question, "answer": answer, "records_used": len(rows)}
