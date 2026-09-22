from datetime import date
from importlib.metadata import requires
from typing import Required

from django.contrib.auth.models import User
from django.db import models


from django.db import models
from django.contrib.auth.models import User


class Trainee(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Verified", "Verified"),
        ("Rejected", "Rejected"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="trainee_profile",
        null=True,
        blank=True
    )

    beneficiary_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True)
    district = models.CharField(max_length=50)
    qualification = models.CharField(max_length=100)
    gender = models.CharField(max_length=20)
    registration_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    consent_given = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.beneficiary_id} - {self.name}"


class Course(models.Model):
    name = models.CharField(max_length=100)
    sector = models.CharField(max_length=100)
    duration = models.CharField(max_length=50)
    skills_taught = models.TextField(blank=True, help_text="Comma-separated skills taught by this course.")

    def __str__(self):
        return self.name


class Provider(models.Model):
    STATUS_CHOICES = Trainee.STATUS_CHOICES
    name = models.CharField(max_length=150)
    provider_type = models.CharField(max_length=50)
    district = models.CharField(max_length=50)
    contact_email = models.EmailField(blank=True)
    rating = models.FloatField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")

    def __str__(self):
        return self.name


class Training(models.Model):
    STATUS_CHOICES = [("Pending", "Pending"),("Training", "Training"), ("Completed", "Completed"), ("Dropped", "Dropped")]
    trainee = models.ForeignKey(Trainee, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    completion_percentage = models.IntegerField(default=0)
    #status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )
    batch = models.ForeignKey("TrainingBatch", on_delete=models.SET_NULL, null=True, blank=True, related_name="training_records")
    trainer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="training_records")
    certificate_number = models.CharField(max_length=80, blank=True)

    def __str__(self):
        return f"{self.trainee.name} - {self.course.name}"


class Employment(models.Model):
    STATUS_CHOICES = [
        ("Employed", "Employed"),
        ("Unemployed", "Unemployed"),
        ("Self-Employed", "Self-employed"),
        ("Apprenticeship", "Apprenticeship"),
        ("Further Training", "Further training"),
        ("Other", "Other"),
        ("Seeking", "Seeking work"),
    ]

    VERIFICATION_CHOICES = [
        ("Not Verified", "Not Verified"),
        ("Pending", "Pending"),
        ("Verified", "Verified"),
        ("Rejected", "Rejected"),
    ]

    VERIFICATION_METHOD_CHOICES = [
        ("UAN", "UAN"),
        ("Employment Proof", "Employment Proof"),
        ("Manual", "Manual Verification"),
    ]

    trainee = models.ForeignKey(
        Trainee,
        on_delete=models.CASCADE,
        related_name="employment_records"
    )

    training = models.ForeignKey(
        Training,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employment_outcomes"
    )

    recorded_on = models.DateField(default=date.today)

    # Optional UAN
    uan_demo = models.CharField(
        max_length=30,
        blank=True
    )

    uan_verified_on = models.DateTimeField(
        null=True,
        blank=True
    )

    employer_name = models.CharField(max_length=150, blank=True)
    job_role = models.CharField(max_length=100, blank=True)
    employment_type = models.CharField(max_length=50, blank=True)
    salary = models.IntegerField(default=0)
    employment_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Seeking"
    )

    registration_number = models.CharField(
        max_length=50,
        blank=True
    )

    business_name = models.CharField(
        max_length=150,
        blank=True
    )

    business_type = models.CharField(
        max_length=100,
        blank=True
    )

    work_description = models.CharField(
        max_length=255,
        blank=True
    )

    sector = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=150, blank=True)

    wage_frequency = models.CharField(
        max_length=20,
        choices=[
            ("Monthly", "Monthly"),
            ("Daily", "Daily"),
            ("Annual", "Annual")
        ],
        default="Monthly"
    )

    # Existing verification status
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_CHOICES,
        default="Not Verified"
    )

    # NEW: How employment was verified
    verification_method = models.CharField(
        max_length=30,
        choices=VERIFICATION_METHOD_CHOICES,
        blank=True
    )

    # NEW: Uploaded employment proof
    employment_proof = models.FileField(
        upload_to="employment_proofs/",
        blank=True,
        null=True
    )

    apprenticeship_expected_completion = models.DateField(
        null=True,
        blank=True
    )

    apprenticeship_converted = models.BooleanField(
        null=True,
        blank=True
    )
    employment_proof_type = models.CharField(
        max_length=50,
        blank=True
    )

    stipend = models.IntegerField(default=0)

    outcome_notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.trainee.name} - {self.status}"

class WageRecord(models.Model):
    trainee = models.ForeignKey(Trainee, on_delete=models.CASCADE, related_name="wage_records")
    employment = models.ForeignKey(Employment, on_delete=models.SET_NULL, null=True, blank=True, related_name="wage_records")
    amount = models.PositiveIntegerField()
    frequency = models.CharField(max_length=20, default="Monthly")
    recorded_on = models.DateField()
    source = models.CharField(max_length=30, default="Outcome")

    class Meta:
        ordering = ["recorded_on", "id"]


