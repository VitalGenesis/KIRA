from __future__ import annotations
import tempfile
from pathlib import Path

import config

_whisper=None

def is_available():
    try:
        import sounddevice, faster_whisper, pyttsx3
        return True
    except ImportError:
        return False


def _model():
    global _whisper
    if _whisper is not None: return _whisper
    from faster_whisper import WhisperModel
    name=__import__('os').getenv('KIRA_WHISPER_MODEL','base')
    device=__import__('os').getenv('KIRA_WHISPER_DEVICE','cuda' if _cuda_available() else 'cpu')
    compute=__import__('os').getenv('KIRA_WHISPER_COMPUTE_TYPE','float16' if device=='cuda' else 'int8')
    _whisper=WhisperModel(name,device=device,compute_type=compute)
    return _whisper


def _cuda_available():
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception: return False


def listen(seconds=5,language='es'):
    import sounddevice as sd
    import numpy as np
    import wave
    sr=16000; dur=max(1,min(float(seconds),30))
    audio=sd.rec(int(sr*dur),samplerate=sr,channels=1,dtype='float32'); sd.wait()
    with tempfile.NamedTemporaryFile(suffix='.wav',delete=False) as f: path=Path(f.name)
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((audio[:,0]*32767).astype(np.int16).tobytes())
    try:
        segments,_=_model().transcribe(str(path),language=language,beam_size=5)
        text=' '.join(s.text.strip() for s in segments).strip()
        return {'text':text,'audio':str(path)}
    finally:
        try:path.unlink()
        except OSError:pass


def speak(text,rate=180,volume=1.0):
    import pyttsx3
    engine=pyttsx3.init(); engine.setProperty('rate',int(rate)); engine.setProperty('volume',max(0,min(1,float(volume)))); engine.say(str(text)); engine.runAndWait(); engine.stop()
    return {'spoken_chars':len(str(text))}
