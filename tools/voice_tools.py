from .registry import register
from voice import listen,speak,is_available
register('voice_status','Comprueba voz local.',lambda:{'available':is_available()},{})
register('voice_listen','Escucha micrófono y transcribe localmente.',listen,{'seconds':'number opcional','language':'string opcional'},risk='medium')
register('voice_speak','Habla mediante TTS local.',speak,{'text':'string','rate':'number opcional','volume':'number opcional'})
