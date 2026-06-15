import asyncio
import base64
import json
import os
import re
import smtplib
import threading
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from playwright.async_api import async_playwright

from app.log_ctx import _ctx, plog

from dotenv import load_dotenv
load_dotenv()

import jinja2
from fastapi import FastAPI, BackgroundTasks, Form, HTTPException, Depends, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, event, Column, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .audit import run_audit
from .auth import verify_token


def send_notification_email(to: str, company_name: str, job_id: str):
    """Send an email notification to the user when their audit is complete, with a link to view the report."""
    app_url = os.environ.get("APP_URL", "")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your SEO audit is ready!"
    msg["From"] = "noreply@powerling.com"
    msg["To"] = to
    html = (
        f"<p>Hi,</p>"
        f"<p>Your pre-audit for <strong>{company_name}</strong> is complete.</p>"
        f"<p><a href='{app_url}/audits/{job_id}/result'>View your report</a></p>"
    )
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as server:
        server.starttls()
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        server.sendmail(msg["From"], [to], msg.as_string())


def send_failure_email(to: str, company_name: str, job_id: str):
    """Send an email notification to the user when their audit fails."""
    app_url = os.environ.get("APP_URL", "")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your SEO audit encountered an error"
    msg["From"] = "noreply@powerling.com"
    msg["To"] = to
    html = (
        f"<p>Hi,</p>"
        f"<p>Unfortunately, your pre-audit for <strong>{company_name}</strong> encountered an error and could not be completed.</p>"
        f"<p><a href='{app_url}/audits/{job_id}'>View details</a></p>"
        f"<p>Please try submitting the audit again. If the problem persists, contact support.</p>"
    )
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as server:
        server.starttls()
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        server.sendmail(msg["From"], [to], msg.as_string())


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
    submitted_by = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending | processing | completed | error
    result = Column(Text, nullable=True)         # JSON string of full report
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

class User(Base):
    __tablename__ = "users"
    email = Column(String, primary_key=True, index=True)
    role = Column(String, default="user")  
    first_connected_at = Column(DateTime, nullable=False)
    last_connected_at = Column(DateTime, nullable=False)

Base.metadata.create_all(bind=engine)


# Background task
def run_audit_job(job_id: str, url: str, company_name: str, competitors: list):
    """Runs the full audit pipeline and updates the DB record when done."""
    _ctx.job_id = job_id[:8]
    _audit_semaphore.acquire()
    db = SessionLocal()
    try:
        # Mark as processing
        job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
        if not job:
            plog("[audit] ERROR: job not found in DB, aborting.")
            return
        job.status = "processing"
        job.started_at = datetime.utcnow()
        db.commit()

        # Run the pipeline
        result = run_audit(job_id, url, company_name, competitors)

        # Save completed result
        job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        job.result = json.dumps(result)
        db.commit()

        # send email to notify the user
        try:
            send_notification_email(job.submitted_by, company_name, job_id)
        except Exception as e:
            plog(f"[audit] WARNING: failed to send notification email: {e}")

    except Exception as e:
        plog(f"[audit] ERROR: {e}")
        job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
        if job:
            job.status = "error"
            job.completed_at = datetime.utcnow()
            job.error_message = str(e)
            db.commit()
            try:
                send_failure_email(job.submitted_by, company_name, job_id)
            except Exception as mail_err:
                plog(f"[audit] WARNING: failed to send failure email: {mail_err}")
    finally:
        db.close()
        _audit_semaphore.release()


