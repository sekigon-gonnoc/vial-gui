import unittest
import lzma
import struct


from keyboard import Keyboard
from util import chunks

LAYOUT_2x2 = """
{"name":"test","vendorId":"0x0000","productId":"0x1111","lighting":"none","matrix":{"rows":2,"cols":2},"layouts":{"keymap":[["0,0","0,1"],["1,0","1,1"]]}}
"""

LAYOUT_ENCODER = r"""
{"name":"test","vendorId":"0x0000","productId":"0x1111","lighting":"none","matrix":{"rows":1,"cols":1},"layouts":{"keymap":[["0,0\n\n\n\n\n\n\n\n\ne","0,1\n\n\n\n\n\n\n\n\ne"],["0,0"]]}}
"""


class SimulatedDevice:

    def __init__(self):
        # sequence of keyboard communications, pairs of (request, response)
        self.expect_data = []
        # current index in communications
        self.expect_idx = 0

    def expect(self, inp, out):
        if isinstance(inp, str):
            inp = bytes.fromhex(inp)
        if isinstance(out, str):
            out = bytes.fromhex(out)
        self.expect_data.append((inp, out))

    def expect_keyboard_id(self, kbid):
        self.expect("FE00", struct.pack("<IQ", 0, kbid))

    def expect_layout(self, layout):
        compressed = lzma.compress(layout.encode("utf-8"))
        self.expect("FE01", struct.pack("<I", len(compressed)))
        for idx, chunk in enumerate(chunks(compressed, 32)):
            self.expect(
                struct.pack("<BBI", 0xFE, 0x02, idx),
                chunk
            )

    def expect_layers(self, layers):
        self.expect("11", struct.pack("BB", 0x11, layers))

    def expect_keymap(self, keymap):
        for l, layer in enumerate(keymap):
            for r, row in enumerate(layer):
                for c, col in enumerate(row):
                    self.expect(struct.pack("BBBB", 4, l, r, c), struct.pack(">BBBBH", 4, l, r, c, col))

    def expect_encoders(self, encoders):
        for l, layer in enumerate(encoders):
            for e, enc in enumerate(layer):
                self.expect(struct.pack("BBBB", 0xFE, 3, l, e), struct.pack(">HH", enc[0], enc[1]))

    @staticmethod
    def sim_send(dev, data):
        if dev.expect_idx >= len(dev.expect_data):
            raise Exception("Trying to communicate more times ({}) than expected ({}); got data={}".format(
                dev.expect_idx + 1,
                len(dev.expect_data),
                data.hex()
            ))
        inp, out = dev.expect_data[dev.expect_idx]
        if data != inp:
            raise Exception("Got unexpected data at index {}: expected={} with result={} got={}".format(
                dev.expect_idx,
                inp.hex(),
                out.hex(),
                data.hex()
            ))
        dev.expect_idx += 1
        return out

    def finish(self):
        if self.expect_idx != len(self.expect_data):
            raise Exception("Didn't communicate all the way, remaining data = {}".format(
                self.expect_data[self.expect_idx:]
            ))


class TestKeyboard(unittest.TestCase):

    @staticmethod
    def prepare_keyboard(layout, keymap, encoders=None):
        dev = SimulatedDevice()
        dev.expect_keyboard_id(0)
        dev.expect_layout(layout)
        dev.expect_layers(len(keymap))
        dev.expect_keymap(keymap)
        if encoders is not None:
            dev.expect_encoders(encoders)
        # layout options
        dev.expect("0202", "020200000000")

        kb = Keyboard(dev, dev.sim_send)
        # simulate old VIA keymap retrieval in tests for now
        kb.sideload = True
        kb.reload()

        return kb, dev

    def test_keyboard_layout(self):
        """ Tests that loading a layout from a keyboard works """

        kb, dev = self.prepare_keyboard(LAYOUT_2x2, [[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        self.assertEqual(kb.layers, 2)
        self.assertEqual(kb.layout[(0, 0, 0)], 1)
        self.assertEqual(kb.layout[(0, 0, 1)], 2)
        self.assertEqual(kb.layout[(0, 1, 0)], 3)
        self.assertEqual(kb.layout[(0, 1, 1)], 4)
        self.assertEqual(kb.layout[(1, 0, 0)], 5)
        self.assertEqual(kb.layout[(1, 0, 1)], 6)
        self.assertEqual(kb.layout[(1, 1, 0)], 7)
        self.assertEqual(kb.layout[(1, 1, 1)], 8)
        dev.finish()

    def test_set_key(self):
        """ Tests that setting a key works """

        kb, dev = self.prepare_keyboard(LAYOUT_2x2, [[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        dev.expect("050101000009", "")
        kb.set_key(1, 1, 0, 9)
        self.assertEqual(kb.layout[(1, 1, 0)], 9)

        dev.finish()

    def test_set_key_twice(self):
        """ Tests that setting a key twice is optimized (doesn't send 2 cmds) """

        kb, dev = self.prepare_keyboard(LAYOUT_2x2, [[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        dev.expect("050101000009", "")
        kb.set_key(1, 1, 0, 9)
        kb.set_key(1, 1, 0, 9)
        self.assertEqual(kb.layout[(1, 1, 0)], 9)

        dev.finish()

    def test_layout_save_restore(self):
        """ Tests that layout saving and restore works """

        kb, dev = self.prepare_keyboard(LAYOUT_2x2, [[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        dev.expect("05010100000A", "")
        kb.set_key(1, 1, 0, 10)
        self.assertEqual(kb.layout[(1, 1, 0)], 10)
        data = kb.save_layout()
        dev.finish()

        kb, dev = self.prepare_keyboard(LAYOUT_2x2, [[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        dev.expect("05010100000A", "")
        kb.restore_layout(data)
        self.assertEqual(kb.layout[(1, 1, 0)], 10)
        dev.finish()

    def test_encoder_simple(self):
        """ Tests that we try to retrieve encoder layout """

        kb, dev = self.prepare_keyboard(LAYOUT_ENCODER, [[[1]], [[2]], [[3]], [[4]]], [[(10, 11)], [(12, 13)], [(14, 15)], [(16, 17)]])
        self.assertEqual(kb.encoder_layout[(0, 0, 0)], 10)
        self.assertEqual(kb.encoder_layout[(0, 0, 1)], 11)
        self.assertEqual(kb.encoder_layout[(1, 0, 0)], 12)
        self.assertEqual(kb.encoder_layout[(1, 0, 1)], 13)
        self.assertEqual(kb.encoder_layout[(2, 0, 0)], 14)
        self.assertEqual(kb.encoder_layout[(2, 0, 1)], 15)
        self.assertEqual(kb.encoder_layout[(3, 0, 0)], 16)
        self.assertEqual(kb.encoder_layout[(3, 0, 1)], 17)
        dev.finish()

    def test_encoder_change(self):
        """ Test that changing encoder works """

        kb, dev = self.prepare_keyboard(LAYOUT_ENCODER, [[[1]], [[2]], [[3]], [[4]]], [[(10, 11)], [(12, 13)], [(14, 15)], [(16, 17)]])
        self.assertEqual(kb.encoder_layout[(1, 0, 0)], 12)
        self.assertEqual(kb.encoder_layout[(1, 0, 1)], 13)
        dev.expect("FE040100010020", "")
        kb.set_encoder(1, 0, 1, 0x20)
        self.assertEqual(kb.encoder_layout[(1, 0, 1)], 0x20)
