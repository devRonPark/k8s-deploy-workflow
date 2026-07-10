import unittest

from preanalyzer.analyzer.parsers.compose import _parse_long_port, _parse_short_port


class ComposeShortPortTests(unittest.TestCase):
    def test_simple_host_container(self):
        port = _parse_short_port("8080:80")
        self.assertEqual((port.host_port, port.container_port), (8080, 80))
        self.assertTrue(port.resolved)
        self.assertIsNone(port.warning)

    def test_container_only(self):
        port = _parse_short_port("80")
        self.assertIsNone(port.host_port)
        self.assertEqual(port.container_port, 80)
        self.assertTrue(port.resolved)

    def test_host_ip(self):
        port = _parse_short_port("127.0.0.1:8080:80")
        self.assertEqual(port.host_ip, "127.0.0.1")
        self.assertEqual((port.host_port, port.container_port), (8080, 80))

    def test_ipv6_host_ip(self):
        port = _parse_short_port("[::1]:8080:80")
        self.assertEqual(port.host_ip, "::1")
        self.assertEqual((port.host_port, port.container_port), (8080, 80))

    def test_protocol(self):
        port = _parse_short_port("8080:80/tcp")
        self.assertEqual(port.protocol, "tcp")
        self.assertEqual(port.container_port, 80)

    def test_port_range_is_not_expanded(self):
        port = _parse_short_port("8000-8005:80-85")
        self.assertEqual(port.raw, "8000-8005:80-85")
        self.assertIsNone(port.host_port)
        self.assertIsNone(port.container_port)
        self.assertIsNotNone(port.warning)

    def test_interpolation_with_default_resolves(self):
        port = _parse_short_port("${HTTP_PORT:-8080}:80")
        self.assertEqual(port.host_port, 8080)
        self.assertEqual(port.resolution_source, "compose_default")
        self.assertTrue(port.resolved)

    def test_interpolation_without_default_is_unresolved(self):
        port = _parse_short_port("${HTTP_PORT}:80")
        self.assertIsNone(port.host_port)
        self.assertEqual(port.container_port, 80)
        self.assertFalse(port.resolved)
        self.assertIn("unresolved", port.warning)

    def test_unparsable_token_is_unresolved_not_raised(self):
        port = _parse_short_port("abc:80")
        self.assertIsNone(port.host_port)
        self.assertFalse(port.resolved)
        self.assertIn("unparsable", port.warning)


class ComposeLongPortTests(unittest.TestCase):
    def test_long_syntax_fields(self):
        port = _parse_long_port({"target": 9090, "published": 19090, "protocol": "udp"})
        self.assertEqual(port.container_port, 9090)
        self.assertEqual(port.host_port, 19090)
        self.assertEqual(port.protocol, "udp")
        self.assertTrue(port.resolved)

    def test_long_syntax_interpolated_published_is_unresolved(self):
        port = _parse_long_port({"target": 80, "published": "${PORT}"})
        self.assertEqual(port.container_port, 80)
        self.assertIsNone(port.host_port)
        self.assertFalse(port.resolved)


if __name__ == "__main__":
    unittest.main()
