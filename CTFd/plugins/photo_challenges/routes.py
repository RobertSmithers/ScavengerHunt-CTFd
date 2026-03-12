from flask import Blueprint, request, redirect, url_for, render_template, current_app, flash, abort, send_from_directory
from flask_restx import Namespace, Resource, Api

from CTFd.utils.decorators import authed_only, during_ctf_time_only, admins_only
from CTFd.utils.user import get_current_user, get_current_team, is_admin
from CTFd.models import db, Solves, Challenges, Notifications
from CTFd.models import Files
from CTFd.plugins import bypass_csrf_protection
from .models import PhotoSubmission
from werkzeug.utils import secure_filename
from CTFd.utils.uploads import upload_file
from CTFd.utils.uploads import get_uploader
from werkzeug.utils import safe_join
from flask import send_file
from datetime import datetime
from sqlalchemy.sql import func
import os, secrets
import json

# photo_bp = Blueprint("photo_evidence", __name__, template_folder="templates", static_folder="static", url_prefix="/photo_evidence")
photo_namespace = Namespace("photos", description="Endpoint to handle photo evidence submissions")

# Dedicated API blueprint for plugin endpoints. Registering this blueprint
# with the app makes the plugin API available immediately without relying
# on the global CTFd_API_v1 initialization order.
photo_bp = Blueprint("photo_challenges_api", __name__, template_folder="templates")
photo_api = Api(photo_bp, doc=False)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _maybe_send_ntfy(challenge_id=None, challenge_name=None, team_id=None, submission_id=None):
    """Send a push to an ntfy endpoint if `PHOTO_NTFY_URL` is set in app config.

    The URL is read from `current_app.config['PHOTO_NTFY_URL']` and is never
    exposed to clients. Optionally configure `PHOTO_NTFY_HEADERS` as a dict of
    extra headers (e.g. Authorization) to include with the request.
    """
    # Prefer app config, but fall back to environment variable so users
    # can set PHOTO_NTFY_URL via docker-compose / .env without modifying
    # CTFd config objects.
    ntfy_url = current_app.config.get('PHOTO_NTFY_URL') or os.environ.get('PHOTO_NTFY_URL')
    if not ntfy_url:
        # Log both config and environment values to help debug missing config
        cfg_val = current_app.config.get('PHOTO_NTFY_URL')
        env_val = os.environ.get('PHOTO_NTFY_URL')
        current_app.logger.info("photo_challenges: PHOTO_NTFY_URL not configured, skipping push (config=%s env=%s)", cfg_val, env_val)
        return

    current_app.logger.info("photo_challenges: sending ntfy push to %s", ntfy_url)

    # Resolve challenge name if not provided
    if not challenge_name and challenge_id is not None:
        try:
            chal = Challenges.query.filter_by(id=challenge_id).first()
            if chal:
                challenge_name = chal.name
        except Exception:
            challenge_name = str(challenge_id)

    title = f"Photo submission: {challenge_name or challenge_id or 'unknown'}"
    body = f"Team {team_id} submitted a photo for '{challenge_name or challenge_id}'. Submission ID: {submission_id}"

    headers = {}
    # Prefer config, fall back to environment variable
    extra = current_app.config.get('PHOTO_NTFY_HEADERS') or os.environ.get('PHOTO_NTFY_HEADERS')
    if isinstance(extra, dict):
        headers.update(extra)
    elif isinstance(extra, str) and extra:
        # Allow JSON string in env var: PHOTO_NTFY_HEADERS='{"Authorization":"Basic ..."}'
        try:
            parsed = json.loads(extra)
            if isinstance(parsed, dict):
                headers.update(parsed)
        except Exception:
            # ignore parse errors
            pass
    # ntfy supports a "Title" header for notifications
    headers.setdefault('Title', title)

    # Try requests first, fall back to urllib
    try:
        # Try requests if available (prefer it for better error visibility)
        try:
            import requests
            resp = requests.post(ntfy_url, data=body.encode('utf-8'), headers=headers, timeout=5)
            current_app.logger.info("photo_challenges: ntfy response status=%s len=%s", getattr(resp, 'status_code', None), len(getattr(resp, 'text', '') or ""))
            return
        except Exception as e:
            current_app.logger.debug("photo_challenges: requests post failed, falling back to urllib: %s", e, exc_info=True)

        # Fallback to urllib
        from urllib.request import Request, urlopen
        req = Request(ntfy_url, data=body.encode('utf-8'), headers=headers)
        urlopen(req, timeout=5)
        current_app.logger.info("photo_challenges: ntfy push sent via urllib")
    except Exception:
        current_app.logger.exception("photo_challenges: ntfy send failed")

