import calendar
import logging
import os

from datetime import date

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.management import call_command
from django.db import transaction
from django.db.models import Q, Avg, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import (
    CourseForm,
    EmploymentForm,
    FollowUpForm,
    ProviderRegistrationForm,
    RetentionRecordForm,
    TraineeForm,
    TrainerRegistrationForm,
    TrainingBatchForm,
    TrainingRelevanceForm,
)

from .models import (
    Course,
    Employment,
    FollowUp,
    Notification,
    OccupationSkill,
    Provider,
    RetentionRecord,
    SelfEmploymentVerification,
    Trainee,
    TrainerRegistration,
    Training,
    TrainingBatch,
    TrainingPerformance,
    TrainingRegistrationRequest,
    TrainingRelevance,
    UANVerification,
    UserProfile,
    WageRecord,
)


logger = logging.getLogger(__name__)


# ==========================================================
# ROLE HELPERS
# ==========================================================

def has_role(user, role):
    return (
        user.is_authenticated
        and (
            user.is_staff
            or getattr(
                getattr(user, "userprofile", None),
                "role",
                None
            ) == role
        )
    )


def is_approved_trainer(user):
    """Return True only when the current user has a verified trainer registration."""
    if not user.is_authenticated:
        return False

    if user.is_staff:
        return True

    return TrainerRegistration.objects.filter(
        user=user,
        status="Verified"
    ).exists()


def authority_required(view):
    return user_passes_test(
        lambda user: has_role(user, "Authority")
    )(view)


def trainer_required(view):
    return user_passes_test(
        lambda user: has_role(user, "Trainer") and is_approved_trainer(user)
    )(view)


def trainee_required(view):
    return user_passes_test(
        lambda user: has_role(user, "Trainee")
    )(view)


# ==========================================================
# COMMON HELPERS
# ==========================================================

def add_months(value, months):
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1

    return date(
        year,
        month,
        min(
            value.day,
            calendar.monthrange(year, month)[1]
        )
    )


