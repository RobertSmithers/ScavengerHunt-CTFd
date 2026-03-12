from flask import Blueprint
from flask_restx import Namespace, Resource

from CTFd.plugins.challenges import BaseChallenge, CHALLENGE_CLASSES
from CTFd.plugins import register_plugin_assets_directory
from .routes import photo_namespace
from .models import PhotoSubmission
from CTFd.plugins.migrations import upgrade
from CTFd.api import CTFd_API_v1

from CTFd.models import (
    ChallengeFiles,
    Challenges,
    Fails,
    Flags,
    Hints,
    Solves,
    Tags,
    db,
    Awards,
)
from CTFd.utils.logging import log

photo_namespace = Namespace("photos", description="Endpoint to handle photo evidence submissions")

class PhotoChallengeModel(Challenges):
    __mapper_args__ = {"polymorphic_identity": "photo"}
    id = db.Column(db.Integer, 
        db.ForeignKey("challenges.id", ondelete="CASCADE"), 
        primary_key=True)

class PhotoChallengeType(BaseChallenge):
    # Use the short type identifier `photo` to match values stored in the
    # `challenges.type` column (CTFd expects challenge.type to match the
    # registered challenge class id).
    id = "photo"
    name = "Photo Challenge"
    templates = {
        "create": "/plugins/photo_challenges/assets/create.html",
        "update": "/plugins/photo_challenges/assets/update.html",
        "view": "/plugins/photo_challenges/assets/view.html",
    }
    scripts = {
        "create": "/plugins/photo_challenges/assets/create.js",
        "update": "/plugins/photo_challenges/assets/update.js",
        "view": "/plugins/photo_challenges/assets/view.js"
    }
    route = "/plugins/photo_challenges/assets"
    blueprint = Blueprint(
        "photo_challenges", __name__,
        template_folder="templates",
        static_folder="assets"
    )
    challenge_model = PhotoChallengeModel # Use default Challenges table

    @classmethod
    def attempt(cls, challenge, request):
        """
        This method is used to check whether a given input is right or wrong.
        Since photo challenges require manual review, we always return False here.
        However, we can set the submission to a "pending review" status.
        ...
             Parameters
                ----------
                challenge : Challenge
                    The Challenge object from the database
                submission : request
                    The submitted request by player

            Returns
                -------
                (boolean, String)
                    (is flag correct, message to show)
        """
        data = request.form or request.get_json()
        provided = data.get("submission", "").strip()
        
        # Log incoming request metadata for debugging
        print("Photo Challenge Attempt: Logging request metadata")
        print("Content-Type:", request.content_type)
        print("Headers:", request.headers)
        try:
            print(f"[photo] attempt called: content_type={request.content_type} headers={request.headers.get('Content-Type')}")
            keys = ",".join(list(request.files.keys()))
            print(f"[photo] request.files keys: {keys}")
            # Log uploaded filenames (do not log file content)
            for k in request.files:
                f = request.files[k]
                print(f"[photo] uploaded file field={k} filename={getattr(f, 'filename', None)}")
            print(f"[photo] request.form keys: {','.join(list(request.form.keys()))}")
        except Exception as e:
            print(f"[photo] error logging request: {str(e)}")

        # We DO NOT accept flags — require an uploaded file
        if "file" not in request.files:
            return False, "No photo uploaded"

        photo = request.files["file"]
        if not photo or photo.filename == "":
            return False, "Invalid photo"

        # Save photo somewhere (plugin `routes.py` currently handles uploads for review)
        # Mark submission as pending (NOT solved)
        return False, "Photo submitted for review"

    @classmethod
    def delete(cls, challenge):
        """
        This method is used to delete the resources used by a challenge.
        :param challenge:
        :return:
        """
        # Delete all photo submissions associated with the challenge
        PhotoSubmission.query.filter_by(challenge_id=challenge.id).delete()

        # Call base class delete to remove standard challenge resources
        super().delete(challenge)

    @classmethod
    def update(cls, challenge, request):
        """
        This method is used to update the challenge with new information.
        :param challenge:
        :param request:
        :return:
        """
        data = request.form or request.get_json()

        for key, value in data.items():
            if hasattr(challenge, key):
                setattr(challenge, key, value)

        db.session.commit()
        return challenge

