"""Laya System 1 selects only explicit, allowlisted single desktop commands."""
import unittest
from unittest.mock import Mock, patch

from agent.reactive import ReactiveRouter


def prediction(choice, probability=.98):
    return {'answers': {'action': {'choice': choice, 'probabilities': {choice: probability}, 'answer_confidence': probability}}}


class ReactiveTests(unittest.TestCase):
    def router(self, choice='spotify_pause', probability=.98):
        backend = Mock()
        backend.predict.return_value = prediction(choice, probability)
        return ReactiveRouter(backend=backend), backend

    def test_short_spotify_command_uses_real_router_schema(self):
        router, backend = self.router()
        action = router.decide('Jarvis, pause Spotify please.')
        self.assertEqual(action, {'tool': 'spotify_playback', 'args': {'action': 'pause'}, 'reply': 'Spotify paused.'})
        text, questions = backend.predict.call_args.args
        self.assertEqual(text, 'Jarvis, pause Spotify please.')
        self.assertEqual(questions['action']['type'], 'choice')
        self.assertIn('process', questions['action']['criteria'])

    def test_installed_apps_open_immediately_without_loading_a_decision_model(self):
        backend = Mock()
        backend.predict.side_effect = AssertionError('Validated app launch should not wait for Laya')
        router = ReactiveRouter(backend=backend)
        with patch('agent.reactive.installed_apps', return_value=['Google Chrome', 'Safari', 'Terminal', 'Visual Studio Code']):
            for text, name in [('open chrome', 'Google Chrome'), ('Can you please open Google Chrome for me?', 'Google Chrome'), ('launch Terminal', 'Terminal'), ('open VS Code', 'Visual Studio Code')]:
                with self.subTest(text=text):
                    self.assertEqual(router.decide(text)['args'], {'app_name': name})
        backend.predict.assert_not_called()

    def test_installed_app_matching_rejects_negation_compound_and_unknown_names(self):
        backend = Mock()
        router = ReactiveRouter(backend=backend)
        with patch('agent.reactive.installed_apps', return_value=['Safari']):
            for text in ['do not open Safari', 'open Safari and delete files', 'open Safari; rm -rf /', 'open nonexistent app']:
                self.assertIsNone(router.decide(text))
        backend.predict.assert_not_called()

    def test_exact_app_open_uses_fixed_allowlisted_arguments(self):
        router, backend = self.router('open_safari')
        self.assertEqual(router.decide('open Safari')['args'], {'app_name': 'Safari'})

    def test_uncertain_wrong_or_process_decision_falls_back_without_action(self):
        for choice, probability in [('spotify_pause', .6), ('spotify_play', .99), ('process', .99), ('run_shell', .99)]:
            with self.subTest(choice=choice, probability=probability):
                router, backend = self.router(choice, probability)
                self.assertIsNone(router.decide('pause Spotify'))

    def test_general_ambiguous_negated_or_compound_requests_skip_reactive_model(self):
        for text in ['write a report', 'do not pause Spotify', 'pause Spotify then delete my files', 'play Bohemian Rhapsody on Spotify', 'play', 'open an app']:
            with self.subTest(text=text):
                router, backend = self.router()
                self.assertIsNone(router.decide(text))
                backend.predict.assert_not_called()

    def test_missing_or_broken_laya_falls_back_and_reports_unavailability(self):
        status = []
        backend = Mock()
        backend.predict.side_effect = RuntimeError('checkpoint unavailable')
        router = ReactiveRouter(backend=backend, on_status=lambda message: status.append(message))
        self.assertIsNone(router.decide('pause Spotify'))
        self.assertTrue(status)
        self.assertIn('fallback', status[-1].lower())

    def test_no_arbitrary_model_arguments_are_executed(self):
        router, backend = self.router()
        backend.predict.return_value['answers']['action']['args'] = {'action': 'delete', 'script': 'rm -rf /'}
        self.assertEqual(router.decide('pause Spotify')['args'], {'action': 'pause'})


if __name__ == '__main__':
    unittest.main()
