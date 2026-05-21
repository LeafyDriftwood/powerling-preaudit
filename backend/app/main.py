import json
import os
import threading
import uuid
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, event, Column, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .audit import run_audit


app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLAlchemy setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./audit_jobs.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

@event.listens_for(engine, "connect")
def _set_wal_mode(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

_audit_semaphore = threading.Semaphore(2)


class AuditJob(Base):
    __tablename__ = "audit_jobs"
    id = Column(String, primary_key=True, index=True)
    url = Column(String, nullable=False)
    company_name = Column(String, nullable=False)
    competitor_1 = Column(String, nullable=False)
    competitor_2 = Column(String, nullable=False)
    competitor_3 = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending | processing | completed | error
    result = Column(Text, nullable=True)         # JSON string of full report
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


# Background task
def run_audit_job(job_id: str, url: str, company_name: str, competitors: list):
    """Runs the full audit pipeline and updates the DB record when done."""
    _audit_semaphore.acquire()
    db = SessionLocal()
    try:
        # Mark as processing
        job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
        if not job:
            print(f"[audit] ERROR: job {job_id} not found in DB, aborting.")
            return
        job.status = "processing"
        db.commit()

        # Run the pipeline
        result = run_audit(url, company_name, competitors)

        # Save completed result
        job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
        job.status = "completed"
        job.result = json.dumps(result)
        db.commit()

    except Exception as e:
        print(f"[audit] ERROR for job {job_id}: {e}")
        job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
        if job:
            job.status = "error"
            job.error_message = str(e)
            db.commit()
    finally:
        db.close()
        _audit_semaphore.release()


# Startup cleanup
@app.on_event("startup")
def cleanup_stale_jobs():
    db = SessionLocal()
    stale = db.query(AuditJob).filter(
        AuditJob.status.in_(["processing", "pending"])
    ).all()
    for job in stale:
        job.status = "error"
        job.error_message = "Server restarted while audit was in progress"
    if stale:
        print(f"[startup] Reset {len(stale)} stale job(s) to error")
    db.commit()
    db.close()


# Endpoints
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/audits")
async def create_audit(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    company_name: str = Form(...),
    competitor_1: str = Form(...),
    competitor_2: str = Form(...),
    competitor_3: str = Form(...),
):
    """Create a new audit job and start the pipeline in the background."""
    job_id = str(uuid.uuid4())

    db = SessionLocal()
    job = AuditJob(
        id=job_id,
        url=url,
        company_name=company_name,
        competitor_1=competitor_1,
        competitor_2=competitor_2,
        competitor_3=competitor_3,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.close()

    background_tasks.add_task(
        run_audit_job,
        job_id,
        url,
        company_name,
        [competitor_1, competitor_2, competitor_3],
    )

    return {
        "job_id": job_id,
        "status": "pending",
        "created_at": job.created_at.isoformat(),
    }


@app.get("/audits")
def list_audits():
    """List all audit jobs, newest first."""
    db = SessionLocal()
    jobs = db.query(AuditJob).order_by(AuditJob.created_at.desc()).all()
    db.close()
    return [
        {
            "id": j.id,
            "url": j.url,
            "company_name": j.company_name,
            "status": j.status,
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]


@app.get("/audits/{job_id}")
def get_audit(job_id: str):
    """Get audit job status and metadata."""
    db = SessionLocal()
    job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
    db.close()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "url": job.url,
        "company_name": job.company_name,
        "competitor_1": job.competitor_1,
        "competitor_2": job.competitor_2,
        "competitor_3": job.competitor_3,
        "status": job.status,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
    }


@app.get("/audits/{job_id}/result")
def get_audit_result(job_id: str):
    """Get the full report for a completed audit."""
    db = SessionLocal()
    job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
    db.close()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "error":
        raise HTTPException(status_code=500, detail=f"Audit failed: {job.error_message}")
    if job.status != "completed":
        raise HTTPException(status_code=202, detail=f"Audit not yet complete (status: {job.status})")
    if not job.result:
        raise HTTPException(status_code=500, detail="Audit completed but result is missing")
    return json.loads(job.result)
