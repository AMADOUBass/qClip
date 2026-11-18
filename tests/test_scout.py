import numpy as np
import pytest

from qclip.chat import ChatMessage
from qclip.config import load_config
from qclip.scout import chat_series, combined_score, format_hms, moving_average, pick_windows, rolling_zscore


def test_rolling_zscore_flat_signal_is_zero() -> None:
    assert np.all(rolling_zscore(np.full(100, 5.0), window=20) == 0)


def test_rolling_zscore_spike_stands_out() -> None:
    x = np.random.default_rng(0).normal(0, 1, 2000)
    x[1000] = 15
    z = rolling_zscore(x, window=600)
    assert int(np.argmax(z)) == 1000
    assert z[1000] > 8


def test_moving_average_keeps_length() -> None:
    assert len(moving_average(np.arange(50.0), 5)) == 50


def test_chat_series_delay_and_emotes() -> None:
    messages = [
        ChatMessage(15.2, "KEKW"),  # réaction à t = 10 s (délai 5 s), emote → 1 + bonus
        ChatMessage(15.9, "mdr t'es nul"),  # même seconde, sans emote → 1
        ChatMessage(30.0, "W"),
        ChatMessage(31.0, "Wesh"),  # « W » doit être un mot entier
        ChatMessage(40.0, "💀💀"),  # emoji en sous-chaîne
        ChatMessage(2.0, "trop tôt"),  # tomberait avant 0 → ignoré
    ]
    series = chat_series(messages, 60, ["KEKW", "W", "💀"], emote_bonus=2.0, delay=5.0)
    assert series[10] == 3 + 1
    assert series[25] == 3
    assert series[26] == 1
    assert series[35] == 3
    assert series.sum() == 3 + 1 + 3 + 1 + 3


def test_pick_windows_best_first_and_limited_overlap() -> None:
    score = np.zeros(1000)
    score[[200, 230, 600, 900]] = [10, 9, 8, 7]  # 230 est trop proche de 200
    windows = pick_windows(score, window_len=75, count=3)
    assert [w.rank for w in windows] == [1, 2, 3]
    assert [w.peak for w in windows] == [200, 600, 900]
    for a in windows:
        assert a.end - a.start == 75
        assert a.start <= a.peak <= a.end
        for b in windows:
            if a is not b:
                assert min(a.end, b.end) - max(a.start, b.start) <= 0.3 * 75


def test_pick_windows_stays_inside_video() -> None:
    score = np.zeros(300)
    score[2] = 5
    score[298] = 4
    windows = pick_windows(score, window_len=75, count=2)
    assert windows[0].start == 0
    assert windows[1].end == 300


def test_combined_score_prefers_chat_peak() -> None:
    config = load_config()
    rng = np.random.default_rng(1)
    loudness = rng.normal(-30, 1, 3600)
    chat = rng.poisson(2, 3600).astype(float)
    chat[1800:1810] += 40  # gros pic de chat
    score, z_chat, _ = combined_score(chat, loudness, config)
    assert 1795 <= int(np.argmax(score)) <= 1815
    assert z_chat.max() > 5


def test_combined_score_without_chat() -> None:
    loudness = np.full(1200, -30.0)
    loudness[600:605] = -5
    score, z_chat, _ = combined_score(None, loudness, load_config())
    assert np.all(z_chat == 0)
    assert 595 <= int(np.argmax(score)) <= 610


@pytest.mark.parametrize(("seconds", "text"), [(0, "0:00:00"), (75.9, "0:01:15"), (3 * 3600 + 62, "3:01:02")])
def test_format_hms(seconds: float, text: str) -> None:
    assert format_hms(seconds) == text
