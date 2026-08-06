import unittest

from pinwatch import power
from pinwatch.power import CONNECTORS, Status


class TestConnectorSpec(unittest.TestCase):
    def test_12vhpwr_spec_current(self):
        conn = CONNECTORS["12vhpwr"]
        # 600 W / 12 V = 50 A over 6 pins
        self.assertAlmostEqual(conn.spec_pin_a, 50.0 / 6, places=6)
        self.assertAlmostEqual(conn.design_margin, 9.5 / (50.0 / 6), places=6)

    def test_2x6_is_electrically_identical(self):
        a, b = CONNECTORS["12vhpwr"], CONNECTORS["12v-2x6"]
        self.assertEqual((a.pins, a.pin_rating_a, a.rated_w), (b.pins, b.pin_rating_a, b.rated_w))


class TestCompute(unittest.TestCase):
    def test_ohms_law(self):
        load = power.compute(600.0)
        self.assertAlmostEqual(load.total_a, 50.0)
        self.assertAlmostEqual(load.ideal_pin_a, 50.0 / 6)
        self.assertAlmostEqual(load.pct_of_rated_w, 100.0)

    def test_slot_offset_reduces_connector_share(self):
        load = power.compute(500.0, slot_w=60.0)
        self.assertAlmostEqual(load.connector_w, 440.0)
        self.assertAlmostEqual(load.total_a, 440.0 / 12.0)
        self.assertEqual(load.board_w, 500.0)

    def test_slot_offset_cannot_go_negative(self):
        load = power.compute(20.0, slot_w=75.0)
        self.assertEqual(load.connector_w, 0.0)
        self.assertEqual(load.total_a, 0.0)

    def test_non_nominal_voltage(self):
        load = power.compute(600.0, volts=11.4)
        self.assertAlmostEqual(load.total_a, 600.0 / 11.4)

    def test_default_share_is_perfect_balance(self):
        load = power.compute(400.0)
        self.assertTrue(load.balanced)
        self.assertAlmostEqual(load.worst_pin_a, load.ideal_pin_a)

    def test_imbalance_loads_one_pin(self):
        # 450 W = 37.5 A; a pin taking 40% carries 15 A, past the 9.5 A rating
        load = power.compute(450.0, share=0.40)
        self.assertAlmostEqual(load.worst_pin_a, 15.0)
        self.assertFalse(load.balanced)
        self.assertIs(load.status, Status.CRITICAL)

    def test_dissipation_is_i_squared_r(self):
        load = power.compute(600.0, share=0.5, contact_mohm=5.0)
        self.assertAlmostEqual(load.worst_pin_a, 25.0)
        self.assertAlmostEqual(load.worst_pin_w, 25.0**2 * 0.005)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            power.compute(100.0, volts=0)
        with self.assertRaises(ValueError):
            power.compute(100.0, share=1.5)
        with self.assertRaises(ValueError):
            power.compute(100.0, share=0)


class TestClassify(unittest.TestCase):
    conn = CONNECTORS["12vhpwr"]

    def test_bands(self):
        spec = self.conn.spec_pin_a  # 8.333 A
        cases = [
            (0.0, Status.NOMINAL),
            (spec * 0.59, Status.NOMINAL),
            (spec * 0.61, Status.ELEVATED),
            (spec * 0.999, Status.ELEVATED),
            (spec * 1.01, Status.HIGH),
            (9.49, Status.HIGH),
            (9.51, Status.CRITICAL),
        ]
        for amps, expected in cases:
            with self.subTest(amps=amps):
                self.assertIs(power.classify(amps, self.conn), expected)

    def test_600w_balanced_is_high_not_critical(self):
        # A 5090 pinned at its rating sits between spec load and terminal rating.
        self.assertIs(power.compute(600.0).status, Status.ELEVATED)
        self.assertIs(power.compute(601.0).status, Status.HIGH)

    def test_thresholds_track_the_connector(self):
        # 150 W on an 8-pin is its rated maximum, so it must not read as critical.
        self.assertIs(power.compute(150.0, conn=CONNECTORS["pcie8"]).status, Status.ELEVATED)
        self.assertIs(power.compute(300.0, conn=CONNECTORS["pcie8"]).status, Status.CRITICAL)


class TestSeriesDetection(unittest.TestCase):
    def test_matches(self):
        for name in ("NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 5070 Ti", "RTX 5050"):
            self.assertTrue(power.is_50_series(name), name)

    def test_rejects(self):
        for name in ("NVIDIA GeForce RTX 4090", "NVIDIA RTX 5000 Ada Generation",
                     "Quadro RTX 5000", "NVIDIA GeForce GTX 1050 Ti", "NVIDIA A100-SXM4"):
            self.assertFalse(power.is_50_series(name), name)


if __name__ == "__main__":
    unittest.main()