def notify(
    user,
    message,
    notification_type="System",
    follow_up=None
):
    if not user:
        return

    Notification.objects.create(
        recipient=user,
        message=message,
        notification_type=notification_type,
        follow_up=follow_up,
    )

    if user.email:
        try:
            send_mail(
                "SkillTrack Maharashtra",
                message,
                None,
                [user.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception(
                "Notification email could not be delivered for user %s",
                user.pk,
            )


def _latest_outcome(trainee):
    return (
        trainee.employment_records
        .order_by("-recorded_on", "-id")
        .first()
    )
import requests
def _risk_insight(trainee):
    """
    Generate AI employment-risk insight for a trainee.

    Data flow:
    TrainingPerformance
        ↓
    Deployed ML API
        ↓
    Employment probability + risk
        ↓
    Combine ML skill gaps + occupation skill gaps
        ↓
    Recommendations
    """

    # ---------------------------------------------------------
    # 1. Get latest training performance
    # ---------------------------------------------------------
    performance = (
        trainee.performance_records
        .order_by("-updated_at")
        .first()
    )

    if not performance:
        logger.warning(
            "ML DEBUG: No TrainingPerformance for trainee %s",
            trainee.pk
        )

        occupation_gaps = _skill_gaps(trainee)

        return {
            "probability": 0,
            "risk": "No Data",
            "outcome": "No training performance",
            "factors": occupation_gaps or [
                "TrainingPerformance record not found"
            ],
            "action": (
                "Enter trainee training performance first."
            ),
            "skill_gaps": occupation_gaps,
            "recommendations": [],
            "prototype": False,
        }

    # ---------------------------------------------------------
    # 2. Prepare ML features
    # ---------------------------------------------------------
    attendance = float(
        performance.attendance_percentage or 0
    )

    assessment = float(
        performance.assessment_score or 0
    )

    practical = float(
        performance.practical_score or 0
    )

    completion = float(
        performance.progress_percentage or 0
    )

    # Experience should represent actual employment experience,
    # not simply whether the trainee has a Training record.
    experience = 1 if Employment.objects.filter(
        trainee=trainee,
        status="Employed"
    ).exists() else 0

    payload = {
        "attendance": attendance,
        "assessment": assessment,
        "practical": practical,
        "completion": completion,
        "experience": experience,
    }

    logger.warning(
        "ML DEBUG INPUT trainee=%s payload=%s",
        trainee.pk,
        payload
    )

    # ---------------------------------------------------------
    # 3. Call deployed ML API
    # ---------------------------------------------------------
    try:
        response = requests.post(
            "https://mlapi-7kho.onrender.com/predict",
            json=payload,
            timeout=30,
        )

        logger.warning(
            "ML DEBUG RESPONSE status=%s body=%s",
            response.status_code,
            response.text
        )

        response.raise_for_status()

        result = response.json()

        logger.warning(
            "ML DEBUG JSON=%s",
            result
        )

        # -----------------------------------------------------
        # 4. Get ML-generated skill gaps
        # -----------------------------------------------------
        ml_gaps = result.get(
            "skill_gaps",
            []
        ) or []

        # -----------------------------------------------------
        # 5. Get occupation/job-role skill gaps
        # -----------------------------------------------------
        occupation_gaps = _skill_gaps(trainee) or []

        # -----------------------------------------------------
        # 6. Combine both sources
        #
        # ML gaps:
        #   Assessment Performance
        #   Course Completion
        #
        # Occupation gaps:
        #   Django
        #   SQL
        #   Python
        #   etc.
        # -----------------------------------------------------
        combined_gaps = []

        for gap in ml_gaps + occupation_gaps:
            if gap and gap not in combined_gaps:
                combined_gaps.append(gap)

        # -----------------------------------------------------
        # 7. Get recommendations from ML API
        # -----------------------------------------------------
        recommendations = result.get(
            "recommendations",
            []
        ) or []

        # Remove duplicate recommendations
        unique_recommendations = []

        for recommendation in recommendations:
            if (
                recommendation
                and recommendation not in unique_recommendations
            ):
                unique_recommendations.append(
                    recommendation
                )

        # -----------------------------------------------------
        # 8. Create readable action text
        # -----------------------------------------------------
        action = " | ".join(
            unique_recommendations
        )

        if not action:
            action = (
                "Continue training and placement support."
            )

        # -----------------------------------------------------
        # 9. Return final insight
        # -----------------------------------------------------
        return {
            "probability": result.get(
                "employment_probability",
                result.get("probability", 0)
            ),

            "risk": result.get(
                "risk",
                "Unknown"
            ),

            "outcome": result.get(
                "outcome",
                "Prediction available"
            ),

            # Combined skill gaps
            "factors": combined_gaps,

            "action": action,

            # This is what your UI should use
            "skill_gaps": combined_gaps,

            "recommendations": unique_recommendations,

            "prototype": False,
        }

    # ---------------------------------------------------------
    # 10. Handle ML API / network / JSON errors
    # ---------------------------------------------------------
    except Exception as e:

        logger.exception(
            "ML DEBUG ERROR trainee=%s error=%s",
            trainee.pk,
            e
        )

        occupation_gaps = _skill_gaps(trainee)

        return {
            "probability": 0,
            "risk": "Error",
            "outcome": "ML prediction failed",
            "factors": occupation_gaps or [
                "Unable to obtain ML prediction"
            ],
            "action": (
                "Check ML service and Render logs."
            ),
            "skill_gaps": occupation_gaps,
            "recommendations": [],
            "prototype": False,
        }
def _skill_gaps(trainee):
    outcome = _latest_outcome(trainee)

    if not outcome or not outcome.job_role:
        return []

    required = (
        OccupationSkill.objects
        .filter(
            occupation__iexact=outcome.job_role
        )
        .values_list("skill", flat=True)
    )

    taught = []

    for training in (
        trainee.training_set
        .select_related("course")
    ):
        if training.course.skills_taught:
            taught.extend(
                x.strip().lower()
                for x in training.course.skills_taught.split(",")
                if x.strip()
            )

    return [
        skill
        for skill in required
        if skill.lower() not in taught
    ]


# ==========================================================
# FOLLOW-UP GENERATION
# ==========================================================

def generate_followups(batch):

    completion_date = (
        batch.completion_date
        or date.today()
    )

    schedule = [
        ("3 Months", 3),
        ("6 Months", 6),
        ("1 Year", 12),
        ("3 Years", 36),
        ("5 Years", 60),
    ]

    for trainee in batch.trainees.all():

        employment = (
            Employment.objects
            .filter(trainee=trainee)
            .order_by("-recorded_on", "-id")
            .first()
        )

        status = (
            employment.status
            if employment
            else "Seeking"
        )

        profile = (
            UserProfile.objects
            .filter(
                trainee=trainee,
                role="Trainee"
            )
            .select_related("user")
            .first()
        )

        for label, months in schedule:

            follow_up, _ = (
                FollowUp.objects
                .get_or_create(
                    trainee=trainee,
                    followup_type=label,
                    defaults={
                        "date": add_months(
                            completion_date,
                            months
                        ),
                        "employment_status": status,
                    },
                )
            )

            if profile:
                notify(
                    profile.user,
                    (
                        f"Your {label.lower()} employment "
                        f"follow-up is scheduled for "
                        f"{follow_up.date:%d %B %Y}."
                    ),
                    "Follow-up",
                    follow_up,
                )


# ==========================================================
# LOGIN / LOGOUT
# ==========================================================

def redirect_for_user(user, request):
    profile = getattr(user, "userprofile", None)


    if profile is None or not profile.role:
        return redirect("choose_role")

    role = profile.role

    if user.is_staff or role == "Authority":
        return redirect("dashboard")


    if role == "Trainer":
        if is_approved_trainer(user):
            return redirect("trainer_dashboard")

        messages.info(
            request,
            "Your trainer registration is still pending Authority approval."
        )
        return redirect("pending_page")


    if role == "Trainee":
        return redirect("trainee_dashboard")


    return redirect("login")

def login_view(request):

    if request.user.is_authenticated:
        return redirect_for_user(request.user, request)

    if request.method == "POST":

        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )

        if user:
            login(request, user)
            return redirect_for_user(user, request)

        messages.error(
            request,
            "Invalid username or password."
        )

    return render(
        request,
        "login.html"
    )


def logout_view(request):
    logout(request)
    return redirect("login")


# ==========================================================
# TRAINEE REGISTRATION
# ==========================================================




def trainee_register(request):

    user = request.user

    # Existing SkillTrack trainee
    if user.is_authenticated:
        profile = getattr(user, "userprofile", None)

        if profile and profile.role == "Trainee" and profile.trainee:
            return redirect_for_user(user, request)

    form = TraineeForm(request.POST or None)

    if request.method == "POST":

        print("TRAINEE POST RECEIVED")
        print("POST DATA:", request.POST)

        if form.is_valid():

            print("FORM VALID")

            with transaction.atomic():

                # Generate beneficiary ID
                last_trainee = (
                    Trainee.objects
                    .select_for_update()
                    .order_by("-id")
                    .first()
                )

                beneficiary_id = (
                    f"MH-2026-{(last_trainee.id + 1 if last_trainee else 1):06d}"
                )

                trainee = form.save(commit=False)

                # Connect user only if logged in
                if user.is_authenticated:
                    trainee.user = user

                trainee.beneficiary_id = beneficiary_id
                trainee.status = "Pending"

                # Use Google user's email if logged in
                # and trainee email was not entered
                if user.is_authenticated and not trainee.email:
                    trainee.email = user.email

                trainee.save()

                # Create/update SkillTrack profile
                # ONLY for authenticated users
                if user.is_authenticated:
                    UserProfile.objects.update_or_create(
                        user=user,
                        defaults={
                            "role": "Trainee",
                            "trainee": trainee,
                        }
                    )

            messages.success(
                request,
                "Registration submitted successfully. "
                "Your application is now pending Authority verification."
            )

            return render(
                request,
                "trainees/registration_success.html",
                {
                    "trainee": trainee
                }
            )

        else:
            print("TRAINEE FORM ERRORS:", form.errors)

    return render(
        request,
        "trainees/trainee_register.html",
        {
            "form": form
        }
    )




# ==========================================================
# TRAINER REGISTRATION
# ==========================================================


def trainer_register(request):

    user = request.user

    # If already registered as Trainer, go to dashboard
    profile = getattr(user, "userprofile", None)

    if profile and profile.role == "Trainer":
        return redirect_for_user(user, request)

    form = TrainerRegistrationForm(
        request.POST or None
    )

    if request.method == "POST" and form.is_valid():

        with transaction.atomic():

            trainer = form.save(commit=False)


            trainer.user = user
            trainer.status = "Pending"
            trainer.email = user.email
            trainer.save()

            UserProfile.objects.update_or_create(
                user=user,
                defaults={"role": "Trainer"}
            )

        messages.success(
            request,
            "Registration submitted successfully. "
            "Your application is now Pending Authority verification."
        )

        logout(request)

        return redirect("login")

    return render(
        request,
        "trainers/trainer_register.html",
        {
            "form": form
        }
    )


def provider_register(request):
    """Public provider application; approval remains an Authority action."""
    form = ProviderRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        provider = form.save(commit=False)
        provider.status = "Pending"
        provider.save()
        messages.success(request, "Provider registration submitted for Authority review.")
        return redirect("login")
    return render(request, "providers/provider_register.html", {"form": form})


# ==========================================================
# AUTHORITY DASHBOARD
# ==========================================================

@login_required
@authority_required
def dashboard(request):

    trainees = Trainee.objects.all()
    trainers = TrainerRegistration.objects.all()
    providers = Provider.objects.all()
    batches = TrainingBatch.objects.all()
    employments = Employment.objects.all()

    trainee_stats = trainees.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status="Pending")),
        verified=Count("id", filter=Q(status="Verified")),
    )

    trainer_stats = trainers.aggregate(
        total=Count("id"),
        verified=Count("id", filter=Q(status="Verified")),
    )

    provider_stats = providers.aggregate(
        total=Count("id"),
        verified=Count("id", filter=Q(status="Verified")),
    )

    batch_stats = batches.aggregate(
        active=Count("id", filter=Q(status="Active")),
        completed=Count("id", filter=Q(status="Completed")),
    )

    employment_stats = employments.aggregate(
        total=Count("id"),
        employed=Count("id", filter=Q(status="Employed")),
        seeking=Count("id", filter=Q(status="Seeking")),
        unemployed=Count("id", filter=Q(status="Unemployed")),
        self_employed=Count("id", filter=Q(status="Self-Employed")),
        apprenticeships=Count("id", filter=Q(status="Apprenticeship")),
    )

    trained = (
        batches
        .filter(status="Completed")
        .aggregate(total=Count("trainees", distinct=True))["total"]
    )

    wage_average = (
        WageRecord.objects
        .aggregate(avg=Avg("amount"))["avg"]
        or 0
    )

    retention_stats = RetentionRecord.objects.aggregate(
        total=Count("id"),
        retained=Count("id", filter=Q(still_employed=True)),
    )

    context = {
        "total_trainees": trainee_stats["total"],
        "pending_trainees": trainee_stats["pending"],
        "verified_trainees": trainee_stats["verified"],
        "total_trainers": trainer_stats["total"],
        "verified_trainers": trainer_stats["verified"],
        "total_providers": provider_stats["total"],
        "verified_providers": provider_stats["verified"],
        "total_courses": Course.objects.count(),
        "active_batches": batch_stats["active"],
        "completed_batches": batch_stats["completed"],
        "trained_trainees": trained or 0,
        "active_training": batch_stats["active"],
        "completed_training": batch_stats["completed"],
        "employed": employment_stats["employed"],
        "seeking": employment_stats["seeking"],
        "unemployed": employment_stats["unemployed"],
        "self_employed": employment_stats["self_employed"],
        "apprenticeships": employment_stats["apprenticeships"],
        "average_wage": round(wage_average),
        "retention_rate": round(
            retention_stats["retained"] * 100 / retention_stats["total"]
        ) if retention_stats["total"] else 0,
        "employment_rate": round(
            employment_stats["employed"] * 100 / employment_stats["total"], 1
        ) if employment_stats["total"] else 0,
        "district_data": list(
            trainees.values("district")
            .annotate(total=Count("id"))
            .order_by("district")
        ),
        "sector_data": list(
            Course.objects.values("sector")
            .annotate(total=Count("id"))
            .order_by("sector")
        ),
        "employment_data": list(
            employments.values("status")
            .annotate(total=Count("id"))
            .order_by("status")
        ),
        "due_followups": (
            FollowUp.objects
            .filter(completed=False, date__lte=date.today())
            .select_related("trainee")[:6]
        ),
    }

    return render(request, "dashboard.html", context)


# ==========================================================
# TRAINEES
# ==========================================================

@login_required
@authority_required
def trainee_list(request):

    return render(
        request,
        "trainees/trainee_list.html",
        {
            "trainees":
                Trainee.objects
                .all()
                .order_by("-id")
        }
    )



@login_required
@authority_required
def trainee_detail(request, id):

    trainee = get_object_or_404(
        Trainee,
        id=id
    )

    # =====================================================
    # BASIC TRAINEE DATA
    # =====================================================

    trainings = (
        trainee.training_set
        .select_related(
            "course",
            "provider",
            "batch",
            "trainer"
        )
        .order_by("-start_date")
    )

    outcomes = (
        trainee.employment_records
        .select_related("training")
        .order_by(
            "-recorded_on",
            "-id"
        )
    )

    # =====================================================
    # AI DATA
    # ONLY RUN FOR VERIFIED TRAINEES
    # =====================================================

    skill_gaps = []
    risk = None

    if trainee.status == "Verified":
        skill_gaps = _skill_gaps(trainee)
        risk = _risk_insight(trainee)



    # =====================================================
    # PAGE
    # =====================================================

    return render(
        request,
        "trainees/trainee_detail.html",
        {
            "trainee": trainee,
            "trainings": trainings,
            "outcomes": outcomes,

            "wages":
                trainee.wage_records.all(),

            "followups":
                trainee.followup_set.all(),

            "retention_records":
                trainee.retention_records
                .all()
                .order_by("-checked_on"),

            "relevance_records":
                trainee.relevance_feedback
                .select_related("training")
                .all(),

            "skill_gaps":
                skill_gaps,

            "risk":
                risk,
        }
    )


@login_required
@authority_required
def trainee_create(request):

    form = TraineeForm(
        request.POST or None
    )

    if request.method == "POST" and form.is_valid():

        trainee = form.save(
            commit=False
        )

        last_trainee = (
            Trainee.objects
            .order_by("-id")
            .first()
        )

        next_id = (
            last_trainee.id + 1
            if last_trainee
            else 1
        )

        trainee.beneficiary_id = (
            f"MH-2026-{next_id:06d}"
        )

        trainee.save()

        messages.success(
            request,
            "Trainee created successfully."
        )

        return redirect(
            "trainee_list"
        )

    return render(
        request,
        "trainees/trainee_form.html",
        {
            "form": form
        }
    )


@login_required
@authority_required
def trainee_update(request, id):

    trainee = get_object_or_404(
        Trainee,
        id=id
    )

    form = TraineeForm(
        request.POST or None,
        instance=trainee
    )

    if request.method == "POST" and form.is_valid():

        form.save()

        messages.success(
            request,
            "Trainee updated successfully."
        )

        return redirect(
            "trainee_detail",
            id=id
        )

    return render(
        request,
        "trainees/trainee_form.html",
        {
            "form": form,
            "trainee": trainee,
        }
    )


@login_required
@authority_required
@require_POST
def verify_trainee(request, id):

    trainee = get_object_or_404(Trainee, id=id)

    # Already verified
    if trainee.status == "Verified":
        messages.info(
            request,
            "This trainee is already verified."
        )
        return redirect("trainee_detail", id=trainee.id)

    # Verify trainee
    trainee.status = "Verified"
    trainee.save(update_fields=["status"])

    # The account is normally created during trainee registration.
    # Reuse it instead of treating an existing account as "already verified".
    user = trainee.user

    # Safety fallback for older records that don't have a linked user
    if not user:
        user = User.objects.get_or_create(
            username=trainee.beneficiary_id,
            defaults={
                "email": trainee.email or "",
            }
        )[0]

        trainee.user = user
        trainee.save(update_fields=["user"])

    # Ensure the correct trainee profile exists
    UserProfile.objects.update_or_create(
        user=user,
        defaults={
            "role": "Trainee",
            "trainee": trainee,
        }
    )

    notify(
        user,
        "Your trainee registration has been verified. You are now eligible for Authority-assigned training.",
        "Registration"
    )

    messages.success(
        request,
        "Trainee verified successfully."
    )

    return render(
        request,
        "trainees/account_created.html",
        {
            "trainee": trainee,
            "username": user.username,
            "password": None,
            "created": False,
        }
    )
@login_required
@authority_required
@require_POST
def reject_trainee(request, id):

    trainee = get_object_or_404(
        Trainee,
        id=id
    )

    trainee.status = "Rejected"

    trainee.save(
        update_fields=["status"]
    )

    if trainee.user_id:
        notify(trainee.user, "Your trainee registration was rejected. Please contact the Authority for assistance.", "Registration")

    messages.success(
        request,
        "Trainee rejected."
    )

    return redirect(
        "trainee_detail",
        id=id
    )


# ==========================================================
# TRAINERS
# ==========================================================

@login_required
@authority_required
def trainer_list(request):

    return render(
        request,
        "trainers/trainer_list.html",
        {
            "trainers":
                TrainerRegistration.objects
                .all()
                .order_by("-id")
        }
    )


@login_required
@authority_required
def trainer_detail(request, id):

    trainer = get_object_or_404(
        TrainerRegistration,
        id=id
    )

    return render(
        request,
        "trainers/trainer_detail.html",
        {
            "trainer": trainer
        }
    )


@login_required
@authority_required
@require_POST
def verify_trainer(request, id):

    trainer = get_object_or_404(
        TrainerRegistration,
        id=id
    )

    user = trainer.user

    if not user:
        messages.error(
            request,
            "This trainer registration is not linked to a user account."
        )
        return redirect("trainer_detail", id=id)

    trainer.status = "Verified"
    trainer.save(update_fields=["status"])

    UserProfile.objects.update_or_create(
        user=user,
        defaults={
            "role": "Trainer",
            "trainee": None,
        }
    )

    notify(
        user,
        "Your trainer registration has been approved. "
        "You can now access your assigned batches.",
        "Registration"
    )

    messages.success(
        request,
        "Trainer verified successfully."
    )

    return redirect("trainer_detail", id=id)
@login_required
@authority_required
@require_POST
def reject_trainer(request, id):

    trainer = get_object_or_404(
        TrainerRegistration,
        id=id
    )

    trainer.status = "Rejected"

    trainer.save(
        update_fields=["status"]
    )

    if trainer.user_id:
        notify(trainer.user, "Your trainer registration was rejected. Please contact the Authority for assistance.", "Registration")

    messages.success(
        request,
        "Trainer rejected."
    )

    return redirect(
        "trainer_detail",
        id=id
    )


# ==========================================================
# PROVIDERS
# ==========================================================

@login_required
@authority_required
def provider_list(request):

    return render(
        request,
        "providers/provider_list.html",
        {
            "providers":
                Provider.objects
                .all()
                .order_by("-id")
        }
    )


@login_required
@authority_required
def provider_detail(request, id):

    provider = get_object_or_404(
        Provider,
        id=id
    )

    return render(
        request,
        "providers/provider_detail.html",
        {
            "provider": provider
        }
    )


@login_required
@authority_required
@require_POST
def verify_provider(request, id):

    provider = get_object_or_404(
        Provider,
        id=id
    )

    provider.status = "Verified"

    provider.save(
        update_fields=["status"]
    )

    messages.success(
        request,
        "Provider verified successfully."
    )

    return redirect(
        "provider_detail",
        id=id
    )


@login_required
@authority_required
@require_POST
def reject_provider(request, id):

    provider = get_object_or_404(
        Provider,
        id=id
    )

    provider.status = "Rejected"

    provider.save(
        update_fields=["status"]
    )

    messages.success(
        request,
        "Provider rejected."
    )

    return redirect(
        "provider_detail",
        id=id
    )


# ==========================================================
# COURSES
# ==========================================================

@login_required
@authority_required
def course_list(request):

    return render(
        request,
        "course/course_list.html",
        {
            "courses":
                Course.objects
                .all()
                .order_by("name")
        }
    )


@login_required
@authority_required
def course_create(request):

    form = CourseForm(
        request.POST or None
    )

    if request.method == "POST" and form.is_valid():

        form.save()

        messages.success(
            request,
            "Course created successfully."
        )

        return redirect(
            "course_list"
        )

    return render(
        request,
        "course/course_form.html",
        {
            "form": form
        }
    )


# ==========================================================
# BATCHES
# ==========================================================

@login_required
@authority_required
def batch_list(request):

    batches = (
        TrainingBatch.objects
        .select_related(
            "course",
            "provider",
            "trainer"
        )
        .all()
        .order_by("-id")
    )

    return render(
        request,
        "training/batch_list.html",
        {
            "batches": batches
        }
    )


@login_required
@authority_required
def batch_create(request):

    form = TrainingBatchForm(
        request.POST or None
    )

    if request.method == "POST" and form.is_valid():

        form.save()

        messages.success(
            request,
            "Training batch created successfully."
        )

        return redirect(
            "batch_list"
        )

    return render(
        request,
        "training/batch_form.html",
        {
            "form": form
        }
    )


@login_required
@authority_required
def batch_assign_trainees(request, id):

    batch = get_object_or_404(
        TrainingBatch,
        id=id
    )

    verified_trainees = (
        Trainee.objects
        .filter(status="Verified")
        .order_by("name")
    )

    if batch.status == "Completed":
        messages.error(request, "Completed batches cannot be changed.")
        return redirect("batch_list")

    if request.method == "POST":

        selected = list(
            Trainee.objects
            .filter(
                id__in=request.POST.getlist(
                    "trainees"
                ),
                status="Verified",
            )
        )

        if len(selected) > batch.capacity:

            messages.error(
                request,
                (
                    f"This batch has capacity for "
                    f"{batch.capacity} trainees; "
                    f"select fewer trainees."
                )
            )

        else:

            previous_ids = set(batch.trainees.values_list("id", flat=True))
            batch.trainees.set(selected)

            for trainee in selected:
                if trainee.id not in previous_ids and trainee.user_id:
                    notify(
                        trainee.user,
                        f"You have been assigned by the Authority to the {batch.name} training batch.",
                        "Training Assignment",
                    )

            messages.success(
                request,
                "Trainees assigned successfully."
            )

            return redirect(
                "batch_list"
            )

    return render(
        request,
        "training/assign_trainees.html",
        {
            "batch": batch,
            "verified_trainees":
                verified_trainees,
        }
    )


