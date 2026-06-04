from django.db import models
from django.contrib.auth.hashers import make_password, check_password as django_check_password
from django.core.validators import MinValueValidator, MaxValueValidator

# User model
class User(models.Model):
    user_id = models.AutoField(primary_key=True)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100, default="")
    last_name = models.CharField(max_length=100, default="")
    birthdate = models.DateField()
    gender = models.CharField(max_length=10, choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')]) # The first value is the value stored in the DB, and the second value is the label displayed on the UI
    height_feet = models.CharField(max_length=10, default="")
    height_inches = models.CharField(max_length=10, default="")
    goal_weight = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)  # Weight in pounds
    goal_to_lose_weight = models.BooleanField(default=False)
    goal_to_feel_better = models.BooleanField(default=False)
    password = models.CharField(max_length=128, blank=True, null=True)  # Optional if signing in with Google
    push_token = models.CharField(max_length=128, blank=True, null=True)
    fitbit_user_id = models.CharField(max_length=64, blank=True, null=True)
    fitbit_access_token = models.TextField(blank=True, null=True)
    fitbit_refresh_token = models.TextField(blank=True, null=True)
    fitbit_token_expires = models.DateTimeField(blank=True, null=True)
    #google_acct_id = models.CharField(max_length=255, blank=True, null=True)  # Optional if creating an account directly

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['user_id', 'first_name', 'last_name', 'birthdate', 'gender', 'height_feet', 'height_inches', 'goal_weight', 'goal_to_lose_weight', 'goal_to_feel_better', 'password']  # Add any additional required fields here

    # When an instance is referenced, prints the user ID and name instead of the default "User object (1)"
    def __str__(self):
        return f"User ID: {self.user_id}, Email: {self.email}"

    def set_password(self, raw_password: str):
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        if not self.password:
            return False
        return django_check_password(raw_password, self.password)

    # def check_password(self, password_entered):
    #     if (password_entered == self.password):
    #         return True
    #     else:
    #         return False
        
# UserData model
class UserData(models.Model):
    data_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)  # Foreign key to User, CASCADE -> all related UserData instances will be deleted if User is deleted
    timestamp = models.DateTimeField(auto_now_add=True)  # Automatically sets the field to the current date and time
    goal_type = models.CharField(max_length=20, choices=[('loseWeight', 'Lose Weight'), ('feelBetter', 'Feel Better'), ('both', 'Both')]) # The first value is the value stored in the DB, and the second value is the label displayed on the UI
    weight_value = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)  # Weight in pounds (optional, depends on goal type)
    feel_better_value = models.IntegerField(null=True, blank=True)  # Scale of 1 to 5 (optional, depends on goal type)

    # When an instance is referenced, prints the user name and timestamp instead of the default "User object (1)"
    def __str__(self):
        return f"Data for {self.user.email} at {self.timestamp}"
    
# NotificationData model
class NotificationData(models.Model):
    notification_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)  # Foreign key to User, CASCADE -> all related NotificationData instances will be deleted if User is deleted
    notification_title = models.CharField(max_length=255, default="Default Title")
    notification_message = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)  # Automatically sets the field to the current date and time
    read_status = models.BooleanField(default=False)

     # When an instance is referenced, prints the user name and timestamp instead of the default "User object (1)"
    def __str__(self):
        return f"Notification for {self.user.email} at {self.timestamp}"


# WearableDevice model
class WearableDevice(models.Model):
    device_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    fitbit_device_id = models.CharField(max_length=64)
    device_type = models.CharField(max_length=32)
    device_name = models.CharField(max_length=64)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.device_name} ({self.user.email})"


class HeartRateSample(models.Model):
    ZONE_CHOICES = [
        ('out_of_range', 'Out of Range'),
        ('fat_burn', 'Fat Burn'),
        ('cardio', 'Cardio'),
        ('peak', 'Peak'),
    ]

    sample_id = models.AutoField(primary_key=True)
    device = models.ForeignKey(WearableDevice, on_delete=models.CASCADE)
    timestamp = models.DateTimeField()
    bpm = models.PositiveSmallIntegerField()
    zone = models.CharField(max_length=20, choices=ZONE_CHOICES)

    def __str__(self):
        return f"{self.bpm} bpm at {self.timestamp}"


class ActivitySummary(models.Model):
    summary_id = models.AutoField(primary_key=True)
    device = models.ForeignKey(WearableDevice, on_delete=models.CASCADE)
    date = models.DateField()
    steps = models.PositiveIntegerField(blank=True, null=True)
    active_minutes = models.PositiveIntegerField(blank=True, null=True)
    calories_burned = models.PositiveIntegerField(blank=True, null=True)
    distance_km = models.DecimalField(max_digits=6, decimal_places=3, blank=True, null=True)

    class Meta:
        unique_together = ('device', 'date')

    def __str__(self):
        return f"Activity for {self.device} on {self.date}"


class EMA(models.Model):
    ACTIVITY_CHOICES = [
        ('none', 'None'),
        ('light', 'Light'),
        ('moderate', 'Moderate'),
        ('vigorous', 'Vigorous'),
    ]

    ema_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    mood = models.PositiveSmallIntegerField(
        blank=True, null=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    energy = models.PositiveSmallIntegerField(
        blank=True, null=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    stress = models.PositiveSmallIntegerField(
        blank=True, null=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    physical_activity = models.CharField(
        max_length=20, choices=ACTIVITY_CHOICES, blank=True, null=True
    )
    weight_lbs = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"EMA for {self.user.email} at {self.timestamp}"
