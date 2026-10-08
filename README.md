# Students CRUD API

FastAPI + SQLite backend to manage student records (Create, Read, Update, Delete).
Optional: POST /ask answers questions about the data using a local Ollama model.

## Prerequisites
- Python 3.10+
- (Optional) Ollama with llama3.2:1b

## Install

    pip install -r requirements.txt

## Run

    uvicorn main:app --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000/docs for the interactive API docs.

## Endpoints
- POST /students : create a student
- GET /students : list / filter (name, course, born_after, limit, offset)
- GET /students/{id} : view a student
- PUT /students/{id} : replace details
- PATCH /students/{id} : update some details
- DELETE /students/{id} : delete a student
- POST /ask : optional Ollama Q&A

## Test (curl)

    curl -X POST localhost:8000/students -H "Content-Type: application/json" -d '{"name":"Aarav Sharma","date_of_birth":"2004-03-12","email":"aarav@example.com","course":"AI/ML"}'
    curl localhost:8000/students
    curl -X PATCH localhost:8000/students/1 -H "Content-Type: application/json" -d '{"course":"Data Science"}'
    curl localhost:8000/students/999
    curl -X DELETE localhost:8000/students/1

## Notes
- Validation: email/phone format, DOB in the past, unique email (409), missing record (404).
- Only dummy data is used. The SQLite file is git-ignored.