@photo_bp.route("/upload/<int:challenge_id>", methods=["GET","POST"])
@authed_only
@during_ctf_time_only
@bypass_csrf_protection
def upload(challenge_id):
    if request.method == "POST":
        if "photo" not in request.files:
            flash("No file part", "danger")
            return redirect(request.url)
        file = request.files["photo"]
        if file.filename == "":
            flash("No selected file", "danger")
            return redirect(request.url)
        if not allowed_file(file.filename):
            flash("Invalid file type", "danger")
            return redirect(request.url)
        filename = secure_filename(file.filename)
        filename = f"{secrets.token_hex(8)}_{filename}"
        # Use CTFd uploader (honors UPLOAD_FOLDER or S3) to store files in a writable location
        location = f"photo_evidence/{filename}"
        file_row = upload_file(file=file, challenge_id=challenge_id, type="challenge", location=location)
        path = file_row.location

        user = get_current_user()
        team = get_current_team()
        team_id = team.id if team else (user.id if user else None)
        submission = PhotoSubmission(team_id=team_id, challenge_id=challenge_id, filename=filename, filepath=path)
        db.session.add(submission)
        db.session.commit()

        # Mark the challenge as paused (pending review) so teams see it's awaiting verification
        try:
            chal = Challenges.query.filter_by(id=challenge_id).first()
            if chal:
                chal.state = "paused"
                db.session.commit()
        except Exception:
            db.session.rollback()

        # Notify the team that their submission is pending review
        challenge_name = None
        try:
            chal = Challenges.query.filter_by(id=challenge_id).first()
            challenge_name = chal.name if chal else str(challenge_id)
            note = Notifications(title="Photo submission pending", content=f"Your photo submission for challenge '{challenge_name}' is pending review.", team_id=team_id)
            db.session.add(note)
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Send optional server-side ntfy push (kept secret on server)
        try:
            # Diagnostic log: show whether PHOTO_NTFY_URL is visible to the app/env
            try:
                cfg_val = current_app.config.get('PHOTO_NTFY_URL')
            except Exception:
                cfg_val = None
            env_val = os.environ.get('PHOTO_NTFY_URL')
            current_app.logger.info("photo_challenges: calling _maybe_send_ntfy (cfg=%s env=%s)", cfg_val, env_val)
            _maybe_send_ntfy(challenge_name=challenge_name, team_id=team_id, submission_id=submission.id)
        except Exception:
            current_app.logger.exception("photo_challenges: ntfy push failed")
        
        flash("Photo submitted for review", "success")
        return redirect(url_for("challenges.view", challenge_id=challenge_id))

    challenge = Challenges.query.filter_by(id=challenge_id).first()
    return render_template("upload.html", challenge=challenge)



@photo_namespace.route("/upload", methods=["POST"])
class UploadPhoto(Resource):
    """API endpoint to accept a photo upload for a challenge (RESTX Resource)."""
    method_decorators = [authed_only, bypass_csrf_protection]

    def post(self):
        current_app.logger.info("photo_challenges: UploadPhoto.post invoked; files=%s form_keys=%s remote=%s", list(request.files.keys()), list(request.form.keys()), request.remote_addr)
        if "file" not in request.files:
            return {"success": False, "message": "No file"}, 400

        file = request.files["file"]
        challenge_id = request.form.get("challenge_id")

        if not file or not challenge_id:
            return {"success": False, "message": "Invalid submission"}, 400

        if not allowed_file(file.filename):
            return {"success": False, "message": "Invalid file type"}, 400

        filename = secure_filename(file.filename)
        filename = f"{secrets.token_hex(8)}_{filename}"
        location = f"photo_evidence/{filename}"
        file_row = upload_file(file=file, challenge_id=int(challenge_id), type="challenge", location=location)
        path = file_row.location

        user = get_current_user()
        team = get_current_team()
        team_id = team.id if team else (user.id if user else None)

        submission = PhotoSubmission(team_id=team_id, challenge_id=int(challenge_id), filename=filename, filepath=path)
        db.session.add(submission)
        db.session.commit()

        # Mark the challenge as paused (pending review)
        try:
            chal = Challenges.query.filter_by(id=int(challenge_id)).first()
            if chal:
                chal.state = "paused"
                db.session.commit()
        except Exception:
            db.session.rollback()

        # Notify the team
        challenge_name = None
        try:
            chal = Challenges.query.filter_by(id=int(challenge_id)).first()
            challenge_name = chal.name if chal else str(challenge_id)
            note = Notifications(title="Photo submission pending", content=f"Your photo submission for challenge '{challenge_name}' is pending review.", team_id=team_id)
            db.session.add(note)
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Send optional server-side ntfy push
        try:
            # Diagnostic log: show whether PHOTO_NTFY_URL is visible to the app/env
            try:
                cfg_val = current_app.config.get('PHOTO_NTFY_URL')
            except Exception:
                cfg_val = None
            env_val = os.environ.get('PHOTO_NTFY_URL')
            current_app.logger.info("photo_challenges: calling _maybe_send_ntfy (cfg=%s env=%s)", cfg_val, env_val)
            _maybe_send_ntfy(challenge_name=challenge_name, team_id=team_id, submission_id=submission.id)
        except Exception:
            current_app.logger.exception("photo_challenges: ntfy push failed")

        return {"success": True, "message": "Photo submitted for review", "submission_id": submission.id}