class TrainingRelevance(models.Model):
    trainee = models.ForeignKey(Trainee, on_delete=models.CASCADE, related_name="relevance_feedback")
    training = models.ForeignKey(Training, on_delete=models.SET_NULL, null=True, blank=True, related_name="relevance_feedback")
    rating = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    skills_used = models.TextField(blank=True)
    skills_not_used = models.TextField(blank=True)
    missing_skills = models.TextField(blank=True)
    feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RetentionRecord(models.Model):
    trainee = models.ForeignKey(Trainee, on_delete=models.CASCADE, related_name="retention_records")
    employment = models.ForeignKey(Employment, on_delete=models.SET_NULL, null=True, blank=True, related_name="retention_records")
    checked_on = models.DateField()
    still_employed = models.BooleanField()
    same_employer = models.BooleanField(null=True, blank=True)
    changed_occupation = models.BooleanField(null=True, blank=True)
    reason_for_leaving = models.CharField(max_length=80, blank=True, choices=[("", "---------"), ("Low salary", "Low salary"), ("Relocation", "Relocation"), ("Poor working conditions", "Poor working conditions"), ("Skill mismatch", "Skill mismatch"), ("Better opportunity", "Better opportunity"), ("Personal/family reason", "Personal/family reason"), ("Lack of growth", "Lack of growth"), ("Employer issue", "Employer issue"), ("Other", "Other")])
    notes = models.TextField(blank=True)


class OccupationSkill(models.Model):
    occupation = models.CharField(max_length=100)
    skill = models.CharField(max_length=100)
    sector = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["occupation", "skill"], name="unique_occupation_skill")]




class FollowUp(models.Model):
    FOLLOWUP_CHOICES = [("3 Months", "3 Months"), ("6 Months", "6 Months"), ("1 Year", "1 Year"), ("3 Years", "3 Years"), ("5 Years", "5 Years")]
    trainee = models.ForeignKey(Trainee, on_delete=models.CASCADE)
    followup_type = models.CharField(max_length=20, choices=FOLLOWUP_CHOICES)
    date = models.DateField()
    employment_status = models.CharField(max_length=50, choices=Employment.STATUS_CHOICES, default="Seeking")
    remarks = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["trainee", "followup_type"], name="unique_trainee_followup_type")]
        ordering = ["date"]

    def __str__(self):
        return f"{self.trainee.name} - {self.followup_type}"


class UserProfile(models.Model):
    ROLE_CHOICES = [("Authority", "Authority"), ("Trainer", "Trainer"), ("Trainee", "Trainee")]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    trainee = models.OneToOneField(Trainee, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class TrainingBatch(models.Model):
    STATUS_CHOICES = [("Active", "Active"), ("Completed", "Completed")]
    name = models.CharField(max_length=150)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE)
    trainer = models.ForeignKey(User, on_delete=models.CASCADE)
    district = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    capacity = models.PositiveIntegerField(default=30)
    trainees = models.ManyToManyField(Trainee, blank=True)
    attendance = models.JSONField(default=dict, blank=True)
    progress = models.JSONField(default=dict, blank=True)
    remarks = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Active")
    completion_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.name


class TrainerRegistration(models.Model):
    STATUS_CHOICES = Trainee.STATUS_CHOICES
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15)
    email = models.EmailField()
    organization = models.CharField(max_length=150)
    district = models.CharField(max_length=50)
    qualification = models.CharField(max_length=150)
    experience = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)
    registration_date = models.DateField()

    def __str__(self):
        return f"{self.name} - {self.organization}"


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="portal_notifications")
    message = models.CharField(max_length=255)
    notification_type = models.CharField(max_length=40, default="System")
    follow_up = models.ForeignKey(FollowUp, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
class TrainingRegistrationRequest(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Verified", "Verified"),
        ("Rejected", "Rejected"),
    ]

    trainee = models.ForeignKey(
        Trainee,
        on_delete=models.CASCADE,
        related_name="training_requests"
    )

    batch = models.ForeignKey(
        TrainingBatch,
        on_delete=models.CASCADE,
        related_name="registration_requests"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    rejection_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["trainee", "batch"],
                name="unique_trainee_batch_request"
            )
        ]
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.trainee.name} - {self.batch.name} - {self.status}"
class UANVerification(models.Model):
    employment = models.ForeignKey(
        Employment,
        on_delete=models.CASCADE,
        related_name="uan_verifications"
    )
    uan = models.CharField(max_length=30)
    verified = models.BooleanField(default=False)
    verification_message = models.CharField(max_length=255, blank=True)
    verified_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.uan} - {'Verified' if self.verified else 'Failed'}"
class SelfEmploymentVerification(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Verified", "Verified"),
        ("Rejected", "Rejected"),
    ]

    employment = models.OneToOneField(
        Employment,
        on_delete=models.CASCADE,
        related_name="self_employment_verification"
    )

    registration_number = models.CharField(max_length=50)
    business_name = models.CharField(max_length=150, blank=True)
    business_type = models.CharField(max_length=100, blank=True)
    work_description = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    verification_message = models.CharField(
        max_length=255,
        blank=True
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.registration_number} - {self.status}"
class TrainingPerformance(models.Model):
    trainee = models.ForeignKey(
        Trainee,
        on_delete=models.CASCADE,
        related_name="performance_records"
    )

    training = models.OneToOneField(
        Training,
        on_delete=models.CASCADE,
        related_name="performance"
    )


    total_classes = models.PositiveIntegerField(default=0)
    attended_classes = models.PositiveIntegerField(default=0)
    attendance_percentage = models.FloatField(default=0)


    total_assignments = models.PositiveIntegerField(default=0)
    completed_assignments = models.PositiveIntegerField(default=0)
    assignment_score = models.FloatField(default=0)


    total_assessments = models.PositiveIntegerField(default=0)
    completed_assessments = models.PositiveIntegerField(default=0)
    assessment_score = models.FloatField(default=0)


    practical_score = models.FloatField(default=0)


    progress_percentage = models.FloatField(default=0)


    final_score = models.FloatField(default=0)


    trainer_remarks = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.trainee.name} - {self.training.course.name}"
