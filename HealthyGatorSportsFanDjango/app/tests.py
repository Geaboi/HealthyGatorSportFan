from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status as http_status
from django.contrib.auth.models import User as AuthUser
from rest_framework_simplejwt.tokens import RefreshToken

from app.models import User, UserData, NotificationData, WearableDevice, HeartRateSample, ActivitySummary, EMA, JITAILog
from app.serializers import (
    UserSerializer, UserDataSerializer, NotificationDataSerializer,
    WearableDeviceSerializer, HeartRateSampleSerializer,
    ActivitySummarySerializer, EMASerializer, JITAILogSerializer,
)
from app.utils import check_game_status, send_notification

FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


def make_user(email='test@example.com', password='testpass123', **kwargs):
    defaults = {'birthdate': '2000-01-01', 'gender': 'male'}
    defaults.update(kwargs)
    user = User(email=email, **defaults)
    user.set_password(password)
    user.save()
    return user


def make_device(user, fitbit_device_id='DEV001', device_type='tracker', device_name='Charge 6'):
    return WearableDevice.objects.create(
        user=user,
        fitbit_device_id=fitbit_device_id,
        device_type=device_type,
        device_name=device_name,
    )


def make_game(home_name, home_pts, away_name, away_pts, game_status):
    game = MagicMock()
    game.home_team.name = home_name
    game.home_team.points = home_pts
    game.away_team.name = away_name
    game.away_team.points = away_pts
    game.status = game_status
    return game