# ==========================================================
# TRAINER DASHBOARD
# ==========================================================

@login_required
@trainer_required
def trainer_dashboard(request):

    batches = (
        TrainingBatch.objects
        .filter(
            trainer=request.user
        )
        .select_related(
            "course",
            "provider"
        )
        .order_by("-start_date")
    )

    return render(
        request,
        "trainer_dashboard.html",
        {
            "batches": batches
        }
    )


@login_required
@trainer_required
def trainer_batch_detail(request, id):

    batch = get_object_or_404(
        TrainingBatch.objects
        .select_related(
            "course",
            "provider"
        ),
        id=id,
        trainer=request.user,
    )

    trainees = (
        batch.trainees
        .all()
        .order_by("name")
    )

    return render(
        request,
        "trainers/trainer_batch_detail.html",
        {
            "batch": batch,
            "trainees": trainees,
        }
    )



@login_required
@trainer_required
def trainer_batch_progress(request, id):

    batch = get_object_or_404(
        TrainingBatch,
        id=id,
        trainer=request.user
    )

    trainees = (
        batch.trainees
        .all()
        .order_by("name")
    )

    if request.method == "POST":

        attendance = batch.attendance or {}
        progress = batch.progress or {}
        remarks = batch.remarks or {}

        for trainee in trainees:

            trainee_id = str(trainee.id)

            # =========================================
            # ATTENDANCE STATUS
            # =========================================

            attendance[trainee_id] = request.POST.get(
                f"attendance_{trainee.id}",
                "Absent"
            )

            # =========================================
            # TRAINING PROGRESS
            # =========================================

            progress[trainee_id] = max(
                0,
                min(
                    100,
                    int(
                        request.POST.get(
                            f"progress_{trainee.id}",
                            0
                        ) or 0
                    )
                )
            )

            # =========================================
            # GENERAL REMARKS
            # =========================================

            remarks[trainee_id] = request.POST.get(
                f"remarks_{trainee.id}",
                ""
            )

            # =========================================
            # TRAINING
            # =========================================

            training, _ = Training.objects.get_or_create(
                trainee=trainee,
                course=batch.course,
                provider=batch.provider,
                defaults={
                    "start_date": batch.start_date,
                    "end_date": batch.end_date,
                    "completion_percentage": progress[trainee_id],
                    "status": "Training",
                    "batch": batch,
                    "trainer": request.user,
                }
            )

            training.completion_percentage = progress[trainee_id]
            training.batch = batch
            training.trainer = request.user

            training.save(
                update_fields=[
                    "completion_percentage",
                    "batch",
                    "trainer",
                ]
            )

            # =========================================
            # TRAINING PERFORMANCE
            # =========================================

            performance, _ = TrainingPerformance.objects.get_or_create(
                trainee=trainee,
                training=training,
            )

            # =========================================
            # ATTENDANCE
            # =========================================

            performance.total_classes = int(
                request.POST.get(
                    f"total_classes_{trainee.id}",
                    performance.total_classes
                ) or 0
            )

            performance.attended_classes = int(
                request.POST.get(
                    f"attended_classes_{trainee.id}",
                    performance.attended_classes
                ) or 0
            )

            # Prevent attended classes from being greater
            # than total classes

            if performance.attended_classes > performance.total_classes:
                performance.attended_classes = (
                    performance.total_classes
                )

            if performance.total_classes > 0:

                performance.attendance_percentage = round(
                    (
                        performance.attended_classes
                        / performance.total_classes
                    ) * 100,
                    2
                )

            else:

                performance.attendance_percentage = 0


            # =========================================
            # ASSIGNMENTS
            # =========================================

            performance.total_assignments = int(
                request.POST.get(
                    f"total_assignments_{trainee.id}",
                    performance.total_assignments
                ) or 0
            )

            performance.completed_assignments = int(
                request.POST.get(
                    f"completed_assignments_{trainee.id}",
                    performance.completed_assignments
                ) or 0
            )

            # Prevent completed assignments from being
            # greater than total assignments

            if (
                performance.completed_assignments
                > performance.total_assignments
            ):
                performance.completed_assignments = (
                    performance.total_assignments
                )

            # Automatically calculate assignment percentage

            if performance.total_assignments > 0:

                performance.assignment_score = round(
                    (
                        performance.completed_assignments
                        / performance.total_assignments
                    ) * 100,
                    2
                )

            else:

                performance.assignment_score = 0


            # =========================================
            # ASSESSMENTS
            # =========================================

            performance.total_assessments = int(
                request.POST.get(
                    f"total_assessments_{trainee.id}",
                    performance.total_assessments
                ) or 0
            )

            performance.completed_assessments = int(
                request.POST.get(
                    f"completed_assessments_{trainee.id}",
                    performance.completed_assessments
                ) or 0
            )

            # Prevent completed assessments from being
            # greater than total assessments

            if (
                performance.completed_assessments
                > performance.total_assessments
            ):
                performance.completed_assessments = (
                    performance.total_assessments
                )

            # Automatically calculate assessment percentage

            if performance.total_assessments > 0:

                performance.assessment_score = round(
                    (
                        performance.completed_assessments
                        / performance.total_assessments
                    ) * 100,
                    2
                )

            else:

                performance.assessment_score = 0


            # =========================================
            # PRACTICAL SCORE
            # =========================================

            performance.practical_score = float(
                request.POST.get(
                    f"practical_score_{trainee.id}",
                    performance.practical_score
                ) or 0
            )

            performance.practical_score = max(
                0,
                min(
                    100,
                    performance.practical_score
                )
            )


            # =========================================
            # PROGRESS
            # =========================================

            performance.progress_percentage = float(
                progress[trainee_id]
            )


            # =========================================
            # FINAL SCORE
            # =========================================

            performance.final_score = float(
                request.POST.get(
                    f"final_score_{trainee.id}",
                    performance.final_score
                ) or 0
            )

            performance.final_score = max(
                0,
                min(
                    100,
                    performance.final_score
                )
            )


            # =========================================
            # PERFORMANCE REMARKS
            # =========================================

            performance.trainer_remarks = request.POST.get(
                f"performance_remarks_{trainee.id}",
                remarks[trainee_id]
            )



            performance.save()




        batch.attendance = attendance
        batch.progress = progress
        batch.remarks = remarks

        batch.save(
            update_fields=[
                "attendance",
                "progress",
                "remarks",
            ]
        )

        messages.success(
            request,
            (
                "Attendance, progress and "
                "training performance saved successfully."
            )
        )

        return redirect(
            "trainer_batch_detail",
            id=id
        )


    # =========================================
    # GET REQUEST
    # =========================================

    return render(
        request,
        "training/trainer_batch_progress.html",
        {
            "batch": batch,
            "trainees": trainees,
        }
    )



# ==========================================================
# COMPLETE BATCH
# ==========================================================

@login_required
@trainer_required
@require_POST
def trainer_complete_batch(request, id):

    batch = get_object_or_404(
        TrainingBatch,
        id=id,
        trainer=request.user
    )

    if batch.status != "Completed":
        assigned_trainees = list(batch.trainees.all())
        records = {
            record.trainee_id: record
            for record in Training.objects.filter(batch=batch)
        }
        incomplete = [
            trainee for trainee in assigned_trainees
            if trainee.id not in records or records[trainee.id].completion_percentage < 100
        ]
        if not assigned_trainees or incomplete:
            messages.error(
                request,
                "A batch can be completed only after every assigned trainee has a training record at 100% progress.",
            )
            return redirect("trainer_batch_detail", id=id)

        batch.status = "Completed"
        batch.completion_date = date.today()

        batch.save(
            update_fields=[
                "status",
                "completion_date",
            ]
        )

        Training.objects.filter(
            batch=batch
        ).update(
            status="Completed",
            end_date=batch.completion_date,
        )

        generate_followups(batch)

        for trainee in batch.trainees.all():

            profile = (
                UserProfile.objects
                .filter(
                    trainee=trainee,
                    role="Trainee"
                )
                .select_related("user")
                .first()
            )

            if profile:

                notify(
                    profile.user,
                    (
                        f"Your training batch "
                        f"{batch.name} has been completed."
                    ),
                    "Training",
                )

        messages.success(
            request,
            (
                "Training marked as completed "
                "and follow-ups generated."
            )
        )

    return redirect(
        "trainer_batch_detail",
        id=id
    )


# ==========================================================
# TRAINEE DASHBOARD
# ==========================================================

@login_required
@trainee_required
def trainee_dashboard(request):

    trainee = (
        request.user
        .userprofile
        .trainee
    )

    batches = (
        TrainingBatch.objects
        .filter(
            trainees=trainee
        )
        .select_related(
            "course",
            "provider",
            "trainer"
        )
        .order_by("-start_date")
    )

    performance_records = (
        TrainingPerformance.objects
        .filter(
            trainee=trainee
        )
        .select_related(
            "training",
            "training__course",
            "training__provider",
        )
        .order_by(
            "-training__start_date"
        )
    )

    # ======================================================
    # PERFORMANCE
    # ======================================================

    latest_performance = (
        performance_records
        .first()
    )

    if latest_performance:

        attendance_percentage = (
            latest_performance.attendance_percentage or 0
        )

        assignment_percentage = (
            latest_performance.assignment_score or 0
        )

        assessment_percentage = (
            latest_performance.assessment_score or 0
        )

        overall_progress = (
            latest_performance.progress_percentage or 0
        )

        trainer_remarks = (
            latest_performance.trainer_remarks or ""
        )

    else:

        attendance_percentage = 0
        assignment_percentage = 0
        assessment_percentage = 0
        overall_progress = 0
        trainer_remarks = ""

    # ======================================================
    # EMPLOYMENT
    # ======================================================

    employment = (
        Employment.objects
        .filter(
            trainee=trainee
        )
        .order_by(
            "-recorded_on",
            "-id"
        )
        .first()
    )

    # ======================================================
    # FOLLOW UPS
    # ======================================================

    followups = (
        FollowUp.objects
        .filter(
            trainee=trainee,
            completed=False
        )
        .order_by("date")[:4]
    )

    return render(
        request,
        "trainees/trainee_dashboard.html",
        {
            "trainee": trainee,

            "batches": batches,

            "performance_records":
                performance_records,

            # Performance values for dashboard
            "attendance_percentage":
                attendance_percentage,

            "assignment_percentage":
                assignment_percentage,

            "assessment_percentage":
                assessment_percentage,

            "overall_progress":
                overall_progress,

            "trainer_remarks":
                trainer_remarks,

            "employment":
                employment,

            "followups":
                followups,
        }
    )


# ==========================================================
# TRAINEE TRAINING REQUEST
# ==========================================================

@login_required
@trainee_required
def trainee_training_request(
    request,
    batch_id
):

    trainee = (
        request.user
        .userprofile
        .trainee
    )

    batch = get_object_or_404(
        TrainingBatch.objects
        .select_related(
            "course",
            "provider",
            "trainer"
        ),
        id=batch_id,
        status="Active",
    )

    if trainee.status != "Verified":

        messages.error(
            request,
            (
                "Your beneficiary profile must "
                "be verified by the Authority first."
            )
        )

        return redirect(
            "trainee_dashboard"
        )

    if batch.trainees.filter(
        id=trainee.id
    ).exists():

        messages.info(
            request,
            "You are already enrolled in this batch."
        )

        return redirect(
            "trainee_dashboard"
        )

    registration_request = (
        TrainingRegistrationRequest.objects
        .filter(
            trainee=trainee,
            batch=batch
        )
        .first()
    )

    if registration_request:

        if registration_request.status == "Pending":

            messages.info(
                request,
                "Your registration request is already pending."
            )

        elif registration_request.status == "Verified":

            messages.info(
                request,
                "Your request has already been verified."
            )

        else:

            messages.info(
                request,
                "Your previous request was rejected."
            )

        return redirect(
            "trainee_dashboard"
        )

    if batch.trainees.count() >= batch.capacity:

        messages.error(
            request,
            "This training batch is already full."
        )

        return redirect(
            "trainee_dashboard"
        )

    if request.method == "POST":

        registration_request = (
            TrainingRegistrationRequest.objects
            .create(
                trainee=trainee,
                batch=batch,
                status="Pending",
            )
        )

        if batch.trainer:

            notify(
                batch.trainer,
                (
                    f"New trainee registration request: "
                    f"{trainee.name} "
                    f"({trainee.beneficiary_id}) "
                    f"requested to join {batch.name}."
                ),
                "Training Registration",
            )

        messages.success(
            request,
            (
                "Training registration request "
                "submitted successfully."
            )
        )

        return redirect(
            "trainee_dashboard"
        )

    return render(
        request,
        "trainees/training_request.html",
        {
            "trainee": trainee,
            "batch": batch,
        }
    )


# ==========================================================
# TRAINER VERIFY TRAINEES
# ==========================================================

@login_required
@trainer_required
def trainer_verify_trainees(request):

    registration_requests = (
        TrainingRegistrationRequest.objects
        .filter(
            batch__trainer=request.user
        )
        .select_related(
            "trainee",
            "batch",
            "batch__course",
            "batch__provider",
        )
        .order_by("-requested_at")
    )

    pending_count = (
        registration_requests
        .filter(status="Pending")
        .count()
    )

    return render(
        request,
        "trainers/verify_trainees.html",
        {
            "registration_requests":
                registration_requests,
            "pending_count":
                pending_count,
        }
    )


@login_required
@trainer_required
@require_POST
def trainer_verify_request(
    request,
    request_id
):

    registration_request = get_object_or_404(
        TrainingRegistrationRequest.objects
        .select_related(
            "trainee",
            "batch",
            "batch__course",
        ),
        id=request_id,
        batch__trainer=request.user,
    )

    if registration_request.status != "Pending":

        messages.warning(
            request,
            "This registration request has already been reviewed."
        )

        return redirect(
            "trainer_verify_trainees"
        )

    batch = registration_request.batch
    trainee = registration_request.trainee

    if batch.trainees.count() >= batch.capacity:

        messages.error(
            request,
            "This batch is already full. The trainee cannot be added."
        )

        return redirect(
            "trainer_verify_trainees"
        )

    batch.trainees.add(trainee)

    registration_request.status = "Verified"
    registration_request.reviewed_at = date.today()
    registration_request.rejection_reason = ""

    registration_request.save(
        update_fields=[
            "status",
            "reviewed_at",
            "rejection_reason",
        ]
    )

    profile = (
        UserProfile.objects
        .filter(
            trainee=trainee,
            role="Trainee"
        )
        .select_related("user")
        .first()
    )

    if profile:

        notify(
            profile.user,
            (
                f"Your registration request for "
                f"{batch.name} has been verified "
                f"by the trainer."
            ),
            "Training Registration",
        )

    messages.success(
        request,
        (
            f"{trainee.name} has been verified "
            f"and added to {batch.name}."
        )
    )

    return redirect(
        "trainer_verify_trainees"
    )


@login_required
@trainer_required
@require_POST
def trainer_reject_request(
    request,
    request_id
):

    registration_request = get_object_or_404(
        TrainingRegistrationRequest.objects
        .select_related(
            "trainee",
            "batch",
        ),
        id=request_id,
        batch__trainer=request.user,
    )

    if registration_request.status != "Pending":

        messages.warning(
            request,
            "This registration request has already been reviewed."
        )

        return redirect(
            "trainer_verify_trainees"
        )

    trainee = registration_request.trainee
    batch = registration_request.batch

    reason = request.POST.get(
        "rejection_reason",
        ""
    ).strip()

    registration_request.status = "Rejected"
    registration_request.rejection_reason = reason
    registration_request.reviewed_at = date.today()

    registration_request.save(
        update_fields=[
            "status",
            "rejection_reason",
            "reviewed_at",
        ]
    )

    profile = (
        UserProfile.objects
        .filter(
            trainee=trainee,
            role="Trainee"
        )
        .select_related("user")
        .first()
    )

    if profile:

        message = (
            f"Your registration request for "
            f"{batch.name} has been rejected "
            f"by the trainer."
        )

        if reason:
            message += (
                f" Reason: {reason}"
            )

        notify(
            profile.user,
            message,
            "Training Registration",
        )

    messages.success(
        request,
        (
            f"Registration request for "
            f"{trainee.name} rejected."
        )
    )

    return redirect(
        "trainer_verify_trainees"
    )


# ==========================================================
# TRAINER ATTENDANCE
# ==========================================================

