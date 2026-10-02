from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import (
    validate_password,
)
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from rest_framework import serializers


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
        )


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    password_confirmation = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate_username(self, value):
        if User.objects.filter(
            username__iexact=value
        ).exists():
            raise serializers.ValidationError(
                "This username is already registered."
            )
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "This email address is already registered."
            )
        return value.lower()

    def validate(self, attributes):
        password = attributes["password"]

        if password != attributes["password_confirmation"]:
            raise serializers.ValidationError(
                {
                    "password_confirmation": (
                        "The passwords do not match."
                    )
                }
            )

        candidate_user = User(
            username=attributes["username"],
            email=attributes["email"],
        )

        try:
            validate_password(
                password,
                user=candidate_user,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"password": list(exc.messages)}
            ) from exc

        return attributes

    def create(self, validated_data):
        validated_data.pop("password_confirmation")
        password = validated_data.pop("password")

        return User.objects.create_user(
            password=password,
            **validated_data,
        )


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate(self, attributes):
        user = authenticate(
            request=self.context.get("request"),
            username=attributes["username"],
            password=attributes["password"],
        )

        if user is None:
            raise serializers.ValidationError(
                "Invalid username or password."
            )

        if not user.is_active:
            raise serializers.ValidationError(
                "This account is inactive."
            )

        attributes["user"] = user
        return attributes