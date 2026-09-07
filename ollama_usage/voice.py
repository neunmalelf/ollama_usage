"""voice - cross-platform text-to-speech for usage-reset announcements.

Mirrors the backend design of ddpico's ``speech`` module: high-quality neural
engines first (Kokoro ONNX, Microsoft Edge-TTS), then the platform natives
(macOS ``say``, Windows PowerShell SAPI), then Python ``pyttsx3``, then the
Linux CLI tools (``spd-say``, ``espeak-ng``, ``espeak``, ``festival``).

No special hardware is required - any machine with speakers or headphones
works; the synthesis itself is pure software.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from typing import Any

# Default URLs for the optional Kokoro ONNX model and voices.
KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin"


def _find_kokoro_model_files() -> tuple[str, str] | None:
    """Return (model_path, voices_path) for a local Kokoro ONNX install, or None."""
    env_model = os.environ.get("KOKORO_MODEL_PATH")
    env_voices = os.environ.get("KOKORO_VOICES_PATH")
    if env_model and env_voices and os.path.isfile(env_model) and os.path.isfile(env_voices):
        return (env_model, env_voices)

    search_dirs = [
        os.path.expanduser("~/.cache/kokoro"),
        os.path.expanduser("~/.config/ollama_usage/models/kokoro"),
        os.path.abspath("./models/kokoro"),
        os.path.abspath("."),
    ]
    for d in search_dirs:
        for model_name in ("kokoro-v0_19.onnx", "kokoro-v1_0.onnx"):
            model_p = os.path.join(d, model_name)
            for voices_name in ("voices.bin", "voices.json"):
                voices_p = os.path.join(d, voices_name)
                if os.path.isfile(model_p) and os.path.isfile(voices_p):
                    return (model_p, voices_p)
    return None


def kokoro_ensure_models(target_dir: str = "") -> tuple[str, str]:
    """Download the Kokoro ONNX model and voices into TARGET_DIR.

    Defaults to ``~/.cache/kokoro``. Only needed for the optional high-quality
    Kokoro backend (``pip install kokoro-onnx`` first).
    """
    import urllib.request

    dest = target_dir or os.path.expanduser("~/.cache/kokoro")
    os.makedirs(dest, exist_ok=True)
    model_path = os.path.join(dest, "kokoro-v0_19.onnx")
    voices_path = os.path.join(dest, "voices.bin")

    if not os.path.isfile(model_path):
        print(f"[voice] downloading Kokoro ONNX model to {model_path}...", file=sys.stderr)
        urllib.request.urlretrieve(KOKORO_MODEL_URL, model_path)
    if not os.path.isfile(voices_path):
        print(f"[voice] downloading Kokoro voices to {voices_path}...", file=sys.stderr)
        urllib.request.urlretrieve(KOKORO_VOICES_URL, voices_path)
    return (model_path, voices_path)


def _play_media_file(path: str) -> bool:
    """Play an audio file (.mp3, .wav) with the platform's players."""
    # 1. Windows native / MSYS2
    if os.name == "nt" or sys.platform in ("win32", "cygwin", "msys"):
        if path.endswith(".wav"):
            try:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
                return True
            except Exception:
                pass
        if shutil.which("powershell"):
            clean_path = path.replace("'", "''")
            ps_cmd = (
                "Add-Type -AssemblyName PresentationCore; "
                f"$player = New-Object System.Windows.Media.MediaPlayer; "
                f"$player.Open([System.Uri]'{clean_path}'); "
                "$player.Play(); "
                "$t = 0; "
                "while (-not $player.NaturalDuration.HasTimeSpan -and $t -lt 60) "
                "{ Start-Sleep -Milliseconds 50; $t++ }; "
                "if ($player.NaturalDuration.HasTimeSpan) { "
                "while ($player.Position -lt $player.NaturalDuration.TimeSpan) "
                "{ Start-Sleep -Milliseconds 100 }; "
                "Start-Sleep -Milliseconds 400; "
                "} else { Start-Sleep -Milliseconds 3000 }; "
                "$player.Close();"
            )
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True)
            if res.returncode == 0:
                return True

    # 2. macOS native afplay
    if sys.platform == "darwin" and shutil.which("afplay"):
        return subprocess.run(["afplay", path], capture_output=True).returncode == 0

    # 3. Linux / POSIX audio players
    for player in ("mpv", "ffplay", "paplay", "pw-play", "play", "aplay"):
        if shutil.which(player):
            if player == "ffplay":
                cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
            elif player == "mpv":
                cmd = ["mpv", "--no-terminal", path]
            else:
                cmd = [player, path]
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                return True
    return False


