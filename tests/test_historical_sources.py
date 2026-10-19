import hashlib
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'backend/archivereader/historical_sources.json'


class HistoricalSourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(CATALOG.read_text(encoding='utf8'))

    def test_bounded_unique_http_catalog_with_required_metadata(self):
        self.assertEqual(self.catalog['version'], 1)
        self.assertTrue(self.catalog['policy'])
        sources = self.catalog['sources']
        self.assertTrue(1 <= len(sources) <= 200)
        self.assertLess(CATALOG.stat().st_size, 1024 * 1024)
        self.assertEqual(len(sources), len({s['url'] for s in sources}))
        self.assertEqual(len(sources), len({s['id'] for s in sources}))
        for source in sources:
            self.assertEqual(source['id'], hashlib.sha256(source['url'].encode()).hexdigest()[:16])
            parsed = urlsplit(source['url'])
            self.assertIn(parsed.scheme, ['http', 'https'])
            self.assertTrue(parsed.hostname)
            self.assertIsNone(parsed.username)
            self.assertIsNone(parsed.password)
            for field in ['title', 'url', 'category', 'resource_type', 'scope', 'work_period',
                          'witness_period', 'edition_period', 'authenticity', 'verification']:
                self.assertIsInstance(source[field], str)
                self.assertLessEqual(len(source[field]), 4000)
            self.assertTrue(source['provenance'])

    def test_all_document_links_retained_with_literal_provenance(self):
        sources = {s['url']: s for s in self.catalog['sources']}
        for name in ['HISTORICAL_LEXICONS.uk.md', 'HISTORICAL_GRAMMARS.uk.md', 'GLOBAL_SOURCES.uk.md']:
            for line in (ROOT / 'docs' / name).read_text(encoding='utf8').splitlines():
                for _, url in re.findall(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', line):
                    self.assertIn(url, sources)
                    self.assertTrue(any(p['document'] == 'docs/' + name for p in sources[url]['provenance']))

    def test_catalog_never_confirms_rules_or_grants_training(self):
        for source in self.catalog['sources']:
            for field in ['checked', 'auto_apply', 'gt_eligible', 'training_eligible']:
                self.assertIs(source[field], False)
            self.assertNotIn('rules', source)
            self.assertNotIn('training_text', source)
        official = [s for s in self.catalog['sources'] if s['verification'].startswith('official_page_read:')]
        self.assertEqual(len(official), 5)
        self.assertTrue(all(s['category'] in ['paleography', 'abbreviation', 'transcription'] for s in official))

    def test_global_discovery_is_distinct_from_verified_dictionary_content(self):
        global_sources = [s for s in self.catalog['sources'] if any(
            p['document'] == 'docs/GLOBAL_SOURCES.uk.md' for p in s['provenance'])]
        self.assertGreaterEqual(len(global_sources), 12)
        for source in global_sources:
            self.assertEqual(source['languages'], [])
            self.assertEqual(source['scripts'], [])
            self.assertTrue(source['access_status'])
            self.assertNotIn('utm_', source['url'].lower())
            self.assertNotIn('460382', source['scope'].replace(',', ''))
        by_url = {s['url']: s for s in global_sources}
        self.assertEqual(by_url['https://glottolog.org/langdoc']['resource_type'], 'bibliography')
        self.assertEqual(by_url['https://wals.info/languoid']['resource_type'], 'language_catalog')
        self.assertEqual(by_url['https://search.language-archives.org/']['access_status'], 'javascript_shell_only')
        pdf = next(s for s in global_sources if 'upload.wikimedia.org' in s['url'])
        self.assertEqual(pdf['access_status'], 'user_provided_unverified_pdf')


if __name__ == '__main__':
    unittest.main()
