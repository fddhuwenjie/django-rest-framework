from base64 import b64decode, b64encode
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.paginator import Paginator as DjangoPaginator
from django.db import models
from django.test import TestCase

from rest_framework import (
    exceptions, filters, generics, pagination, serializers, status
)
from rest_framework.pagination import PAGE_BREAK, PageLink
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

factory = APIRequestFactory()


class TestPaginationIntegration:
    """
    Integration tests.
    """

    def setup_method(self):
        class PassThroughSerializer(serializers.BaseSerializer):
            def to_representation(self, item):
                return item

        class EvenItemsOnly(filters.BaseFilterBackend):
            def filter_queryset(self, request, queryset, view):
                return [item for item in queryset if item % 2 == 0]

        class BasicPagination(pagination.PageNumberPagination):
            page_size = 5
            page_size_query_param = 'page_size'
            max_page_size = 20

        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=range(1, 101),
            filter_backends=[EvenItemsOnly],
            pagination_class=BasicPagination
        )

    def test_filtered_items_are_paginated(self):
        request = factory.get('/', {'page': 2})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'results': [12, 14, 16, 18, 20],
            'previous': 'http://testserver/',
            'next': 'http://testserver/?page=3',
            'count': 50
        }

    def test_setting_page_size(self):
        """
        When 'paginate_by_param' is set, the client may choose a page size.
        """
        request = factory.get('/', {'page_size': 10})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'results': [2, 4, 6, 8, 10, 12, 14, 16, 18, 20],
            'previous': None,
            'next': 'http://testserver/?page=2&page_size=10',
            'count': 50
        }

    def test_setting_page_size_over_maximum(self):
        """
        When page_size parameter exceeds maximum allowable,
        then it should be capped to the maximum.
        """
        request = factory.get('/', {'page_size': 1000})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'results': [
                2, 4, 6, 8, 10, 12, 14, 16, 18, 20,
                22, 24, 26, 28, 30, 32, 34, 36, 38, 40
            ],
            'previous': None,
            'next': 'http://testserver/?page=2&page_size=1000',
            'count': 50
        }

    def test_setting_page_size_to_zero(self):
        """
        When page_size parameter is invalid it should return to the default.
        """
        request = factory.get('/', {'page_size': 0})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'results': [2, 4, 6, 8, 10],
            'previous': None,
            'next': 'http://testserver/?page=2&page_size=0',
            'count': 50
        }

    def test_additional_query_params_are_preserved(self):
        request = factory.get('/', {'page': 2, 'filter': 'even'})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'results': [12, 14, 16, 18, 20],
            'previous': 'http://testserver/?filter=even',
            'next': 'http://testserver/?filter=even&page=3',
            'count': 50
        }

    def test_empty_query_params_are_preserved(self):
        request = factory.get('/', {'page': 2, 'filter': ''})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'results': [12, 14, 16, 18, 20],
            'previous': 'http://testserver/?filter=',
            'next': 'http://testserver/?filter=&page=3',
            'count': 50
        }

    def test_404_not_found_for_zero_page(self):
        request = factory.get('/', {'page': '0'})
        response = self.view(request)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data == {
            'detail': 'Invalid page.'
        }

    def test_404_not_found_for_invalid_page(self):
        request = factory.get('/', {'page': 'invalid'})
        response = self.view(request)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data == {
            'detail': 'Invalid page.'
        }


class TestPaginationDisabledIntegration:
    """
    Integration tests for disabled pagination.
    """

    def setup_method(self):
        class PassThroughSerializer(serializers.BaseSerializer):
            def to_representation(self, item):
                return item

        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=range(1, 101),
            pagination_class=None
        )

    def test_unpaginated_list(self):
        request = factory.get('/', {'page': 2})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == list(range(1, 101))