@photo_namespace.route("/status/<int:challenge_id>")
class SubmissionStatus(Resource):
    """Return whether the current user/team has a pending submission for the challenge."""
    method_decorators = [authed_only]

    def get(self, challenge_id):
        user = get_current_user()
        team = get_current_team()
        team_id = team.id if team else (user.id if user else None)

        status = None
        if team_id is not None:
            sub = (
                PhotoSubmission.query.filter_by(team_id=team_id, challenge_id=challenge_id)
                .order_by(PhotoSubmission.submitted_at.desc())
                .first()
            )
            if sub:
                status = sub.status

        return {"status": status}


# Admin review UI and actions
@photo_namespace.route("/admin/review")
class AdminReview(Resource):
    method_decorators = [admins_only]

    def get(self):
        # list pending submissions
        # Only include submissions whose file record still exists in the Files/ChallengeFiles table
        submissions = (
            PhotoSubmission.query.order_by(PhotoSubmission.submitted_at.desc()).all()
        )
        valid_submissions = []
        for s in submissions:
            if s.filepath and Files.query.filter_by(location=s.filepath).first():
                valid_submissions.append(s)

        # Render the admin review HTML. Some admin UI code fetches this
        # endpoint via XHR and expects JSON. Detect Accept header and
        # return JSON-wrapped HTML when appropriate to avoid the UI
        # attempting to parse HTML as JSON.
        rendered = render_template('admin_review.html', submissions=valid_submissions)
        accept = request.headers.get('Accept', '')
        if 'application/json' in accept:
            return {'html': rendered}

        return rendered


@photo_namespace.route('/admin/review/<int:submission_id>/approve', methods=['POST'])
class AdminApprove(Resource):
    method_decorators = [admins_only]

    def post(self, submission_id):
        sub = PhotoSubmission.query.filter_by(id=submission_id).first_or_404()
        sub.status = 'approved'
        sub.reviewed_at = datetime.utcnow()
        sub.review_notes = request.form.get('notes', '')
        db.session.add(sub)

        # award solve if not already solved for this team/user
        try:
            chal = Challenges.query.filter_by(id=sub.challenge_id).first()
            if chal:
                chal.state = 'visible'
            # Create a Solves record if not exists
            existing_solve = Solves.query.filter_by(challenge_id=sub.challenge_id, team_id=sub.team_id).first()
            if not existing_solve:
                solve = Solves(challenge_id=sub.challenge_id, user_id=None, team_id=sub.team_id, ip=None, provided=sub.filename)
                db.session.add(solve)
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Notify team with details and mark other pending submissions cleared
        try:
            chal = Challenges.query.filter_by(id=sub.challenge_id).first()
            challenge_name = chal.name if chal else str(sub.challenge_id)
            content = f"Your photo submission for challenge '{challenge_name}' was approved."
            if sub.review_notes:
                content += f"\nReview notes: {sub.review_notes}"

            note = Notifications(title='Photo submission approved', content=content, team_id=sub.team_id)
            db.session.add(note)
            # Mark any other pending submissions for this team/challenge as rejected/cleared
            PhotoSubmission.query.filter_by(team_id=sub.team_id, challenge_id=sub.challenge_id, status='pending').update({"status": "rejected"})
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Return JSON for XHR/JSON clients, otherwise redirect to the
        # admin review page so browser form submits still work.
        rendered = render_template('admin_review.html', submissions=PhotoSubmission.query.order_by(PhotoSubmission.submitted_at.desc()).all())
        accept = request.headers.get('Accept', '')
        if 'application/json' in accept or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": True, "submission_id": sub.id, "status": "approved", "html": rendered}
        return redirect('/api/v1/photo_challenges/admin/review')


