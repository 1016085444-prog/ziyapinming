"""技术指标：用能手算的小序列核对口径（另在开发时与 stockstats 逐值比对过，误差 < 1e-9）。"""

import unittest

import helpers  # noqa: F401
from quant import indicators as ind


class IndicatorTest(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(ind.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_seeds_with_first_value(self):
        # α = 2/(3+1) = 0.5
        self.assertEqual(ind.ema([2, 4, 8], 3), [2, 3.0, 5.5])

    def test_macd_histogram_is_double_difference(self):
        closes = [10 + (i % 7) * 0.3 + i * 0.05 for i in range(80)]
        dif, dea, hist = ind.macd(closes)
        self.assertTrue(all(v is None for v in dif[:26]))
        for d, e, h in zip(dif[26:], dea[26:], hist[26:]):
            self.assertAlmostEqual(h, 2 * (d - e))

    def test_rsi_extremes_and_wilder_smoothing(self):
        self.assertEqual(ind.rsi(list(range(1, 30)), 14)[-1], 100.0)
        self.assertEqual(ind.rsi(list(range(30, 1, -1)), 14)[-1], 0.0)
        self.assertEqual(ind.rsi([5.0] * 20, 14)[-1], 50.0)
        # 手算：涨跌交替 +2 / -1，n=2 → 平滑后 RSI 在 50 以上
        seq = [10, 12, 11, 13, 12, 14]
        r = ind.rsi(seq, 2)
        self.assertIsNone(r[1])
        gain, loss = 2, 0
        for diff in (-1, 2, -1, 2):
            gain = (max(diff, 0) + gain) / 2
            loss = (max(-diff, 0) + loss) / 2
        self.assertAlmostEqual(r[-1], 100 * gain / (gain + loss))

    def test_kdj_starts_at_50_and_tracks_rsv(self):
        highs = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        lows = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18]
        closes = [9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 19]
        k, d, j = ind.kdj(highs, lows, closes)
        self.assertIsNone(k[7])
        rsv = (19 - 10) / (19 - 10) * 100
        k_exp = (2 * 50 + rsv) / 3
        d_exp = (2 * 50 + k_exp) / 3
        self.assertAlmostEqual(k[8], (2 * 50 + (17.5 - 9) / (18 - 9) * 100) / 3)
        self.assertAlmostEqual(j[8], 3 * k[8] - 2 * d[8])
        self.assertGreater(k[9], k[8])
        self.assertTrue(k_exp > 50 and d_exp > 50)

    def test_boll_uses_sample_stdev(self):
        closes = [1, 2, 3, 4, 5]
        up, mid, low = ind.boll(closes, 5, 2)
        sd = ind.stdev(closes)
        self.assertAlmostEqual(sd, (2.5) ** 0.5)
        self.assertAlmostEqual(mid[-1], 3)
        self.assertAlmostEqual(up[-1] - mid[-1], 2 * sd)
        self.assertAlmostEqual(mid[-1] - low[-1], 2 * sd)

    def test_atr_true_range_with_gaps(self):
        highs, lows, closes = [10, 12, 9], [9, 11, 8], [9.5, 11.5, 8.5]
        a = ind.atr(highs, lows, closes, 2)
        tr = [1, max(1, 12 - 9.5, 11 - 9.5), max(1, abs(9 - 11.5), abs(8 - 11.5))]
        self.assertAlmostEqual(a[1], (tr[1] + tr[0]) / 2)
        self.assertAlmostEqual(a[2], (tr[2] + a[1]) / 2)

    def test_obv_and_volume_ratio(self):
        self.assertEqual(ind.obv([1, 2, 2, 1], [10, 20, 30, 40]), [0, 20, 20, -20])
        self.assertAlmostEqual(ind.volume_ratio([10, 10, 10, 10, 10, 30]), 3.0)
        self.assertIsNone(ind.volume_ratio([1, 2]))

    def test_swing_levels(self):
        highs = [1, 2, 3, 9, 3, 2, 1, 2, 3, 2, 1, 1]
        lows = [h - 0.5 for h in highs]
        peaks, troughs = ind.swing_levels(highs, lows, window=2, lookback=50)
        self.assertIn((3, 9), peaks)
        self.assertTrue(any(i == 6 for i, _ in troughs))


if __name__ == "__main__":
    unittest.main()