def authenticated_client(app_user):
    auth_user, _ = AuthUser.objects.get_or_create(
        username=app_user.email,
        defaults={'email': app_user.email},
    )
    client = APIClient()
    refresh = RefreshToken.for_user(auth_user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
    return client


# ---------------------------------------------------------------------------
# Model: password hashing
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class UserPasswordTests(TestCase):

    def test_set_password_does_not_store_plaintext(self):
        user = User(email='a@b.com', birthdate='2000-01-01', gender='male')
        user.set_password('mypassword')
        self.assertNotEqual(user.password, 'mypassword')

    def test_correct_password_returns_true(self):
        user = User(email='a@b.com', birthdate='2000-01-01', gender='male')
        user.set_password('mypassword')
        self.assertTrue(user.check_password('mypassword'))

    def test_wrong_password_returns_false(self):
        user = User(email='a@b.com', birthdate='2000-01-01', gender='male')
        user.set_password('mypassword')
        self.assertFalse(user.check_password('wrongpassword'))

    def test_no_password_set_returns_false(self):
        user = User(email='a@b.com', birthdate='2000-01-01', gender='male')
        self.assertFalse(user.check_password('anything'))


# ---------------------------------------------------------------------------
# Utils: check_game_status
#
# NOTE: Tests for Florida as the HOME team (winning/losing while home) will
# FAIL due to a bug in utils.py line 57:
#   `if curr_game.home_team == curr_team:`
# should be:
#   `if curr_game.home_team.name == curr_team:`
# The tests are written for the correct expected behavior to document the bug.
# ---------------------------------------------------------------------------

class CheckGameStatusTests(TestCase):

    def _api(self, games):
        api = MagicMock()
        api.get_scoreboard.return_value = games
        return api

    def test_no_florida_game_returns_no_game_found(self):
        api = self._api([make_game('Alabama', 7, 'Georgia', 3, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'No game found')

    def test_empty_scoreboard_returns_no_game_found(self):
        api = self._api([])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'No game found')

    def test_scheduled_game_returns_game_not_started(self):
        api = self._api([make_game('Florida Gators', 0, 'Alabama', 0, 'scheduled')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'Game not started')

    # Florida as AWAY team — these all pass (bug does not affect away branch)

    def test_florida_away_winning_by_14_or_more_returns_winning_decisive(self):
        api = self._api([make_game('Alabama', 10, 'Florida Gators', 24, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'winning_decisive')

    def test_florida_away_winning_by_1_to_13_returns_winning_close(self):
        api = self._api([make_game('Alabama', 10, 'Florida Gators', 17, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'winning_close')

    def test_florida_away_tied_returns_tied(self):
        api = self._api([make_game('Alabama', 7, 'Florida Gators', 7, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'tied')

    def test_florida_away_losing_by_1_to_13_returns_losing_close(self):
        api = self._api([make_game('Alabama', 17, 'Florida Gators', 10, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'losing_close')

    def test_florida_away_losing_by_14_or_more_returns_losing_decisive(self):
        api = self._api([make_game('Alabama', 35, 'Florida Gators', 7, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'losing_decisive')

    def test_florida_away_completed_winning_by_14_returns_won_decisive(self):
        api = self._api([make_game('Alabama', 10, 'Florida Gators', 35, 'completed')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'won_decisive')

    def test_florida_away_completed_winning_by_1_to_13_returns_won_close(self):
        api = self._api([make_game('Alabama', 14, 'Florida Gators', 21, 'completed')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'won_close')

    def test_florida_away_completed_losing_by_1_to_13_returns_lost_close(self):
        api = self._api([make_game('Alabama', 21, 'Florida Gators', 14, 'completed')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'lost_close')

    def test_florida_away_completed_losing_by_14_or_more_returns_lost_decisive(self):
        api = self._api([make_game('Alabama', 35, 'Florida Gators', 10, 'completed')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'lost_decisive')

    # Florida as HOME team — these FAIL due to the home_team == curr_team bug

    def test_florida_home_winning_by_14_or_more_returns_winning_decisive(self):
        api = self._api([make_game('Florida Gators', 24, 'Alabama', 10, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'winning_decisive')

    def test_florida_home_winning_by_1_to_13_returns_winning_close(self):
        api = self._api([make_game('Florida Gators', 17, 'Alabama', 10, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'winning_close')

    def test_florida_home_losing_by_1_to_13_returns_losing_close(self):
        api = self._api([make_game('Florida Gators', 10, 'Alabama', 17, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'losing_close')

    def test_florida_home_losing_by_14_or_more_returns_losing_decisive(self):
        api = self._api([make_game('Florida Gators', 3, 'Alabama', 21, 'in_progress')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'losing_decisive')

    def test_florida_home_completed_won_decisive(self):
        api = self._api([make_game('Florida Gators', 35, 'Alabama', 14, 'completed')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'won_decisive')

    def test_florida_home_completed_lost_decisive(self):
        api = self._api([make_game('Florida Gators', 10, 'Alabama', 35, 'completed')])
        result, *_ = check_game_status(api)
        self.assertEqual(result, 'lost_decisive')

    # Result structure

    def test_result_includes_team_names_and_scores(self):
        api = self._api([make_game('Alabama', 10, 'Florida Gators', 24, 'in_progress')])
        _, home_team, home_score, away_team, away_score, _ = check_game_status(api)
        self.assertEqual(home_team, 'Alabama')
        self.assertEqual(home_score, 10)
        self.assertEqual(away_team, 'Florida Gators')
        self.assertEqual(away_score, 24)

    def test_live_game_returns_in_progress_completion_status(self):
        api = self._api([make_game('Alabama', 7, 'Florida Gators', 7, 'in_progress')])
        *_, completion = check_game_status(api)
        self.assertEqual(completion, 'in_progress')

    def test_finished_game_returns_completed_completion_status(self):
        api = self._api([make_game('Alabama', 14, 'Florida Gators', 21, 'completed')])
        *_, completion = check_game_status(api)
        self.assertEqual(completion, 'completed')


# ---------------------------------------------------------------------------
# API: POST /user/ — CreateUserView
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class CreateUserViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_valid_payload_creates_user_and_returns_201(self):
        response = self.client.post('/user/', {
            'email': 'new@example.com',
            'password': 'securepass123',
        }, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertIn('user_id', response.data)
        self.assertTrue(User.objects.filter(email='new@example.com').exists())

    def test_duplicate_email_returns_400(self):
        make_user(email='taken@example.com')
        response = self.client.post('/user/', {
            'email': 'taken@example.com',
            'password': 'securepass123',
        }, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_missing_email_returns_400(self):
        response = self.client.post('/user/', {'password': 'securepass123'}, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_password_shorter_than_8_chars_returns_400(self):
        response = self.client.post('/user/', {
            'email': 'new@example.com',
            'password': 'short',
        }, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_password_is_not_stored_in_plaintext(self):
        self.client.post('/user/', {
            'email': 'new@example.com',
            'password': 'securepass123',
        }, format='json')
        user = User.objects.get(email='new@example.com')
        self.assertNotEqual(user.password, 'securepass123')


# ---------------------------------------------------------------------------
# API: PUT /user/<id>/ — UserUpdateView
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class UserUpdateViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_user()

    def test_update_first_name_returns_200_and_persists(self):
        response = self.client.put(
            f'/user/{self.user.user_id}/',
            {'first_name': 'Gator'},
            format='json',
        )
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Gator')

    def test_update_password_rehashes_it(self):
        self.client.put(
            f'/user/{self.user.user_id}/',
            {'password': 'newpassword99'},
            format='json',
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newpassword99'))

    def test_nonexistent_user_returns_404(self):
        response = self.client.put('/user/99999/', {'first_name': 'Ghost'}, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# API: POST /user/checkemail/ — CheckEmailView
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class CheckEmailViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_existing_email_returns_exists_true(self):
        make_user(email='existing@example.com')
        response = self.client.post(
            '/user/checkemail/', {'email': 'existing@example.com'}, format='json'
        )
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertTrue(response.data['exists'])

    def test_new_email_returns_exists_false(self):
        response = self.client.post(
            '/user/checkemail/', {'email': 'brand_new@example.com'}, format='json'
        )
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertFalse(response.data['exists'])


# ---------------------------------------------------------------------------
# API: POST /user/login/ — UserLoginView
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class UserLoginViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_user(email='gator@ufl.edu', password='chomp1234')

    def test_valid_credentials_return_200_with_access_and_refresh_tokens(self):
        response = self.client.post('/user/login/', {
            'email': 'gator@ufl.edu',
            'password': 'chomp1234',
        }, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_valid_credentials_return_user_data_in_response(self):
        response = self.client.post('/user/login/', {
            'email': 'gator@ufl.edu',
            'password': 'chomp1234',
        }, format='json')
        self.assertIn('data', response.data)
        self.assertEqual(response.data['data']['email'], 'gator@ufl.edu')

    def test_wrong_password_returns_401(self):
        response = self.client.post('/user/login/', {
            'email': 'gator@ufl.edu',
            'password': 'wrongpassword',
        }, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_nonexistent_email_returns_401(self):
        response = self.client.post('/user/login/', {
            'email': 'nobody@ufl.edu',
            'password': 'chomp1234',
        }, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_missing_email_returns_400(self):
        response = self.client.post('/user/login/', {'password': 'chomp1234'}, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_missing_password_returns_400(self):
        response = self.client.post('/user/login/', {'email': 'gator@ufl.edu'}, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# API: POST /userdata/<id>/ — CreateUserDataView
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class CreateUserDataViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_user()

    def test_valid_payload_returns_201_with_data_id(self):
        response = self.client.post(f'/userdata/{self.user.user_id}/', {
            'goal_type': 'loseWeight',
            'weight_value': '185.0',
            'feel_better_value': 3,
        }, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertIn('data_id', response.data)

    def test_entry_is_persisted_to_database(self):
        self.client.post(f'/userdata/{self.user.user_id}/', {
            'goal_type': 'loseWeight',
            'weight_value': '185.0',
        }, format='json')
        self.assertEqual(UserData.objects.filter(user=self.user).count(), 1)


# ---------------------------------------------------------------------------
# API: GET /userdata/latest/<id>/ — LatestUserDataView
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class LatestUserDataViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_user()

    def test_returns_most_recent_entry(self):
        UserData.objects.create(user=self.user, goal_type='loseWeight', weight_value=200)
        UserData.objects.create(user=self.user, goal_type='loseWeight', weight_value=185)
        response = self.client.get(f'/userdata/latest/{self.user.user_id}/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(str(response.data['weight_value']), '185.0')

    def test_user_with_no_data_returns_404(self):
        response = self.client.get(f'/userdata/latest/{self.user.user_id}/')
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# API: Notification endpoints
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class NotificationViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_user()

    def test_list_returns_all_notifications_for_user(self):
        NotificationData.objects.create(user=self.user, notification_message='A')
        NotificationData.objects.create(user=self.user, notification_message='B')
        response = self.client.get(f'/notificationdata/{self.user.user_id}/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_list_does_not_return_other_users_notifications(self):
        other = make_user(email='other@example.com')
        NotificationData.objects.create(user=other, notification_message='Not mine')
        response = self.client.get(f'/notificationdata/{self.user.user_id}/')
        self.assertEqual(len(response.data), 0)

    def test_create_notification_returns_201(self):
        response = self.client.post('/notificationdata/', {
            'user': self.user.user_id,
            'notification_title': 'Score Update',
            'notification_message': 'Florida is winning!',
        }, format='json')
        self.assertEqual(response.status_code, http_status.HTTP_201_CREATED)
        self.assertTrue(NotificationData.objects.filter(user=self.user).exists())

    def test_delete_notification_returns_204_and_removes_record(self):
        notification = NotificationData.objects.create(
            user=self.user, notification_message='Delete me'
        )
        response = self.client.delete(
            f'/notificationdata/delete/{notification.notification_id}/'
        )
        self.assertEqual(response.status_code, http_status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            NotificationData.objects.filter(pk=notification.notification_id).exists()
        )

    def test_delete_nonexistent_notification_returns_404(self):
        response = self.client.delete('/notificationdata/delete/99999/')
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_bulk_delete_removes_all_user_notifications_and_returns_200(self):
        NotificationData.objects.create(user=self.user, notification_message='A')
        NotificationData.objects.create(user=self.user, notification_message='B')
        response = self.client.delete(f'/notificationdata/deleteall/{self.user.user_id}/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(NotificationData.objects.filter(user=self.user).count(), 0)

    def test_bulk_delete_with_no_notifications_returns_404(self):
        response = self.client.delete(f'/notificationdata/deleteall/{self.user.user_id}/')
        self.assertEqual(response.status_code, http_status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# API: GET /auth/me/ — me_view
# ---------------------------------------------------------------------------

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class MeViewTests(TestCase):

    def test_authenticated_request_returns_user_profile(self):
        app_user = make_user(email='me@ufl.edu')
        client = authenticated_client(app_user)
        response = client.get('/auth/me/')
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'me@ufl.edu')

    def test_unauthenticated_request_returns_401(self):
        response = APIClient().get('/auth/me/')
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Utils: send_notification — score deduplication via cache
# ---------------------------------------------------------------------------

class SendNotificationTests(TestCase):

    @patch('app.utils.send_push_notification_next_game')
    @patch('app.utils.cache')
    @patch('app.utils.get_users_with_push_token')
    def test_no_push_tokens_sends_nothing(self, mock_get_tokens, mock_cache, mock_send):
        mock_get_tokens.return_value = []
        send_notification('winning_decisive', 'Florida Gators', 24, 'Alabama', 10)
        mock_send.assert_not_called()

    @patch('app.utils.send_push_notification_next_game')
    @patch('app.utils.cache')
    @patch('app.utils.get_users_with_push_token')
    def test_new_score_sends_notification(self, mock_get_tokens, mock_cache, mock_send):
        mock_get_tokens.return_value = [{'user_id': 1, 'push_token': 'ExponentPushToken[abc]'}]
        mock_cache.get.return_value = None
        send_notification('winning_decisive', 'Florida Gators', 24, 'Alabama', 10)
        mock_send.assert_called_once()

    @patch('app.utils.send_push_notification_next_game')
    @patch('app.utils.cache')
    @patch('app.utils.get_users_with_push_token')
    def test_unchanged_score_does_not_resend(self, mock_get_tokens, mock_cache, mock_send):
        mock_get_tokens.return_value = [{'user_id': 1, 'push_token': 'ExponentPushToken[abc]'}]
        mock_cache.get.return_value = b'24-10'
        send_notification('winning_decisive', 'Florida Gators', 24, 'Alabama', 10)
        mock_send.assert_not_called()

    @patch('app.utils.send_push_notification_next_game')
    @patch('app.utils.cache')
    @patch('app.utils.get_users_with_push_token')
    def test_updated_score_sends_new_notification(self, mock_get_tokens, mock_cache, mock_send):
        mock_get_tokens.return_value = [{'user_id': 1, 'push_token': 'ExponentPushToken[abc]'}]
        mock_cache.get.return_value = b'17-10'
        send_notification('winning_decisive', 'Florida Gators', 24, 'Alabama', 10)
        mock_send.assert_called_once()

    @patch('app.utils.send_push_notification_next_game')
    @patch('app.utils.cache')
    @patch('app.utils.get_users_with_push_token')
    def test_no_game_found_sends_nothing(self, mock_get_tokens, mock_cache, mock_send):
        mock_get_tokens.return_value = [{'user_id': 1, 'push_token': 'ExponentPushToken[abc]'}]
        mock_cache.get.return_value = None
        send_notification('No game found', '', 0, '', 0)
        mock_send.assert_not_called()

    @patch('app.utils.send_push_notification_next_game')
    @patch('app.utils.cache')
    @patch('app.utils.get_users_with_push_token')
    def test_sending_notification_updates_cache_with_current_score(
        self, mock_get_tokens, mock_cache, mock_send
    ):
        mock_get_tokens.return_value = [{'user_id': 1, 'push_token': 'ExponentPushToken[abc]'}]
        mock_cache.get.return_value = None
        send_notification('winning_decisive', 'Florida Gators', 24, 'Alabama', 10)
        mock_cache.set.assert_called_once_with('last_score', '24-10')


# ---------------------------------------------------------------------------
# Model: Fitbit token fields
# ---------------------------------------------------------------------------

class UserFitbitFieldTests(TestCase):

    def test_user_stores_fitbit_credentials(self):
        user = make_user()
        expires = timezone.now()
        user.fitbit_user_id = 'ABCD1234'
        user.fitbit_access_token = 'access_token_value'
        user.fitbit_refresh_token = 'refresh_token_value'
        user.fitbit_token_expires = expires
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.fitbit_user_id, 'ABCD1234')
        self.assertEqual(user.fitbit_access_token, 'access_token_value')
        self.assertEqual(user.fitbit_refresh_token, 'refresh_token_value')
        self.assertIsNotNone(user.fitbit_token_expires)

    def test_fitbit_fields_are_nullable(self):
        user = make_user()
        self.assertIsNone(user.fitbit_user_id)
        self.assertIsNone(user.fitbit_access_token)
        self.assertIsNone(user.fitbit_refresh_token)
        self.assertIsNone(user.fitbit_token_expires)


# ---------------------------------------------------------------------------
# Model: WearableDevice
# ---------------------------------------------------------------------------

class WearableDeviceModelTests(TestCase):

    def test_device_is_linked_to_user(self):
        user = make_user()
        device = WearableDevice.objects.create(
            user=user,
            fitbit_device_id='ABCD1234',
            device_type='tracker',
            device_name='Charge 6',
        )
        self.assertEqual(device.user, user)

    def test_is_active_defaults_to_true(self):
        user = make_user()
        device = WearableDevice.objects.create(
            user=user,
            fitbit_device_id='ABCD1234',
            device_type='tracker',
            device_name='Charge 6',
        )
        self.assertTrue(device.is_active)

    def test_created_at_is_set_automatically(self):
        user = make_user()
        device = WearableDevice.objects.create(
            user=user,
            fitbit_device_id='ABCD1234',
            device_type='tracker',
            device_name='Charge 6',
        )
        self.assertIsNotNone(device.created_at)

    def test_deleting_user_deletes_device(self):
        user = make_user()
        WearableDevice.objects.create(
            user=user,
            fitbit_device_id='ABCD1234',
            device_type='tracker',
            device_name='Charge 6',
        )
        user.delete()
        self.assertEqual(WearableDevice.objects.count(), 0)


# ---------------------------------------------------------------------------
# Model: HeartRateSample
# ---------------------------------------------------------------------------

class HeartRateSampleModelTests(TestCase):

    def test_sample_links_to_device(self):
        user = make_user()
        device = make_device(user)
        sample = HeartRateSample.objects.create(
            device=device,
            timestamp=timezone.now(),
            bpm=72,
            zone='fat_burn',
        )
        self.assertEqual(sample.device, device)
        self.assertEqual(sample.bpm, 72)
        self.assertEqual(sample.zone, 'fat_burn')

    def test_deleting_device_deletes_samples(self):
        user = make_user()
        device = make_device(user)
        HeartRateSample.objects.create(
            device=device, timestamp=timezone.now(), bpm=80, zone='cardio'
        )
        device.delete()
        self.assertEqual(HeartRateSample.objects.count(), 0)


# ---------------------------------------------------------------------------
# Model: ActivitySummary
# ---------------------------------------------------------------------------

class ActivitySummaryModelTests(TestCase):

    def test_summary_links_to_device(self):
        user = make_user()
        device = make_device(user)
        summary = ActivitySummary.objects.create(
            device=device,
            date='2026-01-01',
            steps=8000,
            active_minutes=45,
            calories_burned=350,
            distance_km=6.500,
        )
        self.assertEqual(summary.device, device)
        self.assertEqual(summary.steps, 8000)

    def test_duplicate_device_date_raises_error(self):
        from django.db import IntegrityError
        user = make_user()
        device = make_device(user)
        ActivitySummary.objects.create(device=device, date='2026-01-01', steps=8000)
        with self.assertRaises(IntegrityError):
            ActivitySummary.objects.create(device=device, date='2026-01-01', steps=9000)


# ---------------------------------------------------------------------------
# Model: EMA
# ---------------------------------------------------------------------------

class EMAModelTests(TestCase):

    def test_ema_stores_survey_response(self):
        user = make_user()
        ema = EMA.objects.create(
            user=user,
            mood=7,
            energy=5,
            stress=3,
            physical_activity='moderate',
        )
        self.assertEqual(ema.mood, 7)
        self.assertEqual(ema.energy, 5)
        self.assertEqual(ema.stress, 3)
        self.assertEqual(ema.physical_activity, 'moderate')

    def test_timestamp_is_set_automatically(self):
        user = make_user()
        ema = EMA.objects.create(user=user)
        self.assertIsNotNone(ema.timestamp)

    def test_all_fields_are_optional_except_user(self):
        user = make_user()
        ema = EMA.objects.create(user=user)
        self.assertIsNone(ema.mood)
        self.assertIsNone(ema.energy)
        self.assertIsNone(ema.stress)
        self.assertIsNone(ema.physical_activity)
        self.assertIsNone(ema.weight_lbs)
        self.assertIsNone(ema.notes)

    def test_deleting_user_deletes_ema_records(self):
        user = make_user()
        EMA.objects.create(user=user, mood=5)
        user.delete()
        self.assertEqual(EMA.objects.count(), 0)

    def test_mood_rejects_out_of_range_values(self):
        from django.core.exceptions import ValidationError
        user = make_user()
        ema_low = EMA(user=user, mood=0)
        with self.assertRaises(ValidationError):
            ema_low.full_clean()
        ema_high = EMA(user=user, mood=11)
        with self.assertRaises(ValidationError):
            ema_high.full_clean()


# ---------------------------------------------------------------------------
# Model: JITAILog
# ---------------------------------------------------------------------------

class JITAILogModelTests(TestCase):

    def test_jitai_log_stores_intervention(self):
        user = make_user()
        log = JITAILog.objects.create(
            user=user,
            title='Move more!',
            message='You have been inactive for 2 hours.',
            trigger_reason='low_steps',
            volatility_score=0.720,
            threshold_used=0.650,
            prompt_count=3,
        )
        self.assertEqual(log.trigger_reason, 'low_steps')
        self.assertEqual(log.title, 'Move more!')
        self.assertEqual(log.prompt_count, 3)
        self.assertIsNotNone(log.volatility_score)
        self.assertIsNotNone(log.threshold_used)

    def test_prompt_status_defaults_to_sent(self):
        user = make_user()
        log = JITAILog.objects.create(
            user=user,
            title='Move!',
            message='Get up.',
            trigger_reason='low_steps',
        )
        self.assertEqual(log.prompt_status, 'sent')

    def test_opened_at_and_interacted_at_are_nullable(self):
        user = make_user()
        log = JITAILog.objects.create(
            user=user,
            title='Move!',
            message='Get up.',
            trigger_reason='low_steps',
        )
        self.assertIsNone(log.opened_at)
        self.assertIsNone(log.interacted_at)

    def test_timestamp_is_set_automatically(self):
        user = make_user()
        log = JITAILog.objects.create(
            user=user,
            title='Move!',
            message='Get up.',
            trigger_reason='low_steps',
        )
        self.assertIsNotNone(log.timestamp)

    def test_deleting_user_deletes_jitai_logs(self):
        user = make_user()
        JITAILog.objects.create(
            user=user, title='Hi', message='Go.', trigger_reason='low_steps'
        )
        user.delete()
        self.assertEqual(JITAILog.objects.count(), 0)


class WearableDeviceSerializerTests(TestCase):

    def test_serializer_creates_device(self):
        user = make_user()
        data = {
            'user': user.user_id,
            'fitbit_device_id': 'DEV001',
            'device_type': 'tracker',
            'device_name': 'Charge 6',
        }
        serializer = WearableDeviceSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        device = serializer.save()
        self.assertEqual(device.device_name, 'Charge 6')


class HeartRateSampleSerializerTests(TestCase):

    def test_serializer_creates_sample(self):
        user = make_user()
        device = make_device(user)
        data = {
            'device': device.device_id,
            'timestamp': '2026-01-01T10:00:00Z',
            'bpm': 72,
            'zone': 'fat_burn',
        }
        serializer = HeartRateSampleSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        sample = serializer.save()
        self.assertEqual(sample.bpm, 72)


class ActivitySummarySerializerTests(TestCase):

    def test_serializer_creates_summary(self):
        user = make_user()
        device = make_device(user)
        data = {
            'device': device.device_id,
            'date': '2026-01-01',
            'steps': 8000,
            'active_minutes': 45,
        }
        serializer = ActivitySummarySerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        summary = serializer.save()
        self.assertEqual(summary.steps, 8000)


class EMASerializerTests(TestCase):

    def test_serializer_creates_ema(self):
        user = make_user()
        data = {
            'user': user.user_id,
            'mood': 7,
            'energy': 5,
            'stress': 3,
            'physical_activity': 'moderate',
        }
        serializer = EMASerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        ema = serializer.save()
        self.assertEqual(ema.mood, 7)


class JITAILogSerializerTests(TestCase):

    def test_serializer_creates_jitai_log(self):
        user = make_user()
        data = {
            'user': user.user_id,
            'title': 'Move more!',
            'message': 'You have been inactive for 2 hours.',
            'trigger_reason': 'low_steps',
            'prompt_count': 1,
        }
        serializer = JITAILogSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        log = serializer.save()
        self.assertEqual(log.trigger_reason, 'low_steps')
        self.assertEqual(log.prompt_status, 'sent')