@login_required
@trainer_required
def trainer_attendance(request):

    batches = (
        TrainingBatch.objects
        .filter(
            trainer=request.user
        )
        .select_related(
            "course",
            "provider"
        )
        .order_by("-start_date")
    )

    selected_batch = None
    trainees = []

    batch_id = request.GET.get(
        "batch"
    )

    if batch_id:

        selected_batch = get_object_or_404(
            TrainingBatch.objects
            .select_related(
                "course",
                "provider"
            ),
            id=batch_id,
            trainer=request.user,
        )

        trainees = list(
            selected_batch.trainees
            .all()
            .order_by("name")
        )

        attendance_data = (
            selected_batch.attendance
            or {}
        )

        for trainee in trainees:

            trainee.attendance_status = (
                attendance_data.get(
                    str(trainee.id),
                    "Absent"
                )
            )

    if request.method == "POST":

        batch_id = request.POST.get(
            "batch_id"
        )

        selected_batch = get_object_or_404(
            TrainingBatch,
            id=batch_id,
            trainer=request.user,
        )

        trainees = list(
            selected_batch.trainees
            .all()
            .order_by("name")
        )

        attendance = {}

        for trainee in trainees:

            attendance[
                str(trainee.id)
            ] = request.POST.get(
                f"attendance_{trainee.id}",
                "Absent"
            )

        selected_batch.attendance = attendance

        selected_batch.save(
            update_fields=["attendance"]
        )

        messages.success(
            request,
            "Attendance updated successfully."
        )

        return redirect(
            f"{request.path}?batch={selected_batch.id}"
        )

    return render(
        request,
        "training/trainer_attendance.html",
        {
            "batches": batches,
            "selected_batch": selected_batch,
            "trainees": trainees,
        }
    )


# ==========================================================
# EMPLOYMENT
# ==========================================================
@login_required
def employment_list(request):

    profile = getattr(
        request.user,
        "userprofile",
        None
    )

    # ======================================================
    # AUTHORITY
    # ======================================================

    if (
        request.user.is_staff
        or getattr(profile, "role", None) == "Authority"
    ):

        qs = (
            Employment.objects
            .select_related(
                "trainee",
                "training"
            )
            .order_by(
                "-recorded_on",
                "-id"
            )
        )

        status = request.GET.get("status", "").strip()
        district = request.GET.get("district", "").strip()

        if status:
            qs = qs.filter(status=status)

        if district:
            qs = qs.filter(
                trainee__district=district
            )

        districts = (
            Trainee.objects
            .exclude(district__isnull=True)
            .exclude(district="")
            .values_list(
                "district",
                flat=True
            )
            .distinct()
            .order_by("district")
        )

        return render(
            request,
            "employment/list.html",
            {
                "employments": qs,
                "authority": True,
                "statuses": Employment.STATUS_CHOICES,
                "districts": districts,
            }
        )

    # ======================================================
    # TRAINEE
    # ======================================================

    if (
        not profile
        or profile.role != "Trainee"
    ):
        return redirect("login")

    trainee = profile.trainee

    # ======================================================
    # EDIT EXISTING OUTCOME
    # ======================================================

    edit_id = request.GET.get("edit")

    editing_employment = None

    if edit_id:

        editing_employment = get_object_or_404(
            Employment,
            id=edit_id,
            trainee=trainee,
        )

    # ======================================================
    # POST
    # ======================================================

    if request.method == "POST":

        edit_id = request.POST.get("edit_id")

        # ==================================================
        # UPDATE
        # ==================================================

        if edit_id:

            editing_employment = get_object_or_404(
                Employment,
                id=edit_id,
                trainee=trainee,
            )

            form = EmploymentForm(
                request.POST,
                request.FILES,
                instance=editing_employment,
            )

            if form.is_valid():

                outcome = form.save(commit=False)

                outcome.trainee = trainee
                outcome.save()

                # ------------------------------------------
                # UPDATE WAGE RECORD
                # ------------------------------------------

                if outcome.salary:

                    wage_record, created = (
                        WageRecord.objects
                        .get_or_create(
                            employment=outcome,
                            defaults={
                                "trainee": trainee,
                                "amount": outcome.salary,
                                "frequency": (
                                    outcome.wage_frequency
                                ),
                                "recorded_on": (
                                    outcome.employment_date
                                    or date.today()
                                ),
                            }
                        )
                    )

                    if not created:

                        wage_record.trainee = trainee
                        wage_record.amount = outcome.salary
                        wage_record.frequency = (
                            outcome.wage_frequency
                        )
                        wage_record.recorded_on = (
                            outcome.employment_date
                            or date.today()
                        )

                        wage_record.save()

                messages.success(
                    request,
                    "Employment outcome updated successfully."
                )

                return redirect("employment_list")

        # ==================================================
        # CREATE NEW OUTCOME
        # ==================================================

        else:

            form = EmploymentForm(
                request.POST,
                request.FILES,
            )

            if form.is_valid():

                outcome = form.save(commit=False)

                outcome.trainee = trainee
                outcome.save()

                # ------------------------------------------
                # CREATE WAGE RECORD
                # ------------------------------------------

                if outcome.salary:

                    WageRecord.objects.create(
                        trainee=trainee,
                        employment=outcome,
                        amount=outcome.salary,
                        frequency=(
                            outcome.wage_frequency
                        ),
                        recorded_on=(
                            outcome.employment_date
                            or date.today()
                        ),
                    )

                messages.success(
                    request,
                    "Outcome recorded successfully."
                )

                return redirect("employment_list")

    # ======================================================
    # GET
    # ======================================================

    else:

        if editing_employment:

            form = EmploymentForm(
                instance=editing_employment
            )

        else:

            latest = _latest_outcome(trainee)

            form = EmploymentForm(
                initial={
                    "status": (
                        latest.status
                        if latest
                        else "Seeking"
                    )
                }
            )

    # ======================================================
    # TRAINEE OUTCOME HISTORY
    # ======================================================

    outcomes = (
        trainee.employment_records
        .all()
        .order_by(
            "-recorded_on",
            "-id"
        )
    )

    return render(
        request,
        "employment/form.html",
        {
            "form": form,
            "employment": editing_employment,
            "editing": bool(editing_employment),
            "outcomes": outcomes,
        }
    )

# ==========================================================
# EMPLOYMENT OUTCOME DETAIL
# ==========================================================

@login_required
@authority_required
def employment_detail(request, id):

    outcome = get_object_or_404(
        Employment.objects.select_related(
            "trainee",
            "training",
        ),
        id=id,
    )

    return render(
        request,
        "employment/detail.html",
        {
            "outcome": outcome,
        }
    )
@login_required
@authority_required
@require_POST
def verify_employment(request, id):

    outcome = get_object_or_404(
        Employment,
        id=id
    )

    decision = request.POST.get(
        "decision",
        "Verified"
    )

    if decision not in {
        "Verified",
        "Rejected",
        "Pending",
    }:
        decision = "Verified"

    outcome.verification_status = decision

    outcome.save(
        update_fields=[
            "verification_status"
        ]
    )

    messages.success(
        request,
        (
            f"Outcome marked "
            f"{outcome.verification_status.lower()} "
            f"by Authority."
        )
    )


    return redirect("employment_list")

# ==========================================================
# UAN VERIFICATION
# ==========================================================

@login_required
def verify_uan(request):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "message": "Invalid request.",
            },
            status=400
        )

    profile = getattr(
        request.user,
        "userprofile",
        None
    )

    if (
        not profile
        or profile.role != "Trainee"
    ):

        return JsonResponse(
            {
                "success": False,
                "message": "Unauthorized.",
            },
            status=403
        )

    uan = request.POST.get(
        "uan",
        ""
    ).strip()

    if not uan:

        return JsonResponse(
            {
                "success": False,
                "message": "Please enter UAN.",
            }
        )

    employment_id = request.POST.get("employment_id")
    employment = (
        get_object_or_404(Employment, id=employment_id, trainee=profile.trainee)
        if employment_id else None
    )

    demo_data = {

        "100000000001": {
            "employer_name":
                "ABC Technologies Pvt Ltd",
            "job_role":
                "Software Developer",
            "employment_type":
                "Full Time",
            "salary":
                25000,
            "employment_date":
                "2026-07-01",
        },

        "100000000002": {
            "employer_name":
                "Maharashtra IT Solutions",
            "job_role":
                "Python Developer",
            "employment_type":
                "Full Time",
            "salary":
                32000,
            "employment_date":
                "2026-06-15",
        },

        "100000000003": {
            "employer_name":
                "Pune Digital Services",
            "job_role":
                "Data Entry Operator",
            "employment_type":
                "Full Time",
            "salary":
                22000,
            "employment_date":
                "2026-05-20",
        },

        "100000000004": {
            "employer_name":
                "TechVision Solutions",
            "job_role":
                "Web Developer",
            "employment_type":
                "Full Time",
            "salary":
                35000,
            "employment_date":
                "2026-04-10",
        },

        "100000000005": {
            "employer_name":
                "Nashik Engineering Works",
            "job_role":
                "Technician",
            "employment_type":
                "Full Time",
            "salary":
                28000,
            "employment_date":
                "2026-03-12",
        },

        "100000000006": {
            "employer_name":
                "Mumbai Business Solutions",
            "job_role":
                "Support Executive",
            "employment_type":
                "Full Time",
            "salary":
                24000,
            "employment_date":
                "2026-02-18",
        },

        "100000000007": {
            "employer_name":
                "Nagpur Software Labs",
            "job_role":
                "Junior Software Engineer",
            "employment_type":
                "Full Time",
            "salary":
                30000,
            "employment_date":
                "2026-01-25",
        },

        "100000000008": {
            "employer_name":
                "Kolhapur Auto Industries",
            "job_role":
                "Machine Operator",
            "employment_type":
                "Full Time",
            "salary":
                27000,
            "employment_date":
                "2025-12-15",
        },

        "100000000009": {
            "employer_name":
                "Thane Digital Hub",
            "job_role":
                "Digital Marketing Executive",
            "employment_type":
                "Full Time",
            "salary":
                26000,
            "employment_date":
                "2025-11-20",
        },

        "100000000010": {
            "employer_name":
                "Solapur Technology Services",
            "job_role":
                "Technical Support Engineer",
            "employment_type":
                "Full Time",
            "salary":
                29000,
            "employment_date":
                "2025-10-10",
        },

        "100000000011": {
            "employer_name":
                "Aurangabad Tech Solutions",
            "job_role":
                "Software Tester",
            "employment_type":
                "Full Time",
            "salary":
                31000,
            "employment_date":
                "2025-09-15",
        },
    }

    if uan in demo_data:

        data = demo_data[uan]
        if employment is None:
            employment = Employment.objects.create(
                trainee=profile.trainee, status="Employed",
                verification_method="UAN", verification_status="Verified",
                uan_demo=uan, uan_verified_on=timezone.now(), **data,
            )
        else:
            for field, value in data.items():
                setattr(employment, field, value)
            employment.status = "Employed"
            employment.verification_method = "UAN"
            employment.verification_status = "Verified"
            employment.uan_demo = uan
            employment.uan_verified_on = timezone.now()
            employment.save()

        UANVerification.objects.update_or_create(
            employment=employment,
            defaults={
                "uan": uan,
                "verified": True,
                "verification_message":
                    "UAN verified successfully.",
                "verified_at":
                    timezone.now(),
            }
        )

        return JsonResponse(
            {
                "success": True,
                "message":
                    "✓ UAN Verified — "
                    "Employment record found.",
                "uan": uan,
                "employment_id": employment.id,
                **data,
            }
        )

    if employment is None:
        employment = Employment.objects.create(trainee=profile.trainee, status="Seeking")

    UANVerification.objects.update_or_create(
        employment=employment,
        defaults={
            "uan": uan,
            "verified": False,
            "verification_message":
                "UAN verification failed.",
            "verified_at":
                timezone.now(),
        }
    )

    return JsonResponse(
        {
            "success": False,
            "message":
                "✗ UAN Verification Failed.",
        }
    )


