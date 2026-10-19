import unittest

from backend.archivereader.htr_compare import normalize, paired_interval, score


class HtrComparisonTests(unittest.TestCase):
    def test_normalization_preserves_name_differences(self):
        self.assertEqual(normalize('  Joannes\nPaulus '), 'Joannes Paulus')
        self.assertEqual(normalize('e\u0301'), 'é')
        self.assertNotEqual(normalize('Šimek'), normalize('Simek'))
        self.assertGreater(score('Anna', 'Anua')['cer'], 0)

    def test_failure_cannot_improve_paired_comparison(self):
        rows = [
            {'id': 'one', 'source': 'page1', 'results': {'a': {'score': score('abc', 'abc')}, 'b': {'score': score('abc', 'axc')}}},
            {'id': 'two', 'source': 'page2', 'results': {'a': {'error': 'failed'}, 'b': {'score': score('abc', 'abc')}}},
        ]
        self.assertIsNone(paired_interval(rows, 'a', 'b'))
        rows[1]['results']['a'] = {'score': score('abc', 'abc')}
        interval = paired_interval(rows, 'a', 'b')
        self.assertEqual(interval['pages'], 2)
        self.assertAlmostEqual(interval['difference'], -1/6)

    def test_missing_reference_is_not_zero_error(self):
        self.assertIsNone(score('', 'invented')['cer'])
        self.assertEqual(score('abc', 'abc')['character_errors'], 0)


if __name__ == '__main__':
    unittest.main()
