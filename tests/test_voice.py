"""Tests for ollama_usage.voice - TTS backend detection and dispatch."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from ollama_usage import voice as v


class TestBackendDetection:
    def test_none_when_nothing_available(self) -> None:
        with patch.object(v.shutil, "which", return_value=None), \
             patch.dict(sys.modules, {"kokoro_onnx": None, "edge_tts": None,
                                      "pyttsx3": None}):
            assert v._detect_speech_backend() is None

    def test_prefers_kokoro_when_installed_with_models(self) -> None:
        with patch.object(v, "_find_kokoro_model_files",
                         return_value=("m.onnx", "v.bin")), \
             patch.dict(sys.modules, {"kokoro_onnx": MagicMock()}):
            assert v._detect_speech_backend() == "kokoro"

    def test_prefers_edge_tts_over_cli_tools(self) -> None:
        with patch.object(v.shutil, "which", return_value=None), \
             patch.dict(sys.modules, {"kokoro_onnx": None, "edge_tts": MagicMock(),
                                      "pyttsx3": None}):
            assert v._detect_speech_backend() == "edge-tts"

    def test_linux_cli_fallback(self) -> None:
        def fake_which(tool):
            return f"/usr/bin/{tool}" if tool in ("spd-say", "espeak-ng") else None

        with patch.object(v.shutil, "which", side_effect=fake_which), \
             patch.dict(sys.modules, {"kokoro_onnx": None, "edge_tts": None,
                                      "pyttsx3": None}):
            assert v._detect_speech_backend() == "spd-say"


class TestSpeak:
    def test_empty_text_returns_false(self) -> None:
        assert v.speak("") is False

    def test_no_backend_returns_false(self) -> None:
        with patch.object(v, "_detect_speech_backend", return_value=None):
            assert v.speak("hello") is False

    def test_espeak_ng_dispatch(self) -> None:
        proc = MagicMock()
        proc.returncode = 0
        with patch.object(v, "_detect_speech_backend", return_value="espeak-ng"), \
             patch.object(v.subprocess, "run", return_value=proc) as run:
            assert v.speak("hello") is True
        run.assert_called_once()
        assert run.call_args.args[0][0] == "espeak-ng"

    def test_failed_synthesis_returns_false(self) -> None:
        proc = MagicMock()
        proc.returncode = 1
        with patch.object(v, "_detect_speech_backend", return_value="espeak-ng"), \
             patch.object(v.subprocess, "run", return_value=proc):
            assert v.speak("hello") is False

    def test_speak_async_spawns_daemon_thread(self) -> None:
        with patch.object(v.threading, "Thread") as thread_cls:
            v.speak_async("hello")
        thread_cls.assert_called_once()
        assert thread_cls.call_args.kwargs["daemon"] is True


class TestBackendsList:
    def test_lists_available(self) -> None:
        def fake_which(tool):
            return f"/usr/bin/{tool}" if tool in ("espeak-ng", "festival") else None

        with patch.object(v.shutil, "which", side_effect=fake_which), \
             patch.dict(sys.modules, {"kokoro_onnx": None, "edge_tts": None,
                                      "pyttsx3": None}):
            assert v.speech_backends() == ["espeak-ng", "festival"]


class TestKokoroModels:
    def test_ensure_models_downloads_missing(self, tmp_path) -> None:
        with patch("urllib.request.urlretrieve") as dl:
            model, voices = v.kokoro_ensure_models(str(tmp_path))
        assert dl.call_count == 2
        assert model == str(tmp_path / "kokoro-v0_19.onnx")
        assert voices == str(tmp_path / "voices.bin")

    def test_ensure_models_skips_existing(self, tmp_path) -> None:
        (tmp_path / "kokoro-v0_19.onnx").write_bytes(b"m")
        (tmp_path / "voices.bin").write_bytes(b"v")
        with patch("urllib.request.urlretrieve") as dl:
            v.kokoro_ensure_models(str(tmp_path))
        dl.assert_not_called()