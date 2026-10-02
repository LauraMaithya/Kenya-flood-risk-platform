from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


User = get_user_model()
STRONG_PASSWORD = "M7!qZ9#vR2@kL8$x"


class AuthenticationAPITests(APITestCase):
    def create_user(self):
        return User.objects.create_user(
            username="laura",
            email="laura@example.com",
            password=STRONG_PASSWORD,
        )

    def test_csrf_endpoint_is_public(self):
        response = self.client.get(
            reverse("monitoring-api:auth-csrf")
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("csrf_token", response.data)
        self.assertIn("csrftoken", response.cookies)

    def test_health_endpoint_remains_public(self):
        response = self.client.get(
            reverse("monitoring-api:health")
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_monitoring_endpoints_require_authentication(self):
        response = self.client.get(
            reverse("monitoring-api:county-list")
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_registration_creates_and_logs_in_user(self):
        response = self.client.post(
            reverse("monitoring-api:auth-register"),
            {
                "username": "new-user",
                "email": "new-user@example.com",
                "password": STRONG_PASSWORD,
                "password_confirmation": STRONG_PASSWORD,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertTrue(
            User.objects.filter(username="new-user").exists()
        )

        current_user_response = self.client.get(
            reverse("monitoring-api:auth-me")
        )

        self.assertEqual(
            current_user_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            current_user_response.data["username"],
            "new-user",
        )

    def test_duplicate_email_is_rejected(self):
        self.create_user()

        response = self.client.post(
            reverse("monitoring-api:auth-register"),
            {
                "username": "different-user",
                "email": "LAURA@example.com",
                "password": STRONG_PASSWORD,
                "password_confirmation": STRONG_PASSWORD,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("email", response.data)

    def test_weak_password_is_rejected(self):
        response = self.client.post(
            reverse("monitoring-api:auth-register"),
            {
                "username": "weak-user",
                "email": "weak@example.com",
                "password": "password",
                "password_confirmation": "password",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("password", response.data)

    def test_valid_login_returns_current_user(self):
        self.create_user()

        login_response = self.client.post(
            reverse("monitoring-api:auth-login"),
            {
                "username": "laura",
                "password": STRONG_PASSWORD,
            },
            format="json",
        )

        self.assertEqual(
            login_response.status_code,
            status.HTTP_200_OK,
        )

        current_user_response = self.client.get(
            reverse("monitoring-api:auth-me")
        )

        self.assertEqual(
            current_user_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            current_user_response.data["email"],
            "laura@example.com",
        )

    def test_invalid_login_is_rejected(self):
        self.create_user()

        response = self.client.post(
            reverse("monitoring-api:auth-login"),
            {
                "username": "laura",
                "password": "incorrect-password",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_logout_ends_authenticated_session(self):
        self.create_user()

        self.client.post(
            reverse("monitoring-api:auth-login"),
            {
                "username": "laura",
                "password": STRONG_PASSWORD,
            },
            format="json",
        )

        logout_response = self.client.post(
            reverse("monitoring-api:auth-logout")
        )

        self.assertEqual(
            logout_response.status_code,
            status.HTTP_200_OK,
        )

        current_user_response = self.client.get(
            reverse("monitoring-api:auth-me")
        )

        self.assertEqual(
            current_user_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )