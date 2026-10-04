"""Wake activation never executes tools and only admits a deliberate command."""
import unittest
from voice.wake import WakeGate


class WakeTests(unittest.TestCase):
    def test_supported_phrases_wake_and_extract_same_utterance_command(self):
        for text in ['Hey Jarvis, open Safari', 'wake up Jarvis open Safari', 'Jarvis, open Safari']:
            with self.subTest(text=text):
                gate = WakeGate('phrase')
                self.assertEqual(gate.accept_text(text, now=1), 'open Safari')
                self.assertIsNone(gate.accept_text('pause Spotify', now=2))

    def test_phrase_only_arms_next_command_then_rearms(self):
        gate = WakeGate('phrase')
        self.assertIsNone(gate.accept_text('Hey Jarvis', now=1))
        self.assertTrue(gate.is_armed(now=2))
        self.assertEqual(gate.accept_text('pause Spotify', now=3), 'pause Spotify')
        self.assertFalse(gate.is_armed(now=4))

    def test_background_and_embedded_wake_words_do_not_submit(self):
        gate = WakeGate('phrase')
        for text in ['open Safari', 'I was saying hey Jarvis to someone', 'do not wake up Jarvis', 'Jarvisian architecture']:
            self.assertIsNone(gate.accept_text(text, now=1))

    def test_wake_session_times_out_without_command(self):
        gate = WakeGate('phrase', timeout=10)
        gate.accept_text('wake up Jarvis', now=1)
        self.assertIsNone(gate.accept_text('open Safari', now=12))

    def test_two_separate_claps_arm_command_but_one_does_not(self):
        gate = WakeGate('clap')
        self.assertFalse(gate.observe_rms(.2, now=1))
        self.assertFalse(gate.observe_rms(0, now=1.06))
        self.assertFalse(gate.is_armed(now=1.1))
        self.assertTrue(gate.observe_rms(.2, now=1.3))
        self.assertEqual(gate.accept_text('open Safari', now=2), 'open Safari')
        self.assertIsNone(gate.accept_text('pause Spotify', now=3))

    def test_sustained_loud_noise_or_distant_claps_do_not_wake(self):
        gate = WakeGate('clap')
        for now in [1, 1.1, 1.3, 1.5]:
            self.assertFalse(gate.observe_rms(.2, now=now))
        gate.observe_rms(0, now=2)
        self.assertFalse(gate.observe_rms(.2, now=3))
        self.assertFalse(gate.is_armed(now=3.1))

    def test_combined_mode_accepts_phrases_and_claps(self):
        gate = WakeGate('phrase_or_clap')
        self.assertEqual(gate.accept_text('hey Jarvis pause Spotify', now=1), 'pause Spotify')
        gate.observe_rms(.2, now=2)
        gate.observe_rms(0, now=2.1)
        self.assertTrue(gate.observe_rms(.2, now=2.3))
        self.assertEqual(gate.accept_text('open Notes', now=3), 'open Notes')

    def test_always_mode_and_manual_toggle_behavior_do_not_require_wake_phrase(self):
        gate = WakeGate('always')
        self.assertEqual(gate.accept_text('open Safari', now=1), 'open Safari')
        self.assertEqual(gate.accept_text('pause Spotify', now=2), 'pause Spotify')

    def test_mode_change_clears_pending_wake_and_invalid_mode_is_rejected(self):
        gate = WakeGate('phrase')
        gate.accept_text('hey Jarvis', now=1)
        gate.set_mode('clap')
        self.assertIsNone(gate.accept_text('open Safari', now=2))
        with self.assertRaises(ValueError):
            gate.set_mode('unsupported')


if __name__ == '__main__':
    unittest.main()
