import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from apps.accounts.middleware import LoginRequiredMiddleware
from apps.core.views import model_node_glb


class ModelGeometryAuthTests(SimpleTestCase):
    def test_expired_session_returns_json_without_redirect_or_html(self):
        for url in ['/model-node/13212.glb', '/model-review/']:
            request = RequestFactory().get(url)
            request.user = SimpleNamespace(is_authenticated=False)
            response = LoginRequiredMiddleware(lambda request: HttpResponse('unexpected'))(request)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(json.loads(response.content)['error'], 'authentication_required')
            self.assertNotIn('Location', response)
            self.assertIn('no-store', response['Cache-Control'])

    def test_geometry_view_enforces_auth_even_without_middleware(self):
        request = RequestFactory().get('/model-node/1.glb')
        request.user = SimpleNamespace(is_authenticated=False)
        with patch('apps.core.views.selection_glb_path') as generate:
            response = model_node_glb(request, 1)
        generate.assert_not_called()
        self.assertEqual(response.status_code, 401)

    def test_authenticated_geometry_response_remains_binary_and_uncached(self):
        request = RequestFactory().get('/model-node/1.glb')
        request.user = SimpleNamespace(is_authenticated=True)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'test.glb'
            path.write_bytes(b'glTF-test-content')
            with patch('apps.core.views.selection_glb_path', return_value=path):
                response = model_node_glb(request, 1)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], 'model/gltf-binary')
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(b''.join(response.streaming_content), b'glTF-test-content')
                response.close()