# Startup checks
@app.on_event("startup")
def validate_env():
    """Validate that all required environment envs are set on startup."""
    required = [
        "OPENAI_API_KEY",
        "DATAFORSEO_LOGIN",
        "DATAFORSEO_PASSWORD",
        "YOUTUBE_API_KEY",
        "GOOGLE_PAGESPEED_API_KEY",
        "JWT_SECRET",
        "APP_URL",
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASS",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


@app.on_event("startup")
def cleanup_stale_jobs():
    """On server start/restart, mark any jobs that were processing/pending as errored since they were interrupted."""
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
    submitted_by: str = Depends(verify_token),
):
    """Create a new audit job and start the pipeline in the background."""
    job_id = str(uuid.uuid4())

    # create an audit job and add to tb
    db = SessionLocal()
    job = AuditJob(
        id=job_id,
        url=url,
        company_name=company_name,
        competitor_1=competitor_1,
        competitor_2=competitor_2,
        competitor_3=competitor_3,
        submitted_by=submitted_by,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.close()

    # run the audit in the background and update the job record when done
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
def list_audits(submitted_by: str = Depends(verify_token)):
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
def get_audit(job_id: str, submitted_by: str = Depends(verify_token)):
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
def get_audit_result(job_id: str, submitted_by: str = Depends(verify_token)):
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


class UserInsertBody(BaseModel):
    role: str = "user"

@app.get("/users/me")
def get_current_user(submitted_by: str = Depends(verify_token)):
    """Get current user information (used by frontend to determine admin status upon login)."""
    db = SessionLocal()
    user = db.query(User).filter(User.email == submitted_by).first()
    db.close()

    # basic info to return upon first login attempt
    if not user:
       return {
           "email": submitted_by, 
           "role": "user", 
           "first_connected_at": None, 
           "last_connected_at": None
        }
    return {
        "email": user.email,
        "role": user.role,
        "first_connected_at": user.first_connected_at.isoformat(),
        "last_connected_at": user.last_connected_at.isoformat(),
    }

@app.post("/users/me")
def current_user(body: UserInsertBody, submitted_by: str = Depends(verify_token)):
    """Insert user record on login, otherwise just update last connected"""
    db = SessionLocal()
    user = db.query(User).filter(User.email == submitted_by).first()
    # check if user exists, if not, create with existing role 
    if not user:
        user = User(
            email=submitted_by,
            role=body.role,
            first_connected_at=datetime.utcnow(),
            last_connected_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # update last_connected_at on every login (NOTE: role not updaed after first login)
        user.last_connected_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
    db.close()
    return {
        "email": user.email,
        "role": user.role,
        "first_connected_at": user.first_connected_at.isoformat(),
        "last_connected_at": user.last_connected_at.isoformat(),
    }

@app.get("/users")
def list_users(submitted_by: str = Depends(verify_token)):
    """List all users in the admin-only view"""
    db = SessionLocal()

    # verify that the requester is an admin
    requester = db.query(User).filter(User.email == submitted_by).first()
    if not requester or requester.role != "admin":
        db.close()
        raise HTTPException(status_code=403, detail="Forbidden: admin access required")

    # get users and count per user audit counts and package into array
    users = db.query(User).all()
    audit_counts = {u.email: db.query(AuditJob).filter(AuditJob.submitted_by == u.email).count() for u in users}
    result = [
        {
            "email": u.email,
            "role": u.role,
            "first_connected_at": u.first_connected_at.isoformat(),
            "last_connected_at": u.last_connected_at.isoformat(),
            "audit_count": audit_counts.get(u.email, 0),
        }
        for u in users
    ]
    db.close()
    return result

@app.patch("/users/{email}/role")
def update_user_role(email: str, body: UserInsertBody, submitted_by: str = Depends(verify_token)):
    """Update a user's role (admin-only, used for revoke/grant admin in the frontend)"""
    db = SessionLocal()

    # verify that the requester is an admin
    requester = db.query(User).filter(User.email == submitted_by).first()
    if not requester or requester.role != "admin":
        db.close()
        raise HTTPException(status_code=403, detail="Forbidden: admin access required")

    # filter for user
    user = db.query(User).filter(User.email == email).first()
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="User not found")
    
    # update role
    user.role = body.role
    db.commit()
    db.refresh(user)
    db.close()
    return {
        "email": user.email,
        "role": user.role,
        "first_connected_at": user.first_connected_at.isoformat(),
        "last_connected_at": user.last_connected_at.isoformat(),
    }

@app.get("/users/{email}")
def get_user(email: str, submitted_by: str = Depends(verify_token)):
    """Get all audit information about a specific user (admin-only, used when seeings user info)"""
    db = SessionLocal()

     # verify that the requester is an admin
    requester = db.query(User).filter(User.email == submitted_by).first()
    if not requester or requester.role != "admin":
        db.close()
        raise HTTPException(status_code=403, detail="Forbidden: admin access required")
    
    # get user info
    user = db.query(User).filter(User.email == email).first()
    audit_count = db.query(AuditJob).filter(AuditJob.submitted_by == email).count()
    jobs = db.query(AuditJob).filter(AuditJob.submitted_by == email).order_by(AuditJob.created_at.desc()).all()

    jobs_result =  [
        {
            "id": j.id,
            "url": j.url,
            "company_name": j.company_name,
            "status": j.status,
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]

    db.close()

    return {
        "email": user.email,
        "role": user.role,
        "first_connected_at": user.first_connected_at.isoformat(),
        "last_connected_at": user.last_connected_at.isoformat(),
        "audit_count": audit_count,
        "jobs" : jobs_result
    }


# ------------------------------------------------------------------------------
# PDF export: Everything below concerns the creation of the pdf template provided by Nico
# ------------------------------------------------------------------------------

_PDF_ASSETS_DIR = Path(__file__).parent / "pdf_assets"
_pdf_css_cache = None
_pdf_logo_cache = None
_pdf_semaphore = asyncio.Semaphore(1)


def _get_pdf_assets() -> tuple[str, str]:
    """Return (css, logo_data_url), computed once and cached for the process lifetime."""
    global _pdf_css_cache, _pdf_logo_cache
    if _pdf_css_cache is None:
        assets_dir = _PDF_ASSETS_DIR
        css = (assets_dir / "colors_and_type.css").read_text()
        fonts_dir = assets_dir / "fonts"
        def _inline_font(m):
            fpath = assets_dir / m.group(1)
            if fpath.exists():
                b64 = base64.b64encode(fpath.read_bytes()).decode()
                return f"url('data:font/opentype;base64,{b64}')"
            return m.group(0)
        css = re.sub(r"url\('([^']+\.otf)'\)", _inline_font, css)
        css = re.sub(r"@import url\('https://fonts\.googleapis\.com[^']*'\);", "", css)
        _pdf_css_cache = css
        logo_bytes = (assets_dir / "powerling-logo-black.png").read_bytes()
        _pdf_logo_cache = f"data:image/png;base64,{base64.b64encode(logo_bytes).decode()}"
    return _pdf_css_cache, _pdf_logo_cache


def _score_class(n) -> str:
    try:
        v = int(float(str(n)))
        if v >= 70: return "pos"
        if v >= 50: return "warn"
        return "neg"
    except Exception:
        return "muted"


def _score_color(n) -> str:
    try:
        v = int(float(str(n)))
        if v >= 70: return "var(--c-green-strong)"
        if v >= 50: return "var(--c-amber)"
        return "var(--c-red)"
    except Exception:
        return "#9ca3af"


def _format_count(value) -> str:
    if not value:
        return str(value) if value is not None else ""
    s = str(value).replace(",", "").strip()
    try:
        n = int(s)
        if str(n) == s:
            return f"~{n:,}"
    except ValueError:
        pass
    return f"~{value}"


def _tier_class(tier: str) -> str:
    return {
        "Full Coverage": "tier-full",
        "Strong Coverage": "tier-strong",
        "Partial Coverage": "tier-partial",
        "Limited Coverage": "tier-limited",
    }.get(tier or "", "tier-partial")


def _lcr_bar_color(score) -> str:
    try:
        v = float(str(score))
        if v >= 80: return "var(--c-green-strong)"
        if v >= 50: return "var(--c-amber)"
        return "var(--c-red)"
    except Exception:
        return "var(--c-amber)"


def _score_class_lcr(score) -> str:
    try:
        v = float(str(score))
        if v >= 80: return "pos"
        if v >= 50: return "warn"
        return "neg"
    except Exception:
        return "muted"


def _lcr_donut_color(lcr) -> str:
    try:
        v = float(str(lcr))
        if v >= 100: return "#03A857"
        if v >= 80: return "#65a30d"
        if v >= 50: return "#ca8a04"
        return "#C8525A"
    except Exception:
        return "#ca8a04"


@app.get("/audits/{job_id}/pdf")
async def get_audit_pdf(job_id: str, _submitted_by: str = Depends(verify_token)):
    """Generate and return a PDF report for a completed audit."""
    db = SessionLocal()
    job = db.query(AuditJob).filter(AuditJob.id == job_id).first()
    db.close()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail=f"Audit not complete (status: {job.status})")
    if not job.result:
        raise HTTPException(status_code=500, detail="No result data")

    data = json.loads(job.result)
    facts = data.get("facts", {})
    ui = data.get("ui_content", {})

    p1 = facts.get("pillar_1_globalization", {})
    p2 = facts.get("pillar_2_website_health", {})
    p3 = facts.get("pillar_3_accessibility", {})
    p4 = facts.get("pillar_4_online_reputation", {})
    cf = facts.get("competitor_facts", [])

    lcr = p1.get("lcr_score") or 0
    lcr_arc = round(float(lcr) / 100 * 238.76, 1)

    ml_count = len(p1.get("mixed_language_issues") or [])

    crawl_error = p2.get("crawl_error") or ""
    if p2.get("psi_ran") == False and p2.get("crawl_ran") == False:
        p2_warning = "Performance and crawl data could not be collected. Pillar 2 findings are based on limited information only."
    elif p2.get("crawl_ran") == False and crawl_error.startswith("Bot-blocked"):
        p2_warning = "Site health data unavailable - bot protection prevented the crawler from accessing this site. PSI scores are unaffected."
    elif p2.get("crawl_ran") == False and crawl_error:
        p2_warning = f"Crawl data unavailable: {crawl_error}"
    elif p2.get("psi_ran") == False:
        p2_warning = "PageSpeed data could not be collected for this site."
    elif p2.get("crawl_ran") != False and p2.get("pages_crawled") == 1:
        p2_warning = "Crawl limited to 1 page - metrics reflect the homepage only, not the full site."
    else:
        p2_warning = None

    css_content, logo_url_str = _get_pdf_assets()

    tpl_dir = Path(__file__).parent / "templates"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(tpl_dir)),
        autoescape=True,
    )
    env.filters["format_count"] = _format_count
    env.globals.update({
        "score_class": _score_class,
        "score_color": _score_color,
        "tier_class": _tier_class,
        "lcr_bar_color": _lcr_bar_color,
        "score_class_lcr": _score_class_lcr,
    })

    tpl = env.get_template("audit_report.html")
    html = tpl.render(
        company_name=facts.get("company_name", ""),
        url=facts.get("url", ""),
        generated_date=datetime.now(timezone.utc).strftime("%B %d, %Y"),
        p1=p1, p2=p2, p3=p3, p4=p4,
        cf=cf, ui=ui,
        lcr_arc=lcr_arc,
        lcr_donut_color=_lcr_donut_color(lcr),
        ml_count=ml_count,
        p2_warning=p2_warning,
        css_content=css_content,
        logo_url=logo_url_str,
    )

    async def _render():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            await browser.close()
            return pdf_bytes

    try:
        async with _pdf_semaphore:
            pdf_bytes = await asyncio.wait_for(_render(), timeout=30.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="PDF generation timed out")

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", facts.get("company_name", "report")).strip("-").lower()
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{slug}-preaudit.pdf"'},
    )