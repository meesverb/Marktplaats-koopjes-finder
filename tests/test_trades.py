"""trades.py en de tabel `trade` (db.py, migratie 7): de eigen aan- en
verkopen van de eigenaar."""
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

import db
import trades as tr


class TradeTableTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = str(self.dir / "koopjes.db")
        self.conn = db.connect(self.path)
        self.addCleanup(self.conn.close)

    def test_buy_sell_unsell_delete(self):
        tid = db.add_trade(self.conn, title="Garmin Edge 530", bought_at="2026-09-01", buy_price_eur=110.0,
                           model="Garmin Edge 530", expected_resale_eur=149.0, item_id="m1", url="https://x/m1")
        self.assertTrue(db.sell_trade(self.conn, tid, sold_at="2026-09-15", sell_price_eur=150.0,
                                      sell_costs_eur=3.0, sold_via="marktplaats"))
        (row,) = db.list_trades(self.conn)
        self.assertEqual((row["sell_price_eur"], row["sold_via"]), (150.0, "marktplaats"))
        self.assertTrue(db.unsell_trade(self.conn, tid))
        self.assertIsNone(db.list_trades(self.conn)[0]["sold_at"])
        self.assertTrue(db.delete_trade(self.conn, tid))
        self.assertEqual(db.list_trades(self.conn), [])
        self.assertFalse(db.delete_trade(self.conn, tid))

    def test_load_trades_reads_without_writing(self):
        db.add_trade(self.conn, title="Roam", bought_at="2026-08-01", buy_price_eur=60.0)
        (trade,) = tr.load_trades(self.path)
        self.assertEqual(trade.title, "Roam")
        self.assertEqual(tr.load_trades(str(self.dir / "bestaat_niet.db")), [])


class ProgressTest(unittest.TestCase):
    def trade(self, **kw):
        base = dict(id=1, title="x", bought_at="2026-09-01", buy_price_eur=100.0)
        base.update(kw)
        return tr.Trade(**base)

    def test_profit_counts_every_cost(self):
        t = self.trade(buy_costs_eur=5.0, sold_at="2026-09-11", sell_price_eur=150.0, sell_costs_eur=3.0)
        self.assertEqual(t.profit_eur, 42.0)
        self.assertEqual(t.days_held(), 10)

    def test_progress(self):
        sold_a = self.trade(id=1, bought_at="2026-08-01", sold_at="2026-08-20", sell_price_eur=130.0, sell_costs_eur=3.0,
                            expected_resale_eur=120.0)
        sold_b = self.trade(id=2, bought_at="2026-09-01", sold_at="2026-09-05", sell_price_eur=90.0,
                            expected_resale_eur=100.0)
        stock_market = self.trade(id=3, model="Garmin Edge 530", buy_price_eur=110.0, expected_resale_eur=140.0)
        stock_guess = self.trade(id=4, model=None, buy_price_eur=50.0, expected_resale_eur=80.0)
        stock_unknown = self.trade(id=5, model=None, buy_price_eur=20.0)
        p = tr.progress([sold_a, sold_b, stock_market, stock_guess, stock_unknown],
                        {"Garmin Edge 530": 150.0}, shipping_eur=3.0)
        self.assertEqual(p.realized_profit_eur, 27.0 + -10.0)
        self.assertEqual([t.id for t in p.sold], [2, 1])  # latest sale first
        self.assertEqual(p.invested_in_stock_eur, 180.0)
        by_id = {s.trade.id: s for s in p.stock}
        self.assertEqual(by_id[3].expected_resale_eur, 150.0)  # today's market wins
        self.assertEqual(by_id[4].expected_resale_eur, 80.0)  # else what was expected at the buy
        self.assertIsNone(by_id[5].expected_profit_eur)
        self.assertEqual(p.expected_stock_profit_eur, (150 - 3 - 110) + (80 - 3 - 50))
        self.assertEqual(p.monthly, [("2026-08", 27.0), ("2026-09", -10.0)])
        self.assertAlmostEqual(p.estimate_error, ((130 - 120) / 120 + (90 - 100) / 100) / 2)
        self.assertEqual(p.avg_days_to_sell, (19 + 4) / 2)

    def test_open_trade_counts_days_until_today(self):
        t = self.trade(bought_at="2026-09-01")
        self.assertEqual(t.days_held(today=date(2026, 9, 28)), 27)


if __name__ == "__main__":
    unittest.main()
