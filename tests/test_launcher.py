import unittest
from unittest.mock import patch, MagicMock
from scripts.local import existing_console


class LauncherTests(unittest.TestCase):
    def test_old_api_without_console_is_not_reused(self):
        with patch('scripts.local.httpx.Client') as cls:
            client = cls.return_value.__enter__.return_value
            client.get.return_value.json.return_value = {'info': {'title': 'FedHELM edge coordination'}, 'paths': {}}
            self.assertFalse(existing_console(8000))

    def test_reuses_only_fully_online_console(self):
        spec = {'info': {'title':'FedHELM 中文控制台'}, 'paths': {'/ui/command': {}}}
        for online in [True, False]:
            with self.subTest(online=online), patch('scripts.local.httpx.Client') as cls:
                client = cls.return_value.__enter__.return_value
                responses = [MagicMock(), MagicMock()]
                responses[0].json.return_value = spec
                responses[1].json.return_value = {'services': {str(i): {'online': online} for i in range(9)}}
                client.get.side_effect = responses
                self.assertEqual(existing_console(9000), online)