# ==========================================================
# SELF-EMPLOYMENT REGISTRATION VERIFICATION
# ==========================================================

@login_required
def verify_registration(request):

    if request.method != "POST":

        return JsonResponse(
            {
                "success": False,
                "message": "Invalid request.",
            },
            status=400
        )

    profile = getattr(
        request.user,
        "userprofile",
        None
    )

    if (
        not profile
        or profile.role != "Trainee"
    ):

        return JsonResponse(
            {
                "success": False,
                "message": "Unauthorized.",
            },
            status=403
        )

    registration_number = request.POST.get(
        "registration_number",
        ""
    ).strip()

    if not registration_number:

        return JsonResponse(
            {
                "success": False,
                "message":
                    "Please enter registration number.",
            }
        )

    employment, _ = (
        Employment.objects
        .get_or_create(
            trainee=profile.trainee,
            defaults={
                "status": "Seeking"
            }
        )
    )

    demo_self_employment = {

        "MH-DEMO-1001": {
            "business_name":
                "ABC Enterprises",
            "business_type":
                "Proprietorship",
            "work_description":
                "Retail Business",
        },

        "MH-DEMO-1002": {
            "business_name":
                "Pune Digital Services",
            "business_type":
                "Proprietorship",
            "work_description":
                "Computer and Digital Services",
        },

        "MH-DEMO-1003": {
            "business_name":
                "Maharashtra Tailoring House",
            "business_type":
                "Proprietorship",
            "work_description":
                "Tailoring and Garment Services",
        },

        "MH-DEMO-1004": {
            "business_name":
                "Shree Auto Works",
            "business_type":
                "Partnership",
            "work_description":
                "Automobile Repair Services",
        },

        "MH-DEMO-1005": {
            "business_name":
                "Green Solar Solutions",
            "business_type":
                "Proprietorship",
            "work_description":
                "Solar Panel Installation",
        },

        "MH-DEMO-1006": {
            "business_name":
                "Smart Graphic Studio",
            "business_type":
                "Proprietorship",
            "work_description":
                "Graphic Design and Printing",
        },

        "MH-DEMO-1007": {
            "business_name":
                "Maharashtra Mobile Care",
            "business_type":
                "Partnership",
            "work_description":
                "Mobile Repair Services",
        },

        "MH-DEMO-1008": {
            "business_name":
                "Fresh Food Corner",
            "business_type":
                "Proprietorship",
            "work_description":
                "Food and Catering Services",
        },
    }

    if registration_number in demo_self_employment:

        data = demo_self_employment[
            registration_number
        ]

        SelfEmploymentVerification.objects.update_or_create(
            employment=employment,
            defaults={
                "registration_number":
                    registration_number,
                "business_name":
                    data["business_name"],
                "business_type":
                    data["business_type"],
                "work_description":
                    data["work_description"],
                "status":
                    "Verified",
                "verification_message":
                    "Registration verified successfully.",
                "verified_at":
                    timezone.now(),
            }
        )

        return JsonResponse(
            {
                "success": True,
                "message":
                    "✓ Registration Verified — "
                    "Business record found.",
                "registration_number":
                    registration_number,
                **data,
            }
        )

    SelfEmploymentVerification.objects.update_or_create(
        employment=employment,
        defaults={
            "registration_number":
                registration_number,
            "business_name":
                "",
            "business_type":
                "",
            "work_description":
                "",
            "status":
                "Rejected",
            "verification_message":
                "Registration verification failed.",
            "verified_at":
                timezone.now(),
        }
    )

    return JsonResponse(
        {
            "success": False,
            "message":
                "✗ Registration Verification Failed.",
        }
    )


# ==========================================================
# FOLLOW-UPS
# ==========================================================

@login_required
def followup_list(request):

    profile = getattr(
        request.user,
        "userprofile",
        None
    )

    if (
        request.user.is_staff
        or getattr(
            profile,
            "role",
            None
        ) == "Authority"
    ):

        followups = (
            FollowUp.objects
            .select_related("trainee")
            .all()
        )

        return render(
            request,
            "followups/list.html",
            {
                "followups":
                    followups,
                "today":
                    date.today(),
                "authority":
                    True,
            }
        )

    if (
        not profile
        or profile.role != "Trainee"
    ):
        return redirect("login")

    return render(
        request,
        "followups/list.html",
        {
            "followups":
                FollowUp.objects
                .filter(
                    trainee=profile.trainee
                ),
            "today":
                date.today(),
        }
    )


@login_required
@authority_required
def followup_update(request, id):

    followup = get_object_or_404(
        FollowUp,
        id=id
    )

    form = FollowUpForm(
        request.POST or None,
        instance=followup
    )

    if request.method == "POST" and form.is_valid():

        followup = form.save()

        if followup.completed:

            Employment.objects.create(
                trainee=followup.trainee,
                status=followup.employment_status,
                outcome_notes=(
                    f"Recorded during "
                    f"{followup.followup_type} follow-up"
                ),
            )

        messages.success(
            request,
            (
                "Follow-up saved; its outcome "
                "was added to the longitudinal history."
            )
        )

        return redirect(
            "followup_list"
        )

    return render(
        request,
        "followups/form.html",
        {
            "form": form,
            "followup": followup,
        }
    )


# ==========================================================
# NOTIFICATIONS
# ==========================================================

@login_required
def notification_list(request):

    notifications = (
        Notification.objects
        .filter(
            recipient=request.user
        )
    )

    notifications.filter(
        is_read=False
    ).update(
        is_read=True
    )

    return render(
        request,
        "notifications/list.html",
        {
            "notifications":
                notifications
        }
    )


# ==========================================================
# OUTCOME SUPPORT
# ==========================================================

@login_required
@authority_required
def outcome_support(request, id):

    trainee = get_object_or_404(
        Trainee,
        id=id
    )

    relevance_form = TrainingRelevanceForm(
        request.POST or None,
        prefix="relevance"
    )

    retention_form = RetentionRecordForm(
        request.POST or None,
        prefix="retention"
    )

    if request.method == "POST":

        if (
            "save_relevance" in request.POST
            and relevance_form.is_valid()
        ):

            record = relevance_form.save(
                commit=False
            )

            record.trainee = trainee

            record.training = (
                trainee.training_set
                .order_by("-end_date")
                .first()
            )

            record.save()

        elif (
            "save_retention" in request.POST
            and retention_form.is_valid()
        ):

            record = retention_form.save(
                commit=False
            )

            record.trainee = trainee
            record.employment = (
                _latest_outcome(trainee)
            )

            record.save()

        else:

            messages.error(
                request,
                "Please correct the highlighted fields."
            )

            return render(
                request,
                "trainees/outcome_support.html",
                {
                    "trainee": trainee,
                    "relevance_form":
                        relevance_form,
                    "retention_form":
                        retention_form,
                }
            )

        messages.success(
            request,
            "Longitudinal outcome evidence recorded."
        )

        return redirect(
            "trainee_detail",
            id=trainee.id
        )

    return render(
        request,
        "trainees/outcome_support.html",
        {
            "trainee": trainee,
            "relevance_form":
                relevance_form,
            "retention_form":
                retention_form,
        }
    )