def _play_audio_samples(samples: Any, sample_rate: int = 24000) -> bool:
    """Play raw float samples via sounddevice or a temporary WAV file."""
    try:
        import sounddevice as sd
        sd.play(samples, sample_rate)
        sd.wait()
        return True
    except Exception:
        pass

    try:
        import numpy as np
        if hasattr(samples, "dtype"):
            int16_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
            raw_bytes = int16_samples.tobytes()
        else:
            raw_bytes = b"".join(
                int(max(-32768, min(32767, s * 32767))).to_bytes(2, "little", signed=True)
                for s in samples
            )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav_path = tf.name
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(raw_bytes)
        played = _play_media_file(wav_path)
        with contextlib.suppress(OSError):
            os.remove(wav_path)
        return played
    except Exception:
        return False


def speech_say_kokoro(text: str, voice: str = "female", speed: float = 1.0) -> bool:
    """Speak TEXT with the high-quality Kokoro neural TTS model (optional)."""
    if not text:
        return False
    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        return False
    paths = _find_kokoro_model_files()
    if not paths:
        return False
    model_p, voices_p = paths

    voice_lower = str(voice).lower().strip()
    if voice_lower in ("female", "f", "woman", "girl"):
        target_voice = "af_sarah"
    elif voice_lower in ("male", "m", "david", "alex", "adam", "michael", "george", "man", "boy"):
        target_voice = "am_adam"
    else:
        target_voice = voice

    try:
        kokoro_instance = Kokoro(model_p, voices_p)
        samples, sample_rate = kokoro_instance.create(text, voice=target_voice, speed=speed)
        return _play_audio_samples(samples, sample_rate)
    except Exception:
        return False


