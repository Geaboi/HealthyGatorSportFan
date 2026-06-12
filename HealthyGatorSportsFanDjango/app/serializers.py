from rest_framework import serializers
from .models import UserData, User, NotificationData, WearableDevice, HeartRateSample, ActivitySummary, EMA, JITAILog
from django.contrib.auth.hashers import make_password
from decimal import Decimal

import logging

# Serializes models to JSON for the front end
# Deserializes and validates data from the front end, then saves it to the database

# Best practice is one serializer per model

# Serializer for User
class UserSerializer(serializers.ModelSerializer):

    password = serializers.CharField(write_only=True, required=False, allow_blank=False, min_length=8)

    class Meta:
        model = User
        fields = '__all__' #['user_id', 'email', 'password', 'first_name', 'last_name', 'birthdate', 'gender', 'height_feet', 'height_inches', 'goal_weight', 'goal_to_lose_weight', 'goal_to_feel_better']
        # required fields in models.py, but these are overidden temporarily
        read_only_fields = ('user_id',)
        extra_kwargs = {
            'birthdate': {'required': False, 'default': "2000-01-01"},
            'gender': {'required': False, 'default': "Other"},
            'first_name': {'required': False, 'default': ''},
            'last_name': {'required': False, 'default': ''},
            'height_feet': {'required': False, 'default': 0},
            'height_inches': {'required': False, 'default': 0},
            'goal_weight': {'required': False, 'default': 0.0},
            'goal_to_lose_weight': {'required': False, 'default': 0.0},
            'goal_to_feel_better': {'required': False, 'default': 0.0},
        }

    def create(self, validated_data):
        pwd = validated_data.pop('password', None)
        user = User(**validated_data)
        if pwd:
            user.set_password(pwd)
        user.save()
        return user

    def update(self, instance, validated_data):
        pwd = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if pwd:
            instance.set_password(pwd)
        instance.save()
        return instance
    
    # def create(self, validated_data):
    #     return User.objects.create(
    #         email=validated_data['email'],
    #         password=validated_data['password'],
    #         first_name = validated_data['first_name'],
    #         last_name = validated_data['last_name'],
    #         birthdate=validated_data['birthdate'],
    #         gender=validated_data['gender'],
    #         height_feet=validated_data['height_feet'],
    #         height_inches=validated_data['height_inches'],
    #         goal_weight=validated_data['goal_weight'],
    #         goal_to_lose_weight=validated_data['goal_to_lose_weight'],
    #         goal_to_feel_better=validated_data['goal_to_feel_better']
    #     )
    
    # def update(self, instance, validated_data):
    #     # Update fields when new data comes from the basicinfo.tsx screen
    #     instance.first_name = validated_data.get('first_name', instance.first_name)
    #     instance.last_name = validated_data.get('last_name', instance.last_name)
    #     instance.birthdate = validated_data.get('birthdate', instance.birthdate)
    #     instance.gender = validated_data.get('gender', instance.gender)
    #     instance.height_feet = validated_data.get('height_feet', instance.height_feet)
    #     instance.height_inches = validated_data.get('height_inches', instance.height_inches)
    #     instance.goal_weight = validated_data.get('goal_weight', instance.goal_weight)
    #     instance.goal_to_feel_better = validated_data.get('goal_to_feel_better', instance.goal_to_feel_better)
    #     instance.goal_to_lose_weight = validated_data.get('goal_to_lose_weight', instance.goal_to_lose_weight)
    #     instance.save()
    #     return instance

    
# Serializer for UserData
class UserDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserData
        fields = ['data_id', 'user', 'timestamp', 'goal_type', 'weight_value', 'feel_better_value']        
        extra_kwargs = {
            'goal_type': {'required': False},
            'weight_value': {'required': False, 'default': 0.0},
            'feel_better_value': {'required': False, 'default': 0.0}
        }

    def create(self, validated_data):
        return UserData.objects.create(
            goal_type=validated_data['goal_type'],
            weight_value=validated_data['weight_value'],
            feel_better_value=validated_data['feel_better_value'],
        )

    def update(self, instance, validated_data):
        # Update fields when new data comes from the basicinfo.tsx screen
        instance.goal_type = validated_data.get('goal_type', instance.goal_type)
        instance.weight_value = validated_data.get('weight_value', instance.weight_value)
        instance.feel_better_value = validated_data.get('feel_better_value', instance.feel_better_value)
        instance.save()
        return instance
    