@photo_namespace.route('/admin/review/<int:submission_id>/reject', methods=['POST'])
class AdminReject(Resource):
    method_decorators = [admins_only]

    def post(self, submission_id):
        sub = PhotoSubmission.query.filter_by(id=submission_id).first_or_404()
        sub.status = 'rejected'
        sub.reviewed_at = datetime.utcnow()
        sub.review_notes = request.form.get('notes', '')
        db.session.add(sub)
        try:
            # set challenge visible so team can resubmit
            chal = Challenges.query.filter_by(id=sub.challenge_id).first()
            if chal:
                chal.state = 'visible'
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Notify team and ensure any pending flags are cleared so challenge is submittable
        try:
            chal = Challenges.query.filter_by(id=sub.challenge_id).first()
            challenge_name = chal.name if chal else str(sub.challenge_id)
            content = f"Your photo submission for challenge '{challenge_name}' was rejected."
            if sub.review_notes:
                content += f"\nReview notes: {sub.review_notes}"

            note = Notifications(title='Photo submission rejected', content=content, team_id=sub.team_id)
            db.session.add(note)
            # Clear any other pending submissions for this team/challenge
            PhotoSubmission.query.filter_by(team_id=sub.team_id, challenge_id=sub.challenge_id, status='pending').update({"status": "rejected"})
            # Ensure challenge is visible/submittable again
            if chal:
                chal.state = 'visible'
            db.session.commit()
        except Exception:
            db.session.rollback()

        rendered = render_template('admin_review.html', submissions=PhotoSubmission.query.order_by(PhotoSubmission.submitted_at.desc()).all())
        accept = request.headers.get('Accept', '')
        if 'application/json' in accept or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": True, "submission_id": sub.id, "status": "rejected", "html": rendered}
        return redirect('/api/v1/photo_challenges/admin/review')


@photo_namespace.route('/admin/file/<path:filename>')
class AdminFile(Resource):
    method_decorators = [admins_only]

    def get(self, filename):
        # Ensure a Files record exists for this location
        f = Files.query.filter_by(location=filename).first()
        if not f:
            current_app.logger.info("photo_challenges: admin file requested but DB record missing: %s", filename)
            abort(404)

        uploader = get_uploader()
        # Prefer serving local filesystem files inline; log diagnostic info so container logs show what's happening
        try:
            base = getattr(uploader, "base_path", None)
            current_app.logger.info("photo_challenges: serving admin file %s using uploader=%s base=%s", filename, type(uploader).__name__, base)
            if base:
                # compute path and verify existence explicitly
                file_path = os.path.join(base, filename)
                current_app.logger.info("photo_challenges: computed file_path=%s exists=%s", file_path, os.path.exists(file_path))
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    return send_file(file_path, as_attachment=False)

            # Fall back to uploader.download (e.g., S3 redirect) if local file not found
            current_app.logger.info("photo_challenges: falling back to uploader.download for %s", filename)
            return uploader.download(filename)
        except Exception as e:
            current_app.logger.exception("photo_challenges: error serving admin file %s: %s", filename, e)
            abort(404)


# Admin UI landing page mapped to `/admin/photo_evidence` (plugin menu target)
@admins_only
def admin_page():
    """Render the admin review template so the admin menu link works."""
    submissions = PhotoSubmission.query.order_by(PhotoSubmission.submitted_at.desc()).all()
    valid_submissions = []
    for s in submissions:
        if s.filepath and Files.query.filter_by(location=s.filepath).first():
            valid_submissions.append(s)

    return render_template('admin_review.html', submissions=valid_submissions)


