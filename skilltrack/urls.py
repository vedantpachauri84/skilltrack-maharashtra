from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register-trainee/", views.trainee_register, name="trainee_register"),
    path("register-trainer/", views.trainer_register, name="trainer_register"),
    path("register-provider/", views.provider_register, name="provider_register"),
    path("dashboard", views.dashboard, name="dashboard"),
    path("trainees/", views.trainee_list, name="trainee_list"),
    path("trainees/add/", views.trainee_create, name="trainee_create"),
    path("trainees/<int:id>/", views.trainee_detail, name="trainee_detail"),
    path("trainees/<int:id>/edit/", views.trainee_update, name="trainee_update"),
    path("trainees/<int:id>/verify/", views.verify_trainee, name="verify_trainee"),
    path("trainees/<int:id>/reject/", views.reject_trainee, name="reject_trainee"),
    path("trainers/", views.trainer_list, name="trainer_list"),
    path("trainers/<int:id>/", views.trainer_detail, name="trainer_detail"),
    path("trainers/<int:id>/verify/", views.verify_trainer, name="verify_trainer"),
    path("trainers/<int:id>/reject/", views.reject_trainer, name="reject_trainer"),
    path("providers/", views.provider_list, name="provider_list"),
    path("providers/<int:id>/", views.provider_detail, name="provider_detail"),
    path("providers/<int:id>/verify/", views.verify_provider, name="verify_provider"),
    path("providers/<int:id>/reject/", views.reject_provider, name="reject_provider"),
    path("courses/", views.course_list, name="course_list"),
    path("courses/add/", views.course_create, name="course_create"),
    path("training/batches/", views.batch_list, name="batch_list"),
    path("training/batches/add/", views.batch_create, name="batch_create"),
    path("training/batches/<int:id>/assign/", views.batch_assign_trainees, name="batch_assign_trainees"),
    path("trainer-dashboard/", views.trainer_dashboard, name="trainer_dashboard"),
    path("trainer/batches/<int:id>/", views.trainer_batch_detail, name="trainer_batch_detail"),
    path("trainer/batches/<int:id>/progress/", views.trainer_batch_progress, name="trainer_batch_progress"),
    path("trainer/batches/<int:id>/complete/", views.trainer_complete_batch, name="trainer_complete_batch"),
    path("trainee-dashboard/", views.trainee_dashboard, name="trainee_dashboard"),
    path("employment/", views.employment_list, name="employment_list"),
    path("employment/<int:id>/verify/", views.verify_employment, name="verify_employment"),
    path("trainees/<int:id>/outcome-support/", views.outcome_support, name="outcome_support"),
    path("followups/", views.followup_list, name="followup_list"),
    path("followups/<int:id>/", views.followup_update, name="followup_update"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("analytics/", views.analytics, name="analytics"),
path("test-email/", views.test_email),
path("", views.public_dashboard, name="public_dashboard"),
path(
    "trainer/trainees/verify/",
    views.trainer_verify_trainees,
    name="trainer_verify_trainees"
),

path(
    "trainer/trainees/<int:request_id>/verify/",
    views.trainer_verify_request,
    name="trainer_verify_request"
),

path(
    "trainer/trainees/<int:request_id>/reject/",
    views.trainer_reject_request,
    name="trainer_reject_request"
),

path(
    "trainer/attendance/",
    views.trainer_attendance,
    name="trainer_attendance"
),
path(
    "employment/verify-uan/",
    views.verify_uan,
    name="verify_uan",
),
path(
    "employment/verify-registration/",
    views.verify_registration,
    name="verify_registration"
),
    path(
        "run-followups/",
        views.run_followup_emails,
        name="run_followup_emails"
    ),
path(
    "employment/<int:id>/detail/",
    views.employment_detail,
    name="employment_detail",
),
    path("ok",views.ok),
path(
    "google-success/",
    views.google_login_success,
    name="google_login_success",
),
path("choose-role/", views.choose_role, name="choose_role"),
 path("pending/", views.pending_page, name="pending_page"),
]
