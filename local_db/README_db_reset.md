# Manual: Create New Empty DB and Switch Project

This guide walks you through:
1) creating a new empty database,
2) deleting the old database, and
3) switching the project to the new database.

---

## 1) Create a New Empty Database

## 1.1)  Pick a new database name (example: `hrvibe_new`).

## 1.2) Go to postgres:
```bash
psql -h localhost -U gridavyv -d postgres
```

## 1.3) Then inside `psql`:
```sql
CREATE DATABASE hrvibe_new;
```
## 1.4) Exit with `\q`.

---

## 2) Delete the Old Database (optional)

## 2.1) Check available databases and find old database (example: `hrbive_old`):

## 2.2) Go to postgres: 
```bash
psql -h localhost -U gridavyv -d postgres
```

## 2.3) Then inside `psql` create DB:

```sql
DROP DATABASE IF EXISTS hrvibe_old;
```
## 2.4) Exit with `\q`.

---

## 3) Switch the Project to the New Database

## 3.1) In .env update your `DATABASE_URL` to point to the new DB.

Example:
```
was
DATABASE_URL=postgresql://gridavyv@localhost:5432/hrbive_old

update to   
DATABASE_URL=postgresql://gridavyv@localhost:5432/hrbive_new
```

---

## 4) Create Tables from Models

## 4.1) Run the initializer:
```bash
python3 -c "from dotenv import load_dotenv; load_dotenv(); from database import init_db; init_db()"
```

## 4.2) Verify Tables

```bash
psql -h localhost -U gridavyv -d hrvibe_new -c "\dt"
```