def load(app):
    upgrade(plugin_name="photo_challenges")
    app.db.create_all()

    # # Register your blueprint routes
    app.register_blueprint(PhotoChallengeType.blueprint)

    CHALLENGE_CLASSES[PhotoChallengeType.id] = PhotoChallengeType

    # Register static folder so assets are accessible
    register_plugin_assets_directory(
        app,
        base_path="/plugins/photo_challenges/assets"
    )

    # Register API namespace so endpoints are available under `/api/v1/photo_challenges`.
    # Namespace registration may race with application/API initialization, so
    # defer registration until the app is fully initialized. Using
    # `before_first_request` ensures the RESTX API object exists and we avoid
    # ad-hoc `add_url_rule` hacks.
    def _register_namespaces():
        try:
            CTFd_API_v1.add_namespace(photo_namespace, '/photo_challenges')
            app.logger.info("photo_challenges: registered RESTX namespace /photo_challenges")
        except Exception:
            # If registration fails for any reason, silently ignore — the
            # plugin will still expose functionality via the blueprint
            # (static/templates) and a future request can surface errors.
            pass

    app.before_first_request(_register_namespaces)

    # As a robust fallback for cases where the RESTX namespace isn't
    # immediately available (due to app/plugin init ordering), also
    # register direct Flask URL rules that map to the Resource classes
    # defined in `routes.py`. This preserves canonical RESTX usage while
    # ensuring the endpoints remain reachable in all environments.
    try:
        # import here to avoid circular import at module import time
        from .routes import upload_photo_fallback, submission_status_fallback
        # import decorators to wrap fallback views appropriately
        from CTFd.utils.decorators import authed_only
        from CTFd.plugins import bypass_csrf_protection

        app.logger.info("photo_challenges: adding fallback url rules")
        # Ensure POST upload bypasses CSRF but still requires an authenticated user
        upload_view = bypass_csrf_protection(authed_only(upload_photo_fallback))

        app.add_url_rule(
            "/api/v1/photo_challenges/upload",
            endpoint="photo_challenges.upload",
            view_func=upload_view,
            methods=["POST"],
        )

        # Status endpoint should require auth but does not need CSRF bypass
        app.add_url_rule(
            "/api/v1/photo_challenges/status/<int:challenge_id>",
            endpoint="photo_challenges.status",
            view_func=authed_only(submission_status_fallback),
            methods=["GET"],
        )
        # Admin file serving fallback
        try:
            from .routes import admin_file_fallback
            app.add_url_rule(
                "/api/v1/photo_challenges/admin/file/<path:filename>",
                endpoint="photo_challenges.admin_file",
                view_func=admin_file_fallback,
                methods=["GET"],
            )
        except Exception:
            app.logger.exception("photo_challenges: failed to register admin file fallback")
        # Register admin approve/reject fallbacks
        try:
            from .routes import admin_approve_fallback, admin_reject_fallback
            from CTFd.utils.decorators import admins_only

            app.add_url_rule(
                "/api/v1/photo_challenges/admin/review/<int:submission_id>/approve",
                endpoint="photo_challenges.admin_review_approve",
                view_func=admins_only(admin_approve_fallback),
                methods=["POST"],
            )

            app.add_url_rule(
                "/api/v1/photo_challenges/admin/review/<int:submission_id>/reject",
                endpoint="photo_challenges.admin_review_reject",
                view_func=admins_only(admin_reject_fallback),
                methods=["POST"],
            )
        except Exception:
            app.logger.exception("photo_challenges: failed to register admin approve/reject fallbacks")
        # Log any rules that include our plugin prefix to aid debugging
        try:
            rules = [r.rule for r in app.url_map.iter_rules() if 'photo_challenges' in r.endpoint or 'photo_challenges' in r.rule]
            app.logger.info(f"photo_challenges: fallback rules added, matching rules: {rules}")
        except Exception:
            app.logger.info("photo_challenges: fallback rules added (unable to enumerate url_map)")
    except Exception:
        # If these rules cannot be added (e.g., during tests or import
        # ordering issues), ignore and rely on RESTX namespace registration.
        app.logger.exception("photo_challenges: failed to add fallback url rules")

    # Register admin page and add entry to the Admin Plugins menu
    try:
        from .routes import admin_page
        from CTFd.plugins import register_admin_plugin_menu_bar

        app.add_url_rule(
            "/admin/photo_evidence",
            endpoint="photo_challenges.admin",
            view_func=admin_page,
            methods=["GET"],
        )

        register_admin_plugin_menu_bar("Photo Submissions", "photo_evidence")
        app.logger.info("photo_challenges: registered admin menu link target 'photo_evidence'")
    except Exception:
        app.logger.exception("photo_challenges: failed to register admin page or menu link")