# ==========================================================
# ANALYTICS
# ==========================================================

@login_required
@authority_required
def analytics(request):

    outcomes = (
        Employment.objects
        .select_related(
            "trainee",
            "training__course",
            "training__provider"
        )
    )

    district = request.GET.get(
        "district"
    )

    course = request.GET.get(
        "course"
    )

    if district:

        outcomes = outcomes.filter(
            trainee__district=district
        )

    if course:

        outcomes = outcomes.filter(
            training__course_id=course
        )

    completed = (
        Training.objects
        .filter(status="Completed")
    )

    retention_stats = RetentionRecord.objects.aggregate(
        retained=Count("id", filter=Q(still_employed=True)),
        total=Count("id"),
    )

    retained = retention_stats["retained"]
    retention_total = retention_stats["total"]

    placement = (
        outcomes
        .filter(status="Employed")
        .count()
    )

    wage_avg = (
        Employment.objects
        .filter(
            status="Employed",
            salary__isnull=False
        )
        .aggregate(
            avg=Avg("salary")
        )["avg"]
        or 0
    )

    common_gaps = (
        TrainingRelevance.objects
        .exclude(
            missing_skills=""
        )
        .values("missing_skills")
        .annotate(
            total=Count("id")
        )
        .order_by("-total")[:5]
    )

    return render(
        request,
        "analytics.html",
        {
            "course_data":
                list(
                    completed
                    .values(
                        "course__name"
                    )
                    .annotate(
                        total=Count("id")
                    )
                    .order_by(
                        "course__name"
                    )
                ),

            "provider_data":
                list(
                    completed
                    .values(
                        "provider__name"
                    )
                    .annotate(
                        total=Count("id")
                    )
                    .order_by(
                        "provider__name"
                    )
                ),

            "employment_data":
                list(
                    outcomes
                    .values("status")
                    .annotate(
                        total=Count("id")
                    )
                ),

            "district_data":
                list(
                    outcomes
                    .values(
                        "trainee__district"
                    )
                    .annotate(
                        total=Count("id")
                    )
                ),

            "placement":
                placement,

            "outcomes_total":
                outcomes.count(),

            "average_wage":
                round(wage_avg),

            "retention_rate":
                (
                    round(
                        retained
                        * 100
                        / retention_total
                    )
                    if retention_total
                    else 0
                ),

            "common_gaps":
                common_gaps,

            "districts":
                (
                    Trainee.objects
                    .values_list(
                        "district",
                        flat=True
                    )
                    .distinct()
                    .order_by("district")
                ),

            "courses":
                Course.objects
                .all()
                .order_by("name"),
        }
    )


# ==========================================================
# PUBLIC DASHBOARD
# ==========================================================

def public_dashboard(request):
    if request.user.is_authenticated:
        return redirect_for_user(request.user, request)



    trainees = Trainee.objects.all()

    providers = (
        Provider.objects
        .filter(status="Verified")
    )

    trainers = (
        TrainerRegistration.objects
        .filter(status="Verified")
    )

    courses = Course.objects.all()
    batches = TrainingBatch.objects.all()
    employments = Employment.objects.all()

    employment_stats = employments.aggregate(
        total=Count("id"),
        employed=Count("id", filter=Q(status="Employed")),
        seeking=Count("id", filter=Q(status="Seeking")),
        unemployed=Count("id", filter=Q(status="Unemployed")),
    )

    total_employment = employment_stats["total"]
    employed = employment_stats["employed"]

    trainee_stats = trainees.aggregate(
        total=Count("id"),
        verified=Count("id", filter=Q(status="Verified")),
    )

    batch_stats = batches.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status="Active")),
        completed=Count("id", filter=Q(status="Completed")),
    )

    context = {

        "total_trainees":
            trainee_stats["total"],

        "verified_trainees":
            trainee_stats["verified"],

        "total_providers":
            providers.count(),

        "total_trainers":
            trainers.count(),

        "total_courses":
            courses.count(),

        "total_batches":
            batch_stats["total"],

        "active_batches":
            batch_stats["active"],

        "completed_batches":
            batch_stats["completed"],

        "employed":
            employed,

        "seeking":
            employment_stats["seeking"],

        "unemployed":
            employment_stats["unemployed"],

        "employment_rate":
            (
                round(
                    employed
                    * 100
                    / total_employment,
                    1
                )
                if total_employment
                else 0
            ),

        "district_data":
            list(
                trainees
                .values("district")
                .annotate(
                    total=Count("id")
                )
                .order_by("-total")
            ),

        "sector_data":
            list(
                courses
                .values("sector")
                .annotate(
                    total=Count("id")
                )
                .order_by("-total")
            ),
    }

    return render(
        request,
        "public_dashboard.html",
        context
    )


# ==========================================================
# TEST EMAIL
# ==========================================================

def test_email(request):

    send_mail(
        "SkillTrack Test Email",
        "This is a test email from my local Django website.",
        None,
        ["vedantpachauri84@gmail.com"],
        fail_silently=False,
    )

    return HttpResponse(
        "Email sent successfully!"
    )


# ==========================================================
# FOLLOW-UP EMAIL CRON / RENDER
# ==========================================================

@csrf_exempt
def run_followup_emails(request):

    secret = request.headers.get(
        "X-FOLLOWUP-SECRET"
    )

    if secret != os.environ.get(
        "FOLLOWUP_SECRET"
    ):

        return JsonResponse(
            {
                "error":
                    "Unauthorized"
            },
            status=401
        )

    try:

        call_command(
            "send_followup_emails"
        )

        return JsonResponse(
            {
                "success": True,
                "message":
                    "Follow-up check completed",
            }
        )

    except Exception as e:

        return JsonResponse(
            {
                "success": False,
                "error": str(e),
            },
            status=500
        )
def ok(request):
    return HttpResponse("hi")


@login_required
def google_login_success(request):
    return redirect_for_user(request.user, request)

@login_required
def choose_role(request):

    profile = getattr(request.user, "userprofile", None)

    if profile is not None and profile.role:
        return redirect_for_user(request.user, request)

    if request.method == "POST":

        role = request.POST.get("role")

        if role not in ["Trainee", "Trainer"]:
            messages.error(
                request,
                "Please select a valid registration type."
            )
            return render(request, "choose_role.html")

        with transaction.atomic():

            if role == "Trainee":

                last_trainee = (
                    Trainee.objects
                    .select_for_update()
                    .order_by("-id")
                    .first()
                )

                beneficiary_id = (
                    f"MH-2026-"
                    f"{(last_trainee.id + 1 if last_trainee else 1):06d}"
                )

                trainee, created = Trainee.objects.get_or_create(
                    user=request.user,
                    defaults={
                        "beneficiary_id": beneficiary_id,
                        "name": (
                            request.user.get_full_name()
                            or request.user.username
                        ),
                        "email": request.user.email,
                        "status": "Pending",
                        "registration_date": date.today(),
                    }
                )

                UserProfile.objects.update_or_create(
                    user=request.user,
                    defaults={
                        "role": "Trainee",
                        "trainee": trainee,
                    }
                )

            elif role == "Trainer":

                trainer, created = (
                    TrainerRegistration.objects.get_or_create(
                        user=request.user,
                        defaults={
                            "name": (
                                request.user.get_full_name()
                                or request.user.username
                            ),
                            "email": request.user.email,
                            "status": "Pending",
                            "registration_date": timezone.now().date(),
                        }
                    )
                )

                # Keep existing registration information synchronized.
                if not created:
                    trainer.email = request.user.email

                    if not trainer.name:
                        trainer.name = (
                            request.user.get_full_name()
                            or request.user.username
                        )

                    # Do NOT reset an already verified trainer.
                    if trainer.status not in ["Verified"]:
                        trainer.status = "Pending"

                    trainer.save(
                        update_fields=[
                            "email",
                            "name",
                            "status",
                        ]
                    )

                UserProfile.objects.update_or_create(
                    user=request.user,
                    defaults={
                        "role": "Trainer",
                        "trainee": None,
                    }
                )

        messages.success(
            request,
            "Registration submitted successfully. "
            "Your application is now pending Authority verification."
        )
        if role == "Trainer":
            return redirect("pending_page")

        return render(
            request,
            "trainees/registration_success.html"
        )

    return render(request, "choose_role.html")
@login_required
def pending_page(request):
    return render(request, "trainers/pending_page.html")
