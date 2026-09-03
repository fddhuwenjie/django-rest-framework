"""
Tests for the optional RFC 9457 "Problem Details" exception handler.
"""
from http.client import responses

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.test import TestCase
from django.utils import translation

from rest_framework import status
from rest_framework.authentication import BasicAuthentication
from rest_framework.exceptions import (
    APIException, AuthenticationFailed, ErrorDetail, NotAuthenticated,
    ParseError, PermissionDenied, NotFound, Throttled, ValidationError
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView
from rest_framework.views import problem_details_exception_handler

factory = APIRequestFactory()


def handle(exc, path='/'):
    """
    Invoke the problem details handler with a minimal context, mimicking
    what `APIView.handle_exception` passes through.
    """
    request = factory.get(path)
    context = {'view': None, 'args': (), 'kwargs': {}, 'request': request}
    return problem_details_exception_handler(exc, context)


class ProblemDetailsUnitTests(TestCase):

    def test_simple_exception_standard_members(self):
        response = handle(NotAuthenticated())

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data['type'] == 'about:blank'
        assert response.data['title'] == 'Unauthorized'
        assert response.data['status'] == 401
        assert response.data['detail'] == (
            'Authentication credentials were not provided.'
        )
        assert response.data['instance'] == '/'

    def test_title_matches_http_status_phrase(self):
        cases = [
            (ParseError(), 400),
            (AuthenticationFailed(), 401),
            (NotAuthenticated(), 401),
            (PermissionDenied(), 403),
            (NotFound(), 404),
            (Throttled(), 429),
            (ValidationError(), 400),
        ]
        for exc, status_code in cases:
            response = handle(exc)
            assert response.data['status'] == status_code
            assert response.status_code == status_code
            assert response.data['title'] == responses[status_code]
            # `status` must always equal the response status code.
            assert response.data['status'] == response.status_code

    def test_default_content_type_is_problem_json(self):
        response = handle(NotFound())
        # No renderer has been negotiated for a bare factory request, so the
        # handler defaults to the problem+json media type.
        assert response.content_type == 'application/problem+json'

    def test_instance_includes_query_string(self):
        response = handle(NotFound(), path='/items/?page=2&foo=bar')
        assert response.data['instance'] == '/items/?page=2&foo=bar'

    def test_instance_without_query_string(self):
        response = handle(NotFound(), path='/items/')
        assert response.data['instance'] == '/items/'

    def test_single_value_exception_preserves_code(self):
        exc = PermissionDenied(detail='No way.', code='not_allowed')
        response = handle(exc)

        assert response.data['detail'] == 'No way.'
        # A single, non field specific error is exposed through `errors` and
        # keeps its original code. It is not tied to a request field, so it
        # carries no JSON Pointer.
        assert response.data['errors'] == [
            {'detail': 'No way.', 'code': 'not_allowed'}
        ]

    def test_default_code_is_preserved(self):
        response = handle(Throttled())
        assert response.data['errors'] == [
            {'detail': 'Request was throttled.', 'code': 'throttled'}
        ]

    def test_nested_validation_errors_use_json_pointer(self):
        exc = ValidationError({
            'name': [ErrorDetail('This field is required.', code='required')],
            'items': [
                {'price': [
                    ErrorDetail('A valid integer is required.', code='invalid')
                ]},
                [ErrorDetail('Second item is invalid.', code='invalid')],
            ],
            'non_field_errors': [
                ErrorDetail('Objects must be unique together.', code='unique')
            ],
            'a/b': [ErrorDetail('Slash field.', code='invalid')],
            '~tilde': [ErrorDetail('Tilde field.', code='invalid')],
            '~/mix': [ErrorDetail('Mixed field.', code='invalid')],
        })
        response = handle(exc)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['title'] == 'Bad Request'
        assert response.data['status'] == 400
        # The structured detail is never stringified into `detail`.
        assert response.data['detail'] == 'Invalid input.'

        errors = response.data['errors']

        # Every entry is a leaf error object, never a flattened string.
        assert all(isinstance(error, dict) for error in errors)

        expected = [
            {'pointer': '/name/0',
             'detail': 'This field is required.', 'code': 'required'},
            {'pointer': '/items/0/price/0',
             'detail': 'A valid integer is required.', 'code': 'invalid'},
            {'pointer': '/items/1/0',
             'detail': 'Second item is invalid.', 'code': 'invalid'},
            {'pointer': '/non_field_errors/0',
             'detail': 'Objects must be unique together.', 'code': 'unique'},
            {'pointer': '/a~1b/0',
             'detail': 'Slash field.', 'code': 'invalid'},
            {'pointer': '/~0tilde/0',
             'detail': 'Tilde field.', 'code': 'invalid'},
            {'pointer': '/~0~1mix/0',
             'detail': 'Mixed field.', 'code': 'invalid'},
        ]
        assert errors == expected

        # List indices are preserved and field names are escaped per RFC 6901.
        pointers = [error['pointer'] for error in errors]
        assert pointers == [
            '/name/0',
            '/items/0/price/0',
            '/items/1/0',
            '/non_field_errors/0',
            '/a~1b/0',
            '/~0tilde/0',
            '/~0~1mix/0',
        ]

    def test_validation_error_as_list(self):
        exc = ValidationError([
            ErrorDetail('First error.', code='invalid'),
            ErrorDetail('Second error.', code='invalid'),
        ])
        response = handle(exc)

        assert response.data['errors'] == [
            {'pointer': '/0', 'detail': 'First error.', 'code': 'invalid'},
            {'pointer': '/1', 'detail': 'Second error.', 'code': 'invalid'},
        ]

    def test_validation_error_as_plain_string(self):
        response = handle(ValidationError('Something is wrong.'))
        assert response.data['errors'] == [
            {'pointer': '/0',
             'detail': 'Something is wrong.', 'code': 'invalid'}
        ]

    def test_www_authenticate_header_is_preserved(self):
        exc = NotAuthenticated()
        exc.auth_header = 'Bearer realm="api"'
        response = handle(exc)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response['WWW-Authenticate'] == 'Bearer realm="api"'
        assert response.data['status'] == 401

    def test_retry_after_header_is_preserved(self):
        response = handle(Throttled(wait=10))

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response['Retry-After'] == '10'
        assert response.data['status'] == 429
        assert response.data['title'] == 'Too Many Requests'
        assert '10 seconds' in response.data['detail']
        assert response.data['errors'][0]['code'] == 'throttled'

    def test_retry_after_header_absent_without_wait(self):
        response = handle(Throttled())
        assert 'Retry-After' not in response

    def test_custom_problem_type_title_and_extensions(self):
        class Conflict(APIException):
            status_code = status.HTTP_409_CONFLICT
            default_detail = 'The item is locked.'
            default_code = 'conflict'
            problem_type = 'https://example.com/probs/locked'
            problem_title = 'Item Locked'
            problem_extensions = {'balance': 42, 'accounts': ['a', 'b']}

        response = handle(Conflict())

        assert response.data['type'] == 'https://example.com/probs/locked'
        assert response.data['title'] == 'Item Locked'
        assert response.data['status'] == 409
        assert response.data['detail'] == 'The item is locked.'
        assert response.data['errors'] == [
            {'detail': 'The item is locked.', 'code': 'conflict'}
        ]
        assert response.data['balance'] == 42
        assert response.data['accounts'] == ['a', 'b']

    def test_extensions_cannot_override_reserved_members(self):
        class BadExtensions(APIException):
            status_code = status.HTTP_400_BAD_REQUEST
            default_detail = 'Real detail.'
            default_code = 'real_code'
            problem_extensions = {
                'type': 'https://evil.example/type',
                'title': 'Evil title',
                'status': 999,
                'detail': 'Evil detail',
                'instance': '/evil',
                'errors': [{'evil': True}],
                'safe_extension': 'kept',
            }

        response = handle(BadExtensions(), path='/real/path/')

        assert response.data['type'] == 'about:blank'
        assert response.data['title'] == 'Bad Request'
        assert response.data['status'] == 400
        assert response.data['detail'] == 'Real detail.'
        assert response.data['instance'] == '/real/path/'
        # The handler-built `errors` (carrying the real code) wins over the
        # extension supplied `errors`.
        assert response.data['errors'] == [
            {'detail': 'Real detail.', 'code': 'real_code'}
        ]
        # Non reserved extension members are still passed through.
        assert response.data['safe_extension'] == 'kept'
        # No stray evil values leak through.
        assert 'https://evil.example/type' not in response.data['type']

    def test_django_http404_is_handled(self):
        response = handle(Http404('No such resource.'))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data['status'] == 404
        assert response.data['title'] == 'Not Found'
        assert response.data['detail'] == 'No such resource.'
        assert response.data['errors'][0]['code'] == 'not_found'

    def test_django_http404_without_message(self):
        response = handle(Http404())
        assert response.data['detail'] == 'Not found.'
        assert response.data['errors'][0]['code'] == 'not_found'

    def test_django_permission_denied_is_handled(self):
        response = handle(DjangoPermissionDenied('Nope.'))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['status'] == 403
        assert response.data['title'] == 'Forbidden'
        assert response.data['detail'] == 'Nope.'
        assert response.data['errors'][0]['code'] == 'permission_denied'

    def test_unrecognized_exception_returns_none(self):
        assert handle(ValueError('unexpected')) is None
        assert handle(Exception('unexpected')) is None
        assert handle(RuntimeError()) is None

    def test_i18n_detail_is_translated_title_stays_english(self):
        with translation.override('fr'):
            response = handle(APIException())

        assert response.data['detail'] == (
            'Une erreur du serveur est survenue.'
        )
        assert response.data['errors'][0]['detail'] == (
            'Une erreur du serveur est survenue.'
        )
        # The HTTP status phrase is not translated.
        assert response.data['title'] == 'Internal Server Error'
        assert response.data['type'] == 'about:blank'


class ProblemDetailsIntegrationTests(TestCase):
    """
    Exercise the handler through the full view/render pipeline.
    """

    def setUp(self):
        self.default_handler = api_settings.EXCEPTION_HANDLER
        api_settings.EXCEPTION_HANDLER = problem_details_exception_handler

    def tearDown(self):
        api_settings.EXCEPTION_HANDLER = self.default_handler

    def test_json_error_response_is_problem_plus_json(self):
        class FailingView(APIView):
            def get(self, request, *args, **kwargs):
                raise NotFound()

        view = FailingView.as_view()
        response = view(factory.get('/missing/', HTTP_ACCEPT='application/json'))
        response.render()

        assert response.status_code == 404
        assert response['Content-Type'] == 'application/problem+json'
        assert response.data['type'] == 'about:blank'
        assert response.data['title'] == 'Not Found'
        assert response.data['instance'] == '/missing/'
        assert b'"status":404' in response.content
        assert response.content.startswith(b'{')  # body is JSON, not HTML

    def test_browsable_api_keeps_html_rendering(self):
        class FailingView(APIView):
            def get(self, request, *args, **kwargs):
                raise PermissionDenied()

        view = FailingView.as_view()
        response = view(factory.get('/forbidden/', HTTP_ACCEPT='text/html'))
        response.render()

        # The browsable API still renders an HTML page with its own media type.
        assert response['Content-Type'].startswith('text/html')
        assert b'<!DOCTYPE html>' in response.content or b'<html' in response.content

    def test_success_responses_are_unchanged(self):
        class OkView(APIView):
            def get(self, request, *args, **kwargs):
                return Response({'ok': True})

        view = OkView.as_view()
        response = view(factory.get('/ok/', HTTP_ACCEPT='application/json'))
        response.render()

        assert response.status_code == 200
        assert response['Content-Type'] == 'application/json'
        assert response.data == {'ok': True}

    def test_basic_auth_401_keeps_www_authenticate(self):
        class ProtectedView(APIView):
            authentication_classes = [BasicAuthentication]
            permission_classes = [IsAuthenticated]

            def get(self, request, *args, **kwargs):
                return Response({'secret': True})

        view = ProtectedView.as_view()
        response = view(factory.get('/secret/', HTTP_ACCEPT='application/json'))
        response.render()

        assert response.status_code == 401
        assert response['WWW-Authenticate'].startswith('Basic')
        assert response['Content-Type'] == 'application/problem+json'
        assert response.data['status'] == 401
        assert response.data['title'] == 'Unauthorized'
        assert response.data['errors'][0]['code'] == 'not_authenticated'

    def test_no_authenticate_header_coerces_to_403(self):
        class ProtectedView(APIView):
            authentication_classes = []
            permission_classes = [IsAuthenticated]

            def get(self, request, *args, **kwargs):
                return Response({'secret': True})

        view = ProtectedView.as_view()
        response = view(factory.get('/secret/', HTTP_ACCEPT='application/json'))
        response.render()

        assert response.status_code == 403
        assert 'WWW-Authenticate' not in response
        assert response.data['status'] == 403
        assert response.data['title'] == 'Forbidden'

    def test_throttle_keeps_retry_after(self):
        class AlwaysThrottle(BaseThrottle):
            def allow_request(self, request, view):
                return False

            def wait(self):
                return 7

        class ThrottledView(APIView):
            throttle_classes = [AlwaysThrottle]

            def get(self, request, *args, **kwargs):
                return Response({'ok': True})

        view = ThrottledView.as_view()
        response = view(factory.get('/throttled/', HTTP_ACCEPT='application/json'))
        response.render()

        assert response.status_code == 429
        assert response['Retry-After'] == '7'
        assert response['Content-Type'] == 'application/problem+json'
        assert response.data['status'] == 429
        assert response.data['title'] == 'Too Many Requests'

    def test_nested_validation_end_to_end(self):
        from rest_framework import serializers

        class NestedSerializer(serializers.Serializer):
            name = serializers.CharField()
            tags = serializers.ListField(child=serializers.IntegerField())

        class OuterSerializer(serializers.Serializer):
            title = serializers.CharField()
            nested = NestedSerializer()

        class ValidateView(APIView):
            def post(self, request, *args, **kwargs):
                serializer = OuterSerializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                return Response(serializer.validated_data)

        view = ValidateView.as_view()
        response = view(factory.post(
            '/validate/',
            {'nested': {'tags': [1, 'x']}},
            format='json',
            HTTP_ACCEPT='application/json',
        ))
        response.render()

        assert response.status_code == 400
        assert response['Content-Type'] == 'application/problem+json'
        pointers = {error['pointer'] for error in response.data['errors']}
        # Missing top level field, missing nested field, and a wrong list item
        # are all reported as leaf errors with their indices preserved.
        assert '/title/0' in pointers
        assert '/nested/name/0' in pointers
        assert '/nested/tags/1/0' in pointers
        for error in response.data['errors']:
            assert isinstance(error['detail'], str)
            assert error['code'] is not None

    def test_unhandled_exception_still_raises(self):
        class BrokenView(APIView):
            def get(self, request, *args, **kwargs):
                raise ValueError('boom')

        view = BrokenView.as_view()
        with self.assertRaises(ValueError):
            view(factory.get('/broken/', HTTP_ACCEPT='application/json'))


class DefaultHandlerUnchangedTests(TestCase):

    def test_default_handler_does_not_emit_problem_members(self):
        from rest_framework.views import exception_handler

        request = factory.get('/')
        response = exception_handler(
            NotAuthenticated(), {'request': request, 'view': None}
        )

        assert response.status_code == 401
        # The default response shape is untouched.
        assert set(response.data.keys()) == {'detail'}
        assert 'type' not in response.data
        assert 'errors' not in response.data