class TestPageNumberPagination:
    """
    Unit tests for `pagination.PageNumberPagination`.
    """

    def setup_method(self):
        class ExamplePagination(pagination.PageNumberPagination):
            page_size = 5

        self.pagination = ExamplePagination()
        self.queryset = range(1, 101)

    def paginate_queryset(self, request):
        return list(self.pagination.paginate_queryset(self.queryset, request))

    def get_paginated_content(self, queryset):
        response = self.pagination.get_paginated_response(queryset)
        return response.data

    def get_html_context(self):
        return self.pagination.get_html_context()

    @pytest.mark.parametrize('url', ['/', '/?page='])
    def test_no_page_number(self, url):
        request = Request(factory.get(url))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [1, 2, 3, 4, 5]
        assert content == {
            'results': [1, 2, 3, 4, 5],
            'previous': None,
            'next': 'http://testserver/?page=2',
            'count': 100
        }
        assert context == {
            'previous_url': None,
            'next_url': 'http://testserver/?page=2',
            'page_links': [
                PageLink('http://testserver/', 1, True, False),
                PageLink('http://testserver/?page=2', 2, False, False),
                PageLink('http://testserver/?page=3', 3, False, False),
                PAGE_BREAK,
                PageLink('http://testserver/?page=20', 20, False, False),
            ]
        }
        assert self.pagination.display_page_controls
        assert isinstance(self.pagination.to_html(), str)

    def test_second_page(self):
        request = Request(factory.get('/', {'page': 2}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [6, 7, 8, 9, 10]
        assert content == {
            'results': [6, 7, 8, 9, 10],
            'previous': 'http://testserver/',
            'next': 'http://testserver/?page=3',
            'count': 100
        }
        assert context == {
            'previous_url': 'http://testserver/',
            'next_url': 'http://testserver/?page=3',
            'page_links': [
                PageLink('http://testserver/', 1, False, False),
                PageLink('http://testserver/?page=2', 2, True, False),
                PageLink('http://testserver/?page=3', 3, False, False),
                PAGE_BREAK,
                PageLink('http://testserver/?page=20', 20, False, False),
            ]
        }

    def test_last_page(self):
        request = Request(factory.get('/', {'page': 'last'}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [96, 97, 98, 99, 100]
        assert content == {
            'results': [96, 97, 98, 99, 100],
            'previous': 'http://testserver/?page=19',
            'next': None,
            'count': 100
        }
        assert context == {
            'previous_url': 'http://testserver/?page=19',
            'next_url': None,
            'page_links': [
                PageLink('http://testserver/', 1, False, False),
                PAGE_BREAK,
                PageLink('http://testserver/?page=18', 18, False, False),
                PageLink('http://testserver/?page=19', 19, False, False),
                PageLink('http://testserver/?page=20', 20, True, False),
            ]
        }

    def test_invalid_page(self):
        request = Request(factory.get('/', {'page': 'invalid'}))
        with pytest.raises(exceptions.NotFound):
            self.paginate_queryset(request)

    def test_get_paginated_response_schema(self):
        unpaginated_schema = {
            'type': 'object',
            'item': {
                'properties': {
                    'test-property': {
                        'type': 'integer',
                    },
                },
            },
        }

        assert self.pagination.get_paginated_response_schema(unpaginated_schema) == {
            'type': 'object',
            'required': ['count', 'results'],
            'properties': {
                'count': {
                    'type': 'integer',
                    'example': 123,
                },
                'next': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?page=4',
                },
                'previous': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?page=2',
                },
                'results': unpaginated_schema,
            },
        }


class TestPageNumberPaginationOverride:
    """
    Unit tests for `pagination.PageNumberPagination`.

    the Django Paginator Class is overridden.
    """

    def setup_method(self):
        class OverriddenDjangoPaginator(DjangoPaginator):
            # override the count in our overridden Django Paginator
            # we will only return one page, with one item
            count = 1

        class ExamplePagination(pagination.PageNumberPagination):
            django_paginator_class = OverriddenDjangoPaginator
            page_size = 5

        self.pagination = ExamplePagination()
        self.queryset = range(1, 101)

    def paginate_queryset(self, request):
        return list(self.pagination.paginate_queryset(self.queryset, request))

    def get_paginated_content(self, queryset):
        response = self.pagination.get_paginated_response(queryset)
        return response.data

    def get_html_context(self):
        return self.pagination.get_html_context()

    def test_no_page_number(self):
        request = Request(factory.get('/'))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [1]
        assert content == {
            'results': [1, ],
            'previous': None,
            'next': None,
            'count': 1
        }
        assert context == {
            'previous_url': None,
            'next_url': None,
            'page_links': [
                PageLink('http://testserver/', 1, True, False),
            ]
        }
        assert not self.pagination.display_page_controls
        assert isinstance(self.pagination.to_html(), str)

    def test_invalid_page(self):
        request = Request(factory.get('/', {'page': 'invalid'}))
        with pytest.raises(exceptions.NotFound):
            self.paginate_queryset(request)


class TestLimitOffset:
    """
    Unit tests for `pagination.LimitOffsetPagination`.
    """

    def setup_method(self):
        class ExamplePagination(pagination.LimitOffsetPagination):
            default_limit = 10
            max_limit = 15

        self.pagination = ExamplePagination()
        self.queryset = range(1, 101)

    def paginate_queryset(self, request):
        return list(self.pagination.paginate_queryset(self.queryset, request))

    def get_paginated_content(self, queryset):
        response = self.pagination.get_paginated_response(queryset)
        return response.data

    def get_html_context(self):
        return self.pagination.get_html_context()

    def test_no_offset(self):
        request = Request(factory.get('/', {'limit': 5}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [1, 2, 3, 4, 5]
        assert content == {
            'results': [1, 2, 3, 4, 5],
            'previous': None,
            'next': 'http://testserver/?limit=5&offset=5',
            'count': 100
        }
        assert context == {
            'previous_url': None,
            'next_url': 'http://testserver/?limit=5&offset=5',
            'page_links': [
                PageLink('http://testserver/?limit=5', 1, True, False),
                PageLink('http://testserver/?limit=5&offset=5', 2, False, False),
                PageLink('http://testserver/?limit=5&offset=10', 3, False, False),
                PAGE_BREAK,
                PageLink('http://testserver/?limit=5&offset=95', 20, False, False),
            ]
        }
        assert self.pagination.display_page_controls
        assert isinstance(self.pagination.to_html(), str)

    def test_pagination_not_applied_if_limit_or_default_limit_not_set(self):
        class MockPagination(pagination.LimitOffsetPagination):
            default_limit = None
        request = Request(factory.get('/'))
        queryset = MockPagination().paginate_queryset(self.queryset, request)
        assert queryset is None

    def test_single_offset(self):
        """
        When the offset is not a multiple of the limit we get some edge cases:
        * The first page should still be offset zero.
        * We may end up displaying an extra page in the pagination control.
        """
        request = Request(factory.get('/', {'limit': 5, 'offset': 1}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [2, 3, 4, 5, 6]
        assert content == {
            'results': [2, 3, 4, 5, 6],
            'previous': 'http://testserver/?limit=5',
            'next': 'http://testserver/?limit=5&offset=6',
            'count': 100
        }
        assert context == {
            'previous_url': 'http://testserver/?limit=5',
            'next_url': 'http://testserver/?limit=5&offset=6',
            'page_links': [
                PageLink('http://testserver/?limit=5', 1, False, False),
                PageLink('http://testserver/?limit=5&offset=1', 2, True, False),
                PageLink('http://testserver/?limit=5&offset=6', 3, False, False),
                PAGE_BREAK,
                PageLink('http://testserver/?limit=5&offset=96', 21, False, False),
            ]
        }

    def test_first_offset(self):
        request = Request(factory.get('/', {'limit': 5, 'offset': 5}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [6, 7, 8, 9, 10]
        assert content == {
            'results': [6, 7, 8, 9, 10],
            'previous': 'http://testserver/?limit=5',
            'next': 'http://testserver/?limit=5&offset=10',
            'count': 100
        }
        assert context == {
            'previous_url': 'http://testserver/?limit=5',
            'next_url': 'http://testserver/?limit=5&offset=10',
            'page_links': [
                PageLink('http://testserver/?limit=5', 1, False, False),
                PageLink('http://testserver/?limit=5&offset=5', 2, True, False),
                PageLink('http://testserver/?limit=5&offset=10', 3, False, False),
                PAGE_BREAK,
                PageLink('http://testserver/?limit=5&offset=95', 20, False, False),
            ]
        }

    def test_middle_offset(self):
        request = Request(factory.get('/', {'limit': 5, 'offset': 10}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [11, 12, 13, 14, 15]
        assert content == {
            'results': [11, 12, 13, 14, 15],
            'previous': 'http://testserver/?limit=5&offset=5',
            'next': 'http://testserver/?limit=5&offset=15',
            'count': 100
        }
        assert context == {
            'previous_url': 'http://testserver/?limit=5&offset=5',
            'next_url': 'http://testserver/?limit=5&offset=15',
            'page_links': [
                PageLink('http://testserver/?limit=5', 1, False, False),
                PageLink('http://testserver/?limit=5&offset=5', 2, False, False),
                PageLink('http://testserver/?limit=5&offset=10', 3, True, False),
                PageLink('http://testserver/?limit=5&offset=15', 4, False, False),
                PAGE_BREAK,
                PageLink('http://testserver/?limit=5&offset=95', 20, False, False),
            ]
        }

    def test_ending_offset(self):
        request = Request(factory.get('/', {'limit': 5, 'offset': 95}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        context = self.get_html_context()
        assert queryset == [96, 97, 98, 99, 100]
        assert content == {
            'results': [96, 97, 98, 99, 100],
            'previous': 'http://testserver/?limit=5&offset=90',
            'next': None,
            'count': 100
        }
        assert context == {
            'previous_url': 'http://testserver/?limit=5&offset=90',
            'next_url': None,
            'page_links': [
                PageLink('http://testserver/?limit=5', 1, False, False),
                PAGE_BREAK,
                PageLink('http://testserver/?limit=5&offset=85', 18, False, False),
                PageLink('http://testserver/?limit=5&offset=90', 19, False, False),
                PageLink('http://testserver/?limit=5&offset=95', 20, True, False),
            ]
        }

    def test_erroneous_offset(self):
        request = Request(factory.get('/', {'limit': 5, 'offset': 1000}))
        queryset = self.paginate_queryset(request)
        self.get_paginated_content(queryset)
        self.get_html_context()

    def test_invalid_offset(self):
        """
        An invalid offset query param should be treated as 0.
        """
        request = Request(factory.get('/', {'limit': 5, 'offset': 'invalid'}))
        queryset = self.paginate_queryset(request)
        assert queryset == [1, 2, 3, 4, 5]

    def test_invalid_limit(self):
        """
        An invalid limit query param should be ignored in favor of the default.
        """
        request = Request(factory.get('/', {'limit': 'invalid', 'offset': 0}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        next_limit = self.pagination.default_limit
        next_offset = self.pagination.default_limit
        next_url = f'http://testserver/?limit={next_limit}&offset={next_offset}'
        assert queryset == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert content.get('next') == next_url

    def test_zero_limit(self):
        """
        An zero limit query param should be ignored in favor of the default.
        """
        request = Request(factory.get('/', {'limit': 0, 'offset': 0}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        next_limit = self.pagination.default_limit
        next_offset = self.pagination.default_limit
        next_url = f'http://testserver/?limit={next_limit}&offset={next_offset}'
        assert queryset == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert content.get('next') == next_url

    def test_max_limit(self):
        """
        The limit defaults to the max_limit when there is a max_limit and the
        requested limit is greater than the max_limit
        """
        offset = 50
        request = Request(factory.get('/', {'limit': '11235', 'offset': offset}))
        queryset = self.paginate_queryset(request)
        content = self.get_paginated_content(queryset)
        max_limit = self.pagination.max_limit
        next_offset = offset + max_limit
        prev_offset = offset - max_limit
        base_url = f'http://testserver/?limit={max_limit}'
        next_url = base_url + f'&offset={next_offset}'
        prev_url = base_url + f'&offset={prev_offset}'
        assert queryset == list(range(51, 66))
        assert content.get('next') == next_url
        assert content.get('previous') == prev_url

    def test_get_paginated_response_schema(self):
        unpaginated_schema = {
            'type': 'object',
            'item': {
                'properties': {
                    'test-property': {
                        'type': 'integer',
                    },
                },
            },
        }

        assert self.pagination.get_paginated_response_schema(unpaginated_schema) == {
            'type': 'object',
            'required': ['count', 'results'],
            'properties': {
                'count': {
                    'type': 'integer',
                    'example': 123,
                },
                'next': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?offset=400&limit=100',
                },
                'previous': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?offset=200&limit=100',
                },
                'results': unpaginated_schema,
            },
        }


class CursorPaginationTestsMixin:

    def test_invalid_cursor(self):
        request = Request(factory.get('/', {'cursor': '123'}))
        with pytest.raises(exceptions.NotFound):
            self.pagination.paginate_queryset(self.queryset, request)

    def test_use_with_ordering_filter(self):
        class MockView:
            filter_backends = (filters.OrderingFilter,)
            ordering_fields = ['username', 'created']
            ordering = 'created'

        request = Request(factory.get('/', {'ordering': 'username'}))
        ordering = self.pagination.get_ordering(request, [], MockView())
        assert ordering == ('username',)

        request = Request(factory.get('/', {'ordering': '-username'}))
        ordering = self.pagination.get_ordering(request, [], MockView())
        assert ordering == ('-username',)

        request = Request(factory.get('/', {'ordering': 'invalid'}))
        ordering = self.pagination.get_ordering(request, [], MockView())
        assert ordering == ('created',)

    def test_use_with_ordering_filter_without_ordering_default_value(self):
        class MockView:
            filter_backends = (filters.OrderingFilter,)
            ordering_fields = ['username', 'created']

        request = Request(factory.get('/'))
        ordering = self.pagination.get_ordering(request, [], MockView())
        # it gets the value of `ordering` provided by CursorPagination
        assert ordering == ('created',)

        request = Request(factory.get('/', {'ordering': 'username'}))
        ordering = self.pagination.get_ordering(request, [], MockView())
        assert ordering == ('username',)

        request = Request(factory.get('/', {'ordering': 'invalid'}))
        ordering = self.pagination.get_ordering(request, [], MockView())
        assert ordering == ('created',)

    def test_cursor_pagination(self):
        (previous, current, next, previous_url, next_url) = self.get_pages('/')

        assert previous is None
        assert current == [1, 1, 1, 1, 1]
        assert next == [1, 2, 3, 4, 4]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [1, 1, 1, 1, 1]
        assert current == [1, 2, 3, 4, 4]
        assert next == [4, 4, 5, 6, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [1, 2, 3, 4, 4]
        assert current == [4, 4, 5, 6, 7]
        assert next == [7, 7, 7, 7, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [4, 4, 4, 5, 6]  # Paging artifact
        assert current == [7, 7, 7, 7, 7]
        assert next == [7, 7, 7, 8, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [7, 7, 7, 7, 7]
        assert current == [7, 7, 7, 8, 9]
        assert next == [9, 9, 9, 9, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [7, 7, 7, 8, 9]
        assert current == [9, 9, 9, 9, 9]
        assert next is None

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [7, 7, 7, 7, 7]
        assert current == [7, 7, 7, 8, 9]
        assert next == [9, 9, 9, 9, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [4, 4, 5, 6, 7]
        assert current == [7, 7, 7, 7, 7]
        assert next == [8, 9, 9, 9, 9]  # Paging artifact

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [1, 2, 3, 4, 4]
        assert current == [4, 4, 5, 6, 7]
        assert next == [7, 7, 7, 7, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [1, 1, 1, 1, 1]
        assert current == [1, 2, 3, 4, 4]
        assert next == [4, 4, 5, 6, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous is None
        assert current == [1, 1, 1, 1, 1]
        assert next == [1, 2, 3, 4, 4]

        assert isinstance(self.pagination.to_html(), str)

    def test_cursor_pagination_current_page_empty_forward(self):
        # Regression test for #6504
        self.pagination.base_url = "/"

        # We have a cursor on the element at position 100, but this element doesn't exist
        # anymore.
        cursor = pagination.Cursor(reverse=False, offset=0, position=100)
        url = self.pagination.encode_cursor(cursor)
        self.pagination.base_url = "/"

        # Loading the page with this cursor doesn't crash
        (previous, current, next, previous_url, next_url) = self.get_pages(url)

        # The previous url doesn't crash either
        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        # And point to things that are not completely off.
        assert previous == [7, 7, 7, 8, 9]
        assert current == [9, 9, 9, 9, 9]
        assert next == []
        assert previous_url is not None
        assert next_url is not None

    def test_cursor_pagination_current_page_empty_reverse(self):
        # Regression test for #6504
        self.pagination.base_url = "/"

        # We have a cursor on the element at position 100, but this element doesn't exist
        # anymore.
        cursor = pagination.Cursor(reverse=True, offset=0, position=100)
        url = self.pagination.encode_cursor(cursor)
        self.pagination.base_url = "/"

        # Loading the page with this cursor doesn't crash
        (previous, current, next, previous_url, next_url) = self.get_pages(url)

        # The previous url doesn't crash either
        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        # And point to things that are not completely off.
        assert previous == [7, 7, 7, 7, 8]
        assert current == []
        assert next is None
        assert previous_url is not None
        assert next_url is None

    def test_cursor_pagination_with_page_size(self):
        (previous, current, next, previous_url, next_url) = self.get_pages('/?page_size=20')

        assert previous is None
        assert current == [1, 1, 1, 1, 1, 1, 2, 3, 4, 4, 4, 4, 5, 6, 7, 7, 7, 7, 7, 7]
        assert next == [7, 7, 7, 8, 9, 9, 9, 9, 9, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)
        assert previous == [1, 1, 1, 1, 1, 1, 2, 3, 4, 4, 4, 4, 5, 6, 7, 7, 7, 7, 7, 7]
        assert current == [7, 7, 7, 8, 9, 9, 9, 9, 9, 9]
        assert next is None

    def test_cursor_pagination_with_page_size_over_limit(self):
        (previous, current, next, previous_url, next_url) = self.get_pages('/?page_size=30')

        assert previous is None
        assert current == [1, 1, 1, 1, 1, 1, 2, 3, 4, 4, 4, 4, 5, 6, 7, 7, 7, 7, 7, 7]
        assert next == [7, 7, 7, 8, 9, 9, 9, 9, 9, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)
        assert previous == [1, 1, 1, 1, 1, 1, 2, 3, 4, 4, 4, 4, 5, 6, 7, 7, 7, 7, 7, 7]
        assert current == [7, 7, 7, 8, 9, 9, 9, 9, 9, 9]
        assert next is None

    def test_cursor_pagination_with_page_size_zero(self):
        (previous, current, next, previous_url, next_url) = self.get_pages('/?page_size=0')

        assert previous is None
        assert current == [1, 1, 1, 1, 1]
        assert next == [1, 2, 3, 4, 4]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [1, 1, 1, 1, 1]
        assert current == [1, 2, 3, 4, 4]
        assert next == [4, 4, 5, 6, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [1, 2, 3, 4, 4]
        assert current == [4, 4, 5, 6, 7]
        assert next == [7, 7, 7, 7, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [4, 4, 4, 5, 6]  # Paging artifact
        assert current == [7, 7, 7, 7, 7]
        assert next == [7, 7, 7, 8, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [7, 7, 7, 7, 7]
        assert current == [7, 7, 7, 8, 9]
        assert next == [9, 9, 9, 9, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [7, 7, 7, 8, 9]
        assert current == [9, 9, 9, 9, 9]
        assert next is None

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [7, 7, 7, 7, 7]
        assert current == [7, 7, 7, 8, 9]
        assert next == [9, 9, 9, 9, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [4, 4, 5, 6, 7]
        assert current == [7, 7, 7, 7, 7]
        assert next == [8, 9, 9, 9, 9]  # Paging artifact

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [1, 2, 3, 4, 4]
        assert current == [4, 4, 5, 6, 7]
        assert next == [7, 7, 7, 7, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [1, 1, 1, 1, 1]
        assert current == [1, 2, 3, 4, 4]
        assert next == [4, 4, 5, 6, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous is None
        assert current == [1, 1, 1, 1, 1]
        assert next == [1, 2, 3, 4, 4]

    def test_cursor_pagination_with_page_size_negative(self):
        (previous, current, next, previous_url, next_url) = self.get_pages('/?page_size=-5')

        assert previous is None
        assert current == [1, 1, 1, 1, 1]
        assert next == [1, 2, 3, 4, 4]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [1, 1, 1, 1, 1]
        assert current == [1, 2, 3, 4, 4]
        assert next == [4, 4, 5, 6, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [1, 2, 3, 4, 4]
        assert current == [4, 4, 5, 6, 7]
        assert next == [7, 7, 7, 7, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [4, 4, 4, 5, 6]  # Paging artifact
        assert current == [7, 7, 7, 7, 7]
        assert next == [7, 7, 7, 8, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [7, 7, 7, 7, 7]
        assert current == [7, 7, 7, 8, 9]
        assert next == [9, 9, 9, 9, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)

        assert previous == [7, 7, 7, 8, 9]
        assert current == [9, 9, 9, 9, 9]
        assert next is None

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [7, 7, 7, 7, 7]
        assert current == [7, 7, 7, 8, 9]
        assert next == [9, 9, 9, 9, 9]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [4, 4, 5, 6, 7]
        assert current == [7, 7, 7, 7, 7]
        assert next == [8, 9, 9, 9, 9]  # Paging artifact

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [1, 2, 3, 4, 4]
        assert current == [4, 4, 5, 6, 7]
        assert next == [7, 7, 7, 7, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous == [1, 1, 1, 1, 1]
        assert current == [1, 2, 3, 4, 4]
        assert next == [4, 4, 5, 6, 7]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)

        assert previous is None
        assert current == [1, 1, 1, 1, 1]
        assert next == [1, 2, 3, 4, 4]

    def test_get_paginated_response_schema(self):
        unpaginated_schema = {
            'type': 'object',
            'item': {
                'properties': {
                    'test-property': {
                        'type': 'integer',
                    },
                },
            },
        }

        assert self.pagination.get_paginated_response_schema(unpaginated_schema) == {
            'type': 'object',
            'required': ['results'],
            'properties': {
                'next': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?cursor=cD00ODY%3D"'
                },
                'previous': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?cursor=cj0xJnA9NDg3'
                },
                'results': unpaginated_schema,
            },
        }


class MockPaginationObject:
    def __init__(self, created=None, **attrs):
        self.created = created
        self.__dict__.update(attrs)


class MockPaginationQuerySet:
    """
    A minimal queryset-like object that supports `filter()` with `Q`
    objects, including the lexicographic position filters built by
    `CursorPagination`, and multi-field `order_by()` with per-field
    ascending/descending directions.
    """

    def __init__(self, items):
        self.items = items

    def filter(self, *args, **kwargs):
        items = self.items
        for condition in args:
            items = [
                item for item in items
                if self._matches_condition(condition, item)
            ]
        for key, value in kwargs.items():
            items = [
                item for item in items
                if self._matches_lookup(item, key, value)
            ]
        return MockPaginationQuerySet(items)

    @classmethod
    def _matches_condition(cls, condition, item):
        results = []
        for child in condition.children:
            if isinstance(child, models.Q):
                results.append(cls._matches_condition(child, item))
            else:
                results.append(cls._matches_lookup(item, child[0], child[1]))
        matched = (
            all(results) if condition.connector == models.Q.AND
            else any(results)
        )
        return not matched if condition.negated else matched

    @staticmethod
    def _matches_lookup(item, key, value):
        field_name, _, lookup = key.partition('__')
        if not lookup:
            lookup = 'exact'
        attr = getattr(item, field_name)
        if isinstance(attr, (int, float)) and not isinstance(attr, bool) \
                and isinstance(value, str):
            # Values arrive as strings, as they do in encoded cursors.
            value = type(attr)(value)
        if lookup == 'exact':
            return attr == value
        if lookup == 'gt':
            return attr > value
        if lookup == 'lt':
            return attr < value
        if lookup == 'gte':
            return attr >= value
        if lookup == 'lte':
            return attr <= value
        raise AssertionError('Unsupported lookup: %s' % lookup)

    def order_by(self, *ordering):
        items = list(self.items)
        # Python's sort is stable, so applying the sorts from the least
        # significant field to the most significant field yields the same
        # lexicographic ordering as SQL's `ORDER BY`.
        for term in reversed(ordering):
            descending = term.startswith('-')
            field_name = term.lstrip('-')
            items.sort(
                key=lambda item, field_name=field_name: getattr(item, field_name),
                reverse=descending
            )
        return MockPaginationQuerySet(items)

    def __getitem__(self, sliced):
        return self.items[sliced]


class TestCursorPagination(CursorPaginationTestsMixin):
    """
    Unit tests for `pagination.CursorPagination`.
    """

    def setup_method(self):
        class ExamplePagination(pagination.CursorPagination):
            page_size = 5
            page_size_query_param = 'page_size'
            max_page_size = 20
            ordering = 'created'

        self.pagination = ExamplePagination()
        self.queryset = MockPaginationQuerySet([
            MockPaginationObject(idx) for idx in [
                1, 1, 1, 1, 1,
                1, 2, 3, 4, 4,
                4, 4, 5, 6, 7,
                7, 7, 7, 7, 7,
                7, 7, 7, 8, 9,
                9, 9, 9, 9, 9
            ]
        ])

    def test_legacy_single_field_cursor_is_supported(self):
        # A cursor encoded by an older DRF version carries a single
        # `p` value and must keep working unchanged.
        legacy_cursor = b64encode(b'p=3').decode('ascii')
        request = Request(factory.get('/', {'cursor': legacy_cursor}))
        page = self.pagination.paginate_queryset(self.queryset, request)
        assert [item.created for item in page] == [4, 4, 4, 4, 5]

    def test_single_field_cursor_format_is_unchanged(self):
        # Walk to a page whose next cursor carries a position, and make
        # sure it is still encoded as a single `p` token.
        request = Request(factory.get('/'))
        self.pagination.paginate_queryset(self.queryset, request)
        next_url = self.pagination.get_next_link()

        request = Request(factory.get(next_url))
        self.pagination.paginate_queryset(self.queryset, request)
        next_url = self.pagination.get_next_link()

        encoded = parse_qs(urlparse(next_url).query)['cursor'][0]
        tokens = parse_qs(b64decode(encoded.encode('ascii')).decode('ascii'))
        assert len(tokens.get('p', [])) == 1

    def get_pages(self, url):
        """
        Given a URL return a tuple of:

        (previous page, current page, next page, previous url, next url)
        """
        request = Request(factory.get(url))
        queryset = self.pagination.paginate_queryset(self.queryset, request)
        current = [item.created for item in queryset]

        next_url = self.pagination.get_next_link()
        previous_url = self.pagination.get_previous_link()

        if next_url is not None:
            request = Request(factory.get(next_url))
            queryset = self.pagination.paginate_queryset(self.queryset, request)
            next = [item.created for item in queryset]
        else:
            next = None

        if previous_url is not None:
            request = Request(factory.get(previous_url))
            queryset = self.pagination.paginate_queryset(self.queryset, request)
            previous = [item.created for item in queryset]
        else:
            previous = None

        return (previous, current, next, previous_url, next_url)


class TestCursorPaginationCompositeOrdering:
    """
    Unit tests for `pagination.CursorPagination` with a composite
    ordering made of several fields with mixed directions.
    """

    # Rows as `(category, created, pk)` tuples, in insertion order.
    rows = [
        ('b', 40, 1),
        ('a', 10, 2),
        ('a', 20, 3),
        ('c', 5, 4),
        ('b', 10, 5),
        ('a', 20, 6),
        ('c', 15, 7),
        ('a', 30, 8),
        ('b', 10, 9),
    ]

    # The expected lexicographic order: category asc, created desc, pk asc.
    ordered = [
        ('a', 30, 8),
        ('a', 20, 3),
        ('a', 20, 6),
        ('a', 10, 2),
        ('b', 40, 1),
        ('b', 10, 5),
        ('b', 10, 9),
        ('c', 15, 7),
        ('c', 5, 4),
    ]

    def build_queryset(self):
        return MockPaginationQuerySet([
            MockPaginationObject(created, category=category, pk=pk)
            for category, created, pk in self.rows
        ])

    def setup_method(self):
        class ExamplePagination(pagination.CursorPagination):
            page_size = 3
            ordering = ('category', '-created', 'pk')

        self.pagination = ExamplePagination()
        self.queryset = self.build_queryset()

    def get_page(self, url):
        request = Request(factory.get(url))
        # A fresh queryset simulates other clients inserting/deleting rows
        # between requests; the cursor must still stay consistent.
        page = self.pagination.paginate_queryset(self.build_queryset(), request)
        return [
            (item.category, item.created, item.pk) for item in page
        ]

    def get_pages(self, url):
        request = Request(factory.get(url))
        current = [
            (item.category, item.created, item.pk)
            for item in self.pagination.paginate_queryset(self.queryset, request)
        ]
        next_url = self.pagination.get_next_link()
        previous_url = self.pagination.get_previous_link()
        next_page = self.get_page(next_url) if next_url is not None else None
        previous_page = self.get_page(previous_url) if previous_url is not None else None
        return (previous_page, current, next_page, previous_url, next_url)

    def test_composite_ordering_forward_paging(self):
        (previous, current, next, previous_url, next_url) = self.get_pages('/')
        assert previous is None
        assert current == self.ordered[0:3]
        assert next == self.ordered[3:6]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)
        assert previous == self.ordered[0:3]
        assert current == self.ordered[3:6]
        assert next == self.ordered[6:9]

        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)
        assert previous == self.ordered[3:6]
        assert current == self.ordered[6:9]
        assert next is None

    def test_composite_ordering_backward_paging(self):
        # Walk forward to the last page.
        (_, _, _, _, next_url) = self.get_pages('/')
        (_, _, _, _, next_url) = self.get_pages(next_url)
        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)
        assert current == self.ordered[6:9]
        assert previous == self.ordered[3:6]
        assert next is None

        # Walk back to the first page.
        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)
        assert previous == self.ordered[0:3]
        assert current == self.ordered[3:6]
        assert next == self.ordered[6:9]

        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)
        assert previous is None
        assert current == self.ordered[0:3]
        assert next == self.ordered[3:6]

    def test_composite_ordering_direction_change(self):
        # Forward to the second page.
        (_, _, _, _, next_url) = self.get_pages('/')
        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)
        assert current == self.ordered[3:6]

        # Reverse back to the first page.
        (previous, current, next, previous_url, next_url) = self.get_pages(previous_url)
        assert current == self.ordered[0:3]
        assert next == self.ordered[3:6]

        # Forward again lands back on the same second page, with no
        # duplicated or missing items.
        (previous, current, next, previous_url, next_url) = self.get_pages(next_url)
        assert previous == self.ordered[0:3]
        assert current == self.ordered[3:6]

    def test_composite_ordering_with_repeated_positions_falls_back_to_offset(self):
        # With no unique tie-breaker, full composite positions repeat.
        # The offset mechanism must still return every item exactly once.
        class DuplicatePositionPagination(pagination.CursorPagination):
            page_size = 3
            ordering = ('category', '-created')

        paginator = DuplicatePositionPagination()
        queryset = self.build_queryset()

        seen = []
        url = '/'
        while url is not None:
            request = Request(factory.get(url))
            page = paginator.paginate_queryset(queryset, request)
            seen.extend(
                (item.category, item.created, item.pk) for item in page
            )
            url = paginator.get_next_link()

        assert seen == self.ordered

    def test_invalid_composite_cursor_wrong_field_count(self):
        encoded = b64encode(b'p=a&p=20').decode('ascii')
        request = Request(factory.get('/', {'cursor': encoded}))
        with pytest.raises(exceptions.NotFound):
            self.pagination.paginate_queryset(self.queryset, request)


class CursorPaginationModel(models.Model):
    created = models.IntegerField()


class CursorPaginationCompositeModel(models.Model):
    category = models.CharField(max_length=100)
    created = models.IntegerField()


@pytest.mark.usefixtures("reset_sequences")
class TestCursorPaginationWithValueQueryset(CursorPaginationTestsMixin, TestCase):
    """
    Unit tests for `pagination.CursorPagination` for value querysets.
    """

    def setUp(self):
        class ExamplePagination(pagination.CursorPagination):
            page_size = 5
            page_size_query_param = 'page_size'
            max_page_size = 20
            ordering = 'created'

        self.pagination = ExamplePagination()
        data = [
            1, 1, 1, 1, 1,
            1, 2, 3, 4, 4,
            4, 4, 5, 6, 7,
            7, 7, 7, 7, 7,
            7, 7, 7, 8, 9,
            9, 9, 9, 9, 9
        ]
        for idx in data:
            CursorPaginationModel.objects.create(created=idx)

        self.queryset = CursorPaginationModel.objects.values()

    def get_pages(self, url):
        """
        Given a URL return a tuple of:

        (previous page, current page, next page, previous url, next url)
        """
        request = Request(factory.get(url))
        queryset = self.pagination.paginate_queryset(self.queryset, request)
        current = [item['created'] for item in queryset]

        next_url = self.pagination.get_next_link()
        previous_url = self.pagination.get_previous_link()

        if next_url is not None:
            request = Request(factory.get(next_url))
            queryset = self.pagination.paginate_queryset(self.queryset, request)
            next = [item['created'] for item in queryset]
        else:
            next = None

        if previous_url is not None:
            request = Request(factory.get(previous_url))
            queryset = self.pagination.paginate_queryset(self.queryset, request)
            previous = [item['created'] for item in queryset]
        else:
            previous = None

        return (previous, current, next, previous_url, next_url)


class CompositeCursorPaginationTestsMixin:
    """
    Shared tests for composite cursor pagination against a real database.
    Subclasses run the same tests against model instances (using the `pk`
    alias) and against `.values()` dictionaries (using the concrete `id`
    field name).
    """

    page_size = 3

    # Rows as `(category, created)` tuples, in insertion order.
    rows = [
        ('b', 40),
        ('a', 10),
        ('a', 20),
        ('c', 5),
        ('b', 10),
        ('a', 20),
        ('c', 15),
        ('a', 30),
        ('b', 10),
    ]

    # Expected order: category asc, created desc, primary key asc.
    ordered_ids = [8, 3, 6, 2, 1, 5, 9, 7, 4]

    def setUp(self):
        for category, created in self.rows:
            CursorPaginationCompositeModel.objects.create(
                category=category, created=created
            )

    def get_queryset(self):
        raise NotImplementedError

    def item_id(self, item):
        raise NotImplementedError

    def paginate(self, url):
        request = Request(factory.get(url))
        page = self.pagination.paginate_queryset(self.get_queryset(), request)
        return (
            [self.item_id(item) for item in page],
            self.pagination.get_next_link(),
            self.pagination.get_previous_link(),
        )

    def get_pages(self, url):
        current, next_url, previous_url = self.paginate(url)
        next_page = self.paginate(next_url)[0] if next_url is not None else None
        previous_page = self.paginate(previous_url)[0] if previous_url is not None else None
        return (previous_page, current, next_page, previous_url, next_url)

    def test_composite_pagination_forward(self):
        pages = []
        url = '/'
        while url is not None:
            page, url, _ = self.paginate(url)
            pages.append(page)

        assert pages == [
            self.ordered_ids[0:3],
            self.ordered_ids[3:6],
            self.ordered_ids[6:9],
        ]

    def test_composite_pagination_backward_and_direction_change(self):
        # Forward to the last page.
        (_, current, _, _, next_url) = self.get_pages('/')
        assert current == self.ordered_ids[0:3]
        (_, current, _, previous_url, next_url) = self.get_pages(next_url)
        assert current == self.ordered_ids[3:6]
        (previous, current, next_page, previous_url, next_url) = self.get_pages(next_url)
        assert current == self.ordered_ids[6:9]
        assert previous == self.ordered_ids[3:6]
        assert next_page is None

        # Walk backwards to the middle page, then the first page.
        (previous, current, next_page, previous_url, next_url) = self.get_pages(previous_url)
        assert previous == self.ordered_ids[0:3]
        assert current == self.ordered_ids[3:6]
        assert next_page == self.ordered_ids[6:9]
        (previous, current, next_page, previous_url, next_url) = self.get_pages(previous_url)
        assert previous is None
        assert current == self.ordered_ids[0:3]
        assert next_page == self.ordered_ids[3:6]

        # Changing direction again stays consistent.
        (previous, current, _, _, _) = self.get_pages(next_url)
        assert previous == self.ordered_ids[0:3]
        assert current == self.ordered_ids[3:6]

    def test_composite_pagination_with_concurrent_changes_forward(self):
        current, next_url, _ = self.paginate('/')
        assert current == [8, 3, 6]

        # Rows are inserted on both sides of the cursor, and deleted on
        # both sides too, before the next page is requested.
        # id=10 sorts *before* the cursor (newer within category 'a'),
        # id=11 sorts *after* the cursor (new category 'd').
        CursorPaginationCompositeModel.objects.create(category='a', created=25)
        CursorPaginationCompositeModel.objects.create(category='d', created=1)
        CursorPaginationCompositeModel.objects.filter(id=8).delete()  # already seen
        CursorPaginationCompositeModel.objects.filter(id=2).delete()  # after the cursor

        current, next_url, _ = self.paginate(next_url)
        assert current == [1, 5, 9]
        current, next_url, _ = self.paginate(next_url)
        assert current == [7, 4, 11]
        assert next_url is None

    def test_composite_pagination_with_concurrent_changes_backward(self):
        current, next_url, _ = self.paginate('/')
        assert current == [8, 3, 6]

        # Insertions and deletions located *before* the next page boundary,
        # i.e. in the region reached through the "previous" link.
        CursorPaginationCompositeModel.objects.create(category='a', created=35)  # id=10
        CursorPaginationCompositeModel.objects.filter(id=3).delete()

        current, _, previous_url = self.paginate(next_url)
        assert current == [2, 1, 5]

        # Paging backwards: the inserted row is reached, the deleted row is
        # gone, and nothing already shown on the current page is repeated.
        (_, previous_page, next_page, _, _) = self.get_pages(previous_url)
        assert previous_page == [10, 8, 6]
        assert next_page == [2, 1, 5]

    def test_invalid_composite_cursors(self):
        invalid_cursors = [
            b64encode(b'p=a&p=20').decode('ascii'),              # too few positions
            b64encode(b'p=1').decode('ascii'),                   # single-field cursor
            b64encode(b'p=a&p=20&p=6&p=x').decode('ascii'),      # too many positions
            b64encode(b'p=a&p=').decode('ascii'),                # incomplete position
            b64encode(b'p=a&p=notanint&p=1').decode('ascii'),    # non-numeric content
            b64encode(b'o=notanint').decode('ascii'),            # invalid offset
        ]
        for encoded in invalid_cursors:
            request = Request(factory.get('/', {'cursor': encoded}))
            with pytest.raises(exceptions.NotFound):
                self.pagination.paginate_queryset(self.get_queryset(), request)

    def test_composite_cursor_on_single_field_ordering_is_invalid(self):
        class SingleFieldPagination(pagination.CursorPagination):
            page_size = self.page_size
            ordering = 'created'

        paginator = SingleFieldPagination()
        encoded = b64encode(b'p=a&p=1').decode('ascii')
        request = Request(factory.get('/', {'cursor': encoded}))
        with pytest.raises(exceptions.NotFound):
            paginator.paginate_queryset(self.get_queryset(), request)


@pytest.mark.usefixtures("reset_sequences")
class TestCompositeCursorPagination(CompositeCursorPaginationTestsMixin, TestCase):
    """
    Composite cursor pagination for model instances, using the `pk`
    alias as the unique final ordering field.
    """

    def setUp(self):
        class ExamplePagination(pagination.CursorPagination):
            page_size = self.page_size
            ordering = ('category', '-created', 'pk')

        self.pagination = ExamplePagination()
        super().setUp()

    def get_queryset(self):
        return CursorPaginationCompositeModel.objects.all()

    def item_id(self, item):
        return item.pk


@pytest.mark.usefixtures("reset_sequences")
class TestCompositeCursorPaginationWithValueQueryset(CompositeCursorPaginationTestsMixin, TestCase):
    """
    Composite cursor pagination for `.values()` querysets, where rows are
    plain dictionaries. The concrete primary key field name (`id`) is
    used instead of the `pk` alias.
    """

    def setUp(self):
        class ExamplePagination(pagination.CursorPagination):
            page_size = self.page_size
            ordering = ('category', '-created', 'id')

        self.pagination = ExamplePagination()
        super().setUp()

    def get_queryset(self):
        return CursorPaginationCompositeModel.objects.values()

    def item_id(self, item):
        return item['id']


def test_get_displayed_page_numbers():
    """
    Test our contextual page display function.

    This determines which pages to display in a pagination control,
    given the current page and the last page.
    """
    displayed_page_numbers = pagination._get_displayed_page_numbers

    # At five pages or less, all pages are displayed, always.
    assert displayed_page_numbers(1, 5) == [1, 2, 3, 4, 5]
    assert displayed_page_numbers(2, 5) == [1, 2, 3, 4, 5]
    assert displayed_page_numbers(3, 5) == [1, 2, 3, 4, 5]
    assert displayed_page_numbers(4, 5) == [1, 2, 3, 4, 5]
    assert displayed_page_numbers(5, 5) == [1, 2, 3, 4, 5]

    # Between six and either pages we may have a single page break.
    assert displayed_page_numbers(1, 6) == [1, 2, 3, None, 6]
    assert displayed_page_numbers(2, 6) == [1, 2, 3, None, 6]
    assert displayed_page_numbers(3, 6) == [1, 2, 3, 4, 5, 6]
    assert displayed_page_numbers(4, 6) == [1, 2, 3, 4, 5, 6]
    assert displayed_page_numbers(5, 6) == [1, None, 4, 5, 6]
    assert displayed_page_numbers(6, 6) == [1, None, 4, 5, 6]

    assert displayed_page_numbers(1, 7) == [1, 2, 3, None, 7]
    assert displayed_page_numbers(2, 7) == [1, 2, 3, None, 7]
    assert displayed_page_numbers(3, 7) == [1, 2, 3, 4, None, 7]
    assert displayed_page_numbers(4, 7) == [1, 2, 3, 4, 5, 6, 7]
    assert displayed_page_numbers(5, 7) == [1, None, 4, 5, 6, 7]
    assert displayed_page_numbers(6, 7) == [1, None, 5, 6, 7]
    assert displayed_page_numbers(7, 7) == [1, None, 5, 6, 7]

    assert displayed_page_numbers(1, 8) == [1, 2, 3, None, 8]
    assert displayed_page_numbers(2, 8) == [1, 2, 3, None, 8]
    assert displayed_page_numbers(3, 8) == [1, 2, 3, 4, None, 8]
    assert displayed_page_numbers(4, 8) == [1, 2, 3, 4, 5, None, 8]
    assert displayed_page_numbers(5, 8) == [1, None, 4, 5, 6, 7, 8]
    assert displayed_page_numbers(6, 8) == [1, None, 5, 6, 7, 8]
    assert displayed_page_numbers(7, 8) == [1, None, 6, 7, 8]
    assert displayed_page_numbers(8, 8) == [1, None, 6, 7, 8]

    # At nine or more pages we may have two page breaks, one on each side.
    assert displayed_page_numbers(1, 9) == [1, 2, 3, None, 9]
    assert displayed_page_numbers(2, 9) == [1, 2, 3, None, 9]
    assert displayed_page_numbers(3, 9) == [1, 2, 3, 4, None, 9]
    assert displayed_page_numbers(4, 9) == [1, 2, 3, 4, 5, None, 9]
    assert displayed_page_numbers(5, 9) == [1, None, 4, 5, 6, None, 9]
    assert displayed_page_numbers(6, 9) == [1, None, 5, 6, 7, 8, 9]
    assert displayed_page_numbers(7, 9) == [1, None, 6, 7, 8, 9]
    assert displayed_page_numbers(8, 9) == [1, None, 7, 8, 9]
    assert displayed_page_numbers(9, 9) == [1, None, 7, 8, 9]
