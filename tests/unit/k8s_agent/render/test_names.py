from __future__ import annotations

import unittest

from k8s_agent.render.names import dns_label, resource_name


class RenderNameTests(unittest.TestCase):
    def test_dns_label_normalizes_and_truncates(self):
        self.assertEqual(dns_label("API_Service!!"), "api-service")
        self.assertEqual(len(dns_label("a" * 100)), 63)
        self.assertEqual(dns_label("---API---"), "api")

    def test_resource_name_includes_component_and_suffix(self):
        self.assertEqual(resource_name("Frontend/API", "svc"), "frontend-api-svc")


if __name__ == "__main__":
    unittest.main()