# --- Fallback view functions (used by plugin load to register direct Flask rules) ---
def upload_photo_fallback():
    """Fallback view that delegates to the API upload handler.

    This exists so `__init__.py` can register a direct Flask URL rule
    in environments where the RESTX namespace isn't attached yet.
    """
    current_app.logger.info("photo_challenges: upload_photo_fallback invoked; files=%s form_keys=%s remote=%s", list(request.files.keys()), list(request.form.keys()), request.remote_addr)
    if "file" not in request.files:
        return {"success": False, "message": "No file"}, 400

    file = request.files["file"]
    challenge_id = request.form.get("challenge_id")

    if not file or not challenge_id:
        return {"success": False, "message": "Invalid submission"}, 400

    if not allowed_file(file.filename):
        return {"success": False, "message": "Invalid file type"}, 400

    filename = secure_filename(file.filename)
    filename = f"{secrets.token_hex(8)}_{filename}"
    location = f"photo_evidence/{filename}"
    file_row = upload_file(file=file, challenge_id=int(challenge_id), type="challenge", location=location)
    path = file_row.location

    user = get_current_user()
    team = get_current_team()
    team_id = team.id if team else (user.id if user else None)

    submission = PhotoSubmission(team_id=team_id, challenge_id=int(challenge_id), filename=filename, filepath=path)
    db.session.add(submission)
    db.session.commit()

    # Mark the challenge as paused (pending review)
    try:
        chal = Challenges.query.filter_by(id=int(challenge_id)).first()
        if chal:
            chal.state = "paused"
            db.session.commit()
    except Exception:
        db.session.rollback()

    # Notify the team
    try:
        note = Notifications(title="Photo submission pending", content=f"Your photo for challenge {challenge_id} is pending review.", team_id=team_id)
        db.session.add(note)
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Send optional server-side ntfy push for fallback handler as well
    try:
        # Resolve challenge name for message clarity
        challenge_name = None
        try:
            chal = Challenges.query.filter_by(id=int(challenge_id)).first()
            challenge_name = chal.name if chal else str(challenge_id)
        except Exception:
            challenge_name = str(challenge_id)

        try:
            cfg_val = current_app.config.get('PHOTO_NTFY_URL')
        except Exception:
            cfg_val = None
        env_val = os.environ.get('PHOTO_NTFY_URL')
        current_app.logger.info("photo_challenges: upload_photo_fallback calling _maybe_send_ntfy (cfg=%s env=%s)", cfg_val, env_val)
        _maybe_send_ntfy(challenge_id=int(challenge_id), challenge_name=challenge_name, team_id=team_id, submission_id=submission.id)
    except Exception:
        current_app.logger.exception("photo_challenges: ntfy push failed in fallback")

    return {"success": True, "message": "Photo submitted for review", "submission_id": submission.id}


def submission_status_fallback(challenge_id):
    """Fallback view that delegates to the submission status handler."""
    user = get_current_user()
    team = get_current_team()
    team_id = team.id if team else (user.id if user else None)

    status = None
    if team_id is not None:
        sub = (
            PhotoSubmission.query.filter_by(team_id=team_id, challenge_id=challenge_id)
            .order_by(PhotoSubmission.submitted_at.desc())
            .first()
        )
        if sub:
            status = sub.status

    return {"status": status}


@admins_only
def admin_file_fallback(filename):
    """Fallback view to serve uploaded files to admins.

    Mirrors the logic in `AdminFile.get` so the plugin can register a
    direct Flask URL rule even if the RESTX namespace isn't available.
    """
    # Ensure a Files record exists for this location
    f = Files.query.filter_by(location=filename).first()
    if not f:
        current_app.logger.info("photo_challenges: admin file requested but DB record missing: %s", filename)
        abort(404)

    uploader = get_uploader()
    try:
        base = getattr(uploader, "base_path", None)
        current_app.logger.info("photo_challenges: serving admin file %s using uploader=%s base=%s", filename, type(uploader).__name__, base)
        if base:
            file_path = os.path.join(base, filename)
            current_app.logger.info("photo_challenges: computed file_path=%s exists=%s", file_path, os.path.exists(file_path))
            if os.path.exists(file_path) and os.path.isfile(file_path):
                return send_file(file_path, as_attachment=False)

        current_app.logger.info("photo_challenges: falling back to uploader.download for %s", filename)
        return uploader.download(filename)
    except Exception as e:
        current_app.logger.exception("photo_challenges: error serving admin file %s: %s", filename, e)
        abort(404)


# Admin action fallbacks so `load(app)` can register direct POST rules
@admins_only
def admin_approve_fallback(submission_id):
    """Fallback wrapper that calls the AdminApprove Resource.post method."""
    try:
        # instantiate resource and delegate
        res = AdminApprove()
        return res.post(submission_id)
    except Exception:
        current_app.logger.exception("photo_challenges: admin approve fallback failed")
        abort(500)


@admins_only
def admin_reject_fallback(submission_id):
    """Fallback wrapper that calls the AdminReject Resource.post method."""
    try:
        res = AdminReject()
        return res.post(submission_id)
    except Exception:
        current_app.logger.exception("photo_challenges: admin reject fallback failed")
        abort(500)