def speech_say_edge(text: str, voice: str = "female") -> bool:
    """Speak TEXT with Microsoft Edge's neural voice service (optional)."""
    if not text:
        return False
    voice_lower = str(voice).lower().strip()
    if voice_lower in ("female", "f", "woman", "girl"):
        target_voice = "en-US-JennyNeural"
    elif voice_lower in ("male", "m", "guy", "christopher", "ryan", "man", "boy", "david", "alex"):
        target_voice = "en-US-GuyNeural"
    elif "-" in voice:
        target_voice = voice
    else:
        target_voice = "en-US-JennyNeural"

    # 1. edge-tts CLI tool
    if shutil.which("edge-tts"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                mp3_path = tf.name
            cmd = ["edge-tts", "--voice", target_voice, "--text", text, "--write-media", mp3_path]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode == 0 and os.path.isfile(mp3_path):
                _play_media_file(mp3_path)
                with contextlib.suppress(OSError):
                    os.remove(mp3_path)
                return True
        except Exception:
            pass

    # 2. edge_tts python library
    try:
        import edge_tts

        async def _synthesize() -> str:
            communicate = edge_tts.Communicate(text, target_voice)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                mp3_path = tf.name
            await communicate.save(mp3_path)
            return mp3_path

        loop = asyncio.new_event_loop()
        mp3_file = loop.run_until_complete(_synthesize())
        loop.close()
        if mp3_file and os.path.isfile(mp3_file):
            _play_media_file(mp3_file)
            with contextlib.suppress(OSError):
                os.remove(mp3_file)
            return True
    except Exception:
        pass
    return False


def _detect_speech_backend() -> str | None:
    """Return the best speech backend available on this system, or None."""
    # 0. Kokoro TTS (high quality neural voice if installed & models found)
    try:
        import kokoro_onnx  # noqa: F401
        if _find_kokoro_model_files():
            return "kokoro"
    except ImportError:
        pass

    # 1. Edge-TTS (studio quality neural voice if installed)
    if shutil.which("edge-tts"):
        return "edge-tts"
    try:
        import edge_tts  # noqa: F401
        return "edge-tts"
    except ImportError:
        pass

    # 2. macOS native `say` command
    if sys.platform == "darwin" and shutil.which("say"):
        return "say"

    # 3. Windows PowerShell SAPI (David / Zira Desktop voices)
    if (os.name == "nt" or sys.platform in ("win32", "cygwin", "msys")) and shutil.which("powershell"):
        return "powershell"

    # 4. Python pyttsx3 library
    try:
        import pyttsx3  # noqa: F401
        return "pyttsx3"
    except ImportError:
        pass

    # 5. Linux / POSIX CLI tools (fallback)
    for tool in ("spd-say", "espeak-ng", "espeak", "festival"):
        if shutil.which(tool):
            return tool
    return None


def speech_backends() -> list[str]:
    """List all speech backends detected on the current system."""
    available: list[str] = []
    try:
        import kokoro_onnx  # noqa: F401
        if _find_kokoro_model_files():
            available.append("kokoro")
    except ImportError:
        pass
    if shutil.which("edge-tts"):
        available.append("edge-tts")
    else:
        try:
            import edge_tts  # noqa: F401
            available.append("edge-tts")
        except ImportError:
            pass
    if sys.platform == "darwin" and shutil.which("say"):
        available.append("say")
    if (os.name == "nt" or sys.platform in ("win32", "cygwin", "msys")) and shutil.which("powershell"):
        available.append("powershell")
    try:
        import pyttsx3  # noqa: F401
        available.append("pyttsx3")
    except ImportError:
        pass
    for tool in ("spd-say", "espeak-ng", "espeak", "festival"):
        if shutil.which(tool):
            available.append(tool)
    return available


def speak(text: str, voice: str = "female", rate: int = 160, backend: str = "") -> bool:
    """Speak TEXT aloud using the best available backend.

    Returns True when the announcement was spoken, False when no speech
    engine is available or synthesis failed.
    """
    if not text:
        return False

    chosen_backend = backend or _detect_speech_backend()
    if not chosen_backend:
        return False

    voice_lower = str(voice).lower().strip()
    is_male = voice_lower in ("male", "m", "david", "alex", "adam", "michael", "george", "guy", "man", "boy")

    try:
        if chosen_backend == "kokoro":
            speed_val = max(0.5, min(2.0, rate / 160.0))
            if speech_say_kokoro(text, voice=voice, speed=speed_val):
                return True

        if chosen_backend == "edge-tts" and speech_say_edge(text, voice=voice):
            return True

        if chosen_backend == "say":
            target_voice = "Alex" if is_male else "Samantha"
            return subprocess.run(
                ["say", "-v", target_voice, "-r", str(rate), text], capture_output=True
            ).returncode == 0

        if chosen_backend == "powershell":
            voice_name = "Microsoft David Desktop" if is_male else "Microsoft Zira Desktop"
            safe_text = text.replace("'", "''")
            ps_script = (
                f"Add-Type -AssemblyName System.Speech; "
                f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"try {{ $synth.SelectVoice('{voice_name}') }} catch {{ }}; "
                f"$synth.Rate = {max(-10, min(10, int((rate - 160) / 20)))}; "
                f"$synth.Speak('{safe_text}');"
            )
            return subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script], capture_output=True
            ).returncode == 0

        if chosen_backend == "pyttsx3":
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", rate)
            voices = engine.getProperty("voices")
            selected_voice = None
            if voices:
                for v in voices:
                    v_name = str(getattr(v, "name", "")).lower()
                    v_gender = str(getattr(v, "gender", "")).lower()
                    if is_male and any(k in v_gender or k in v_name for k in ("male", "david", "alex")):
                        selected_voice = v.id
                        break
                    if not is_male and any(k in v_gender or k in v_name for k in ("female", "zira", "samantha")):
                        selected_voice = v.id
                        break
            if selected_voice:
                engine.setProperty("voice", selected_voice)
            engine.say(text)
            engine.runAndWait()
            return True

        if chosen_backend == "spd-say":
            return subprocess.run(["spd-say", "-r", str(rate), text], capture_output=True).returncode == 0

        if chosen_backend == "espeak-ng":
            return subprocess.run(
                ["espeak-ng", "-s", str(rate), text], capture_output=True
            ).returncode == 0

        if chosen_backend == "espeak":
            return subprocess.run(
                ["espeak", "-s", str(rate), text], capture_output=True
            ).returncode == 0

        if chosen_backend == "festival":
            return subprocess.run(
                ["festival", "--tts"], input=text.encode(), capture_output=True
            ).returncode == 0
    except Exception:
        return False
    return False


def speak_async(text: str, voice: str = "female", rate: int = 160, backend: str = "") -> None:
    """Speak TEXT in a daemon thread so the caller never blocks."""
    threading.Thread(
        target=speak, args=(text, voice, rate, backend), daemon=True, name="ollama-voice"
    ).start()