# Serializer for NotificationData
class NotificationDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationData
        fields = '__all__'  # Or specify the fields you want to include
        # fields = ['user', 'notification_title','notification_message', 'read_status']


class WearableDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = WearableDevice
        fields = '__all__'
        read_only_fields = ('device_id', 'created_at')


class HeartRateSampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = HeartRateSample
        fields = '__all__'
        read_only_fields = ('sample_id',)


class ActivitySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivitySummary
        fields = '__all__'
        read_only_fields = ('summary_id',)


class EMASerializer(serializers.ModelSerializer):
    class Meta:
        model = EMA
        fields = '__all__'
        read_only_fields = ('ema_id', 'timestamp')


class JITAILogSerializer(serializers.ModelSerializer):
    class Meta:
        model = JITAILog
        fields = '__all__'
        read_only_fields = ('log_id', 'timestamp')


class TelemetryWearableDeviceSerializer(serializers.Serializer):
    fitbit_device_id = serializers.CharField(max_length=64)
    device_type = serializers.CharField(max_length=32, required=False, default='tracker')
    device_name = serializers.CharField(max_length=64, required=False, default='Phone Telemetry Device')
    last_synced_at = serializers.DateTimeField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)


class TelemetryHeartRateSampleSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    bpm = serializers.IntegerField(min_value=1, max_value=255)
    zone = serializers.ChoiceField(choices=HeartRateSample.ZONE_CHOICES)


class TelemetryActivitySummarySerializer(serializers.Serializer):
    date = serializers.DateField()
    steps = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    active_minutes = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    calories_burned = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    distance_km = serializers.DecimalField(
        max_digits=6,
        decimal_places=3,
        min_value=Decimal('0'),
        required=False,
        allow_null=True,
    )


class TelemetryEMASerializer(serializers.Serializer):
    mood = serializers.IntegerField(min_value=1, max_value=10, required=False, allow_null=True)
    energy = serializers.IntegerField(min_value=1, max_value=10, required=False, allow_null=True)
    stress = serializers.IntegerField(min_value=1, max_value=10, required=False, allow_null=True)
    physical_activity = serializers.ChoiceField(
        choices=EMA.ACTIVITY_CHOICES,
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    weight_lbs = serializers.DecimalField(
        max_digits=4,
        decimal_places=1,
        required=False,
        allow_null=True,
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class TelemetryJITAILogSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False, default='JITAI prompt')
    message = serializers.CharField(required=False, default='Prompt issued')
    trigger_reason = serializers.CharField(max_length=100)
    volatility_score = serializers.DecimalField(
        max_digits=6,
        decimal_places=3,
        required=False,
        allow_null=True,
    )
    threshold_used = serializers.DecimalField(
        max_digits=6,
        decimal_places=3,
        required=False,
        allow_null=True,
    )
    prompt_status = serializers.ChoiceField(
        choices=JITAILog.PROMPT_STATUS_CHOICES,
        required=False,
        default='sent',
    )
    prompt_count = serializers.IntegerField(min_value=0, required=False, default=0)
    opened_at = serializers.DateTimeField(required=False, allow_null=True)
    interacted_at = serializers.DateTimeField(required=False, allow_null=True)


class TelemetryIngestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    wearable_device = TelemetryWearableDeviceSerializer(required=False)
    heart_rate_samples = TelemetryHeartRateSampleSerializer(many=True, required=False, default=list)
    activity_summaries = TelemetryActivitySummarySerializer(many=True, required=False, default=list)
    emas = TelemetryEMASerializer(many=True, required=False, default=list)
    jitai_logs = TelemetryJITAILogSerializer(many=True, required=False, default=list